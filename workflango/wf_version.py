"""
Workflow versions (#11): snapshot of a workflow, diff between snapshots, classification of the
changes and changelog (see the `propose_wf_version` management command).

A model declares the version of its workflow with ``configure_workflow(version='1.2.0')``.
The last released version is recorded in ``wf_version.json`` in the description folder
(``<app>/wf_doc/<model_name>/`` by default), next to the phases' ``.md`` files, and committed:

- ``phases``: the effective configuration of every phase (defaults applied; automatic reject
  transitions left out: they follow ``allow-reject``), in definition order;
- ``handlers``: the model's own ``validate_<from>_to_<to>`` methods and the generic handlers
  (``wf_doc.GENERIC_HANDLERS``), as hashes of their code (AST without docstring: comments and
  formatting do not count) and of their docstring;
- ``texts``: hashes of the ``.md`` files of the folder (long descriptions, preface, postface).

`diff()` compares the current workflow with the snapshot and classifies each change:

- **major**: phase added or removed (renaming = removed + added), start phase changed,
  destination added to or removed from ``reachable_phases``;
- **minor**: any other phase or transition key (groups, ``owner_mode``, ``allow-reject``,
  ``require_message``, ``is_closed``, properties, unknown keys…), handler added, removed or
  with different code;
- **patch**: texts (``caption``, ``description``, ``button-style``, handler docstrings,
  ``.md`` files).

Changes in code called by the handlers (helpers, services) are not seen: complete the generated
changelog by hand.
"""
import ast
import hashlib
import inspect
import json
import re
import textwrap
from dataclasses import dataclass
from datetime import date

from .i18n import wgettext

SNAPSHOT_FILE = 'wf_version.json'
CHANGELOG_FILE = 'CHANGELOG.md'

MAJOR, MINOR, PATCH = 'major', 'minor', 'patch'
LEVELS = (MAJOR, MINOR, PATCH)

# Keys whose change is cosmetic (patch); any other key is minor
PATCH_PHASE_KEYS = {'caption', 'description'}
PATCH_TRANSITION_KEYS = {'caption', 'description', 'button-style', 'tooltip'}

_VALIDATOR_RE = re.compile(r'^validate_\w+_to_\w+$')


@dataclass(frozen=True)
class Change:
    level: str
    text: str


# ---------------------------------------------------------------------------
# Snapshot

def _plain(value):
    """JSON-friendly copy of a config value (callables by qualified name, sets sorted)."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_plain(v) for v in value), key=repr)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if callable(value):
        return f'{getattr(value, "__module__", "")}.{getattr(value, "__qualname__", repr(value))}'
    return str(value)   # lazy translations, …


def _sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def _handler_hashes(method):
    """(code, doc) hashes of a method: code = AST of the function without its docstring."""
    func = inspect.unwrap(method)
    doc = inspect.getdoc(func) or ''
    try:
        node = ast.parse(textwrap.dedent(inspect.getsource(func))).body[0]
        body = node.body
        if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
        node.name = ''   # the name is the key of the snapshot entry
        code = ast.dump(node, annotate_fields=False)
    except (OSError, TypeError, SyntaxError, IndexError):
        code = repr(getattr(getattr(func, '__code__', None), 'co_code', func))
    return _sha(code), _sha(doc.strip())


def workflow_handlers(model):
    """{name: method} of the model's own workflow handlers."""
    from .wf_doc import GENERIC_HANDLERS, _own_method
    names = {n for n in dir(model) if _VALIDATOR_RE.match(n)} | set(GENERIC_HANDLERS)
    handlers = {}
    for name in sorted(names):
        method = _own_method(model, name)
        if method is not None:
            handlers[name] = method
    return handlers


def snapshot(cfg):
    """Snapshot of the current workflow of a WorkflowConfig (without version and date)."""
    phases = {}
    for phase in cfg.get_phases_list():
        conf = _plain({k: v for k, v in cfg[phase].items() if k != 'reachable_phases'})
        conf['reachable_phases'] = {
            dest: _plain(tconf) for dest, tconf in cfg[phase]['reachable_phases'].items()
            if (phase, dest) not in cfg._auto_rejects
        }
        phases[phase] = conf
    handlers = {}
    for name, method in workflow_handlers(cfg._model).items():
        code, doc = _handler_hashes(method)
        handlers[name] = {'code': code, 'doc': doc}
    texts = {}
    folder, _ = cfg.description_folder()
    if folder.is_dir():
        for path in sorted(folder.glob('*.md')):
            if path.name != CHANGELOG_FILE:
                texts[path.name] = _sha(path.read_text(encoding='utf-8'))
    return {'phases': phases, 'handlers': handlers, 'texts': texts}


def snapshot_path(cfg):
    folder, _ = cfg.description_folder()
    return folder / SNAPSHOT_FILE


def read_snapshot(cfg):
    """The recorded snapshot (dict with version and date), None if missing."""
    path = snapshot_path(cfg)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding='utf-8'))


def write_snapshot(cfg, version, today=None):
    data = {'version': version, 'date': (today or date.today()).isoformat(), **snapshot(cfg)}
    path = snapshot_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return data


# ---------------------------------------------------------------------------
# Diff

def _caption(phases, phase):
    return (phases.get(phase) or {}).get('caption') or phase


def _key_changes(old, new, patch_keys, label):
    """Changes of the keys of a phase or transition config."""
    changes = []
    for key in sorted(set(old) | set(new)):
        if old.get(key) == new.get(key):
            continue
        level = PATCH if key in patch_keys else MINOR
        changes.append(Change(level, wgettext('{where}: `{key}` changed ({old} → {new})').format(
            where=label, key=key, old=_short(old.get(key)), new=_short(new.get(key)))))
    return changes


def _short(value):
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 60 else text[:57] + '…'


def diff(old, new):
    """Classified changes from snapshot `old` to snapshot `new` (sorted by level)."""
    changes = []
    old_phases, new_phases = old.get('phases', {}), new.get('phases', {})
    for phase in new_phases:
        if phase not in old_phases:
            changes.append(Change(MAJOR, wgettext('Phase {phase} added').format(
                phase=f'«{_caption(new_phases, phase)}» (`{phase}`)')))
    for phase in old_phases:
        if phase not in new_phases:
            changes.append(Change(MAJOR, wgettext('Phase {phase} removed').format(
                phase=f'«{_caption(old_phases, phase)}» (`{phase}`)')))
    old_start = next(iter(old_phases), None)
    new_start = next(iter(new_phases), None)
    if old_start and new_start and old_start != new_start:
        changes.append(Change(MAJOR, wgettext('Start phase changed: {old} → {new}').format(
            old=f'`{old_start}`', new=f'`{new_start}`')))

    for phase in (p for p in new_phases if p in old_phases):
        o, n = old_phases[phase], new_phases[phase]
        where = f'«{_caption(new_phases, phase)}»'
        o_reach, n_reach = o.get('reachable_phases', {}), n.get('reachable_phases', {})
        for dest in n_reach:
            if dest not in o_reach:
                changes.append(Change(MAJOR, wgettext('{where}: destination {dest} added').format(
                    where=where, dest=f'«{_caption(new_phases, dest)}»')))
        for dest in o_reach:
            if dest not in n_reach:
                changes.append(Change(MAJOR, wgettext('{where}: destination {dest} removed').format(
                    where=where, dest=f'«{_caption(old_phases, dest)}»')))
        for dest in (d for d in n_reach if d in o_reach):
            changes += _key_changes(o_reach[dest], n_reach[dest], PATCH_TRANSITION_KEYS,
                                    f'{where} → «{_caption(new_phases, dest)}»')
        changes += _key_changes({k: v for k, v in o.items() if k != 'reachable_phases'},
                                {k: v for k, v in n.items() if k != 'reachable_phases'},
                                PATCH_PHASE_KEYS, where)

    old_handlers, new_handlers = old.get('handlers', {}), new.get('handlers', {})
    for name in sorted(set(old_handlers) | set(new_handlers)):
        o, n = old_handlers.get(name), new_handlers.get(name)
        if o is None:
            changes.append(Change(MINOR, wgettext('`{name}()` added').format(name=name)))
        elif n is None:
            changes.append(Change(MINOR, wgettext('`{name}()` removed').format(name=name)))
        elif o['code'] != n['code']:
            changes.append(Change(MINOR, wgettext('`{name}()`: code changed').format(name=name)))
        elif o['doc'] != n['doc']:
            changes.append(Change(PATCH, wgettext('`{name}()`: docstring changed').format(name=name)))

    old_texts, new_texts = old.get('texts', {}), new.get('texts', {})
    for name in sorted(set(old_texts) | set(new_texts)):
        if old_texts.get(name) != new_texts.get(name):
            changes.append(Change(PATCH, wgettext('`{name}` changed').format(name=name)))

    return sorted(changes, key=lambda c: LEVELS.index(c.level))


# ---------------------------------------------------------------------------
# Versions

def parse_version(version):
    """'1.2.3' → (1, 2, 3); ValueError if not MAJOR.MINOR.PATCH."""
    parts = str(version).split('.')
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f'Invalid workflow version {version!r} (expected MAJOR.MINOR.PATCH)')
    return tuple(int(p) for p in parts)


def required_level(changes):
    """The highest level among the changes (None: no change)."""
    for level in LEVELS:
        if any(c.level == level for c in changes):
            return level
    return None


def bump(version, level):
    major, minor, patch = parse_version(version)
    if level == MAJOR:
        return f'{major + 1}.0.0'
    if level == MINOR:
        return f'{major}.{minor + 1}.0'
    if level == PATCH:
        return f'{major}.{minor}.{patch + 1}'
    return version


def is_enough(proposed, recorded, level):
    """Whether version `proposed` is a large enough bump of `recorded` for `level`."""
    return parse_version(proposed) >= parse_version(bump(recorded, level))


# ---------------------------------------------------------------------------
# Changelog

_LEVEL_TITLES = {MAJOR: 'Major changes', MINOR: 'Minor changes', PATCH: 'Texts'}


def changelog_entry(version, changes, today=None, initial=False):
    lines = [f'## [{version}] - {(today or date.today()).isoformat()}', '']
    if initial:
        lines += [wgettext('Initial version.'), '']
    for level in LEVELS:
        items = [c.text for c in changes if c.level == level]
        if items:
            lines += [f'### {wgettext(_LEVEL_TITLES[level])}', '', *(f'- {t}' for t in items), '']
    return '\n'.join(lines)


def write_changelog(cfg, entry, title):
    """Prepend `entry` to <description folder>/CHANGELOG.md (created with `title`)."""
    folder, _ = cfg.description_folder()
    path = folder / CHANGELOG_FILE
    if path.is_file():
        text = path.read_text(encoding='utf-8')
        head, sep, rest = text.partition('\n## ')
        text = f'{head.rstrip()}\n\n{entry}\n' + (f'\n## {rest}' if sep else '')
    else:
        text = f'# {title}\n\n{entry}\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + '\n', encoding='utf-8')
    return path


# ---------------------------------------------------------------------------
# Check

def check_version(cfg):
    """Warnings about the workflow version: changes not recorded in the snapshot, version
    declared in configure_workflow different from the recorded one. [] when not versioned."""
    version = cfg.version
    if version is None:
        return []
    name = cfg._model.__name__
    try:
        parse_version(version)
    except ValueError as e:
        return [f'{name}: {e}']
    recorded = read_snapshot(cfg)
    if recorded is None:
        return [f'{name}: version {version} not recorded ({SNAPSHOT_FILE} missing): '
                f'run propose_wf_version --write']
    warnings = []
    changes = diff(recorded, snapshot(cfg))
    if changes:
        warnings.append(
            f'{name}: workflow changed since version {recorded["version"]} '
            f'({len(changes)} changes, {required_level(changes)}): run propose_wf_version')
    elif version != recorded['version']:
        warnings.append(f'{name}: configure_workflow(version={version!r}) differs from the '
                        f'recorded version {recorded["version"]}')
    return warnings
