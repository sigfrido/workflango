"""
Markdown documentation of a model's workflow configuration (see the `generate_wf_doc`
management command).

`workflow_markdown(model, detailed=True, graph=True)` returns a Markdown document,
browseable on GitHub and includable in pdoc documentation:

- mermaid graph of the phases (unless graph=False) (top-down; forward transitions labeled with their
  caption; reject transitions only when declared in the config, not the automatic ones),
  each phase linked to its section;
- one section per phase, in definition order: caption, description, long description
  (<description folder>/<phase>.md, Markdown as is) and the reachable phases (linked);
- unless `detailed=False`: the phase and transition configuration keys (dicts as YAML), the
  `validate_*` methods of the model concerning each phase and the generic workflow handlers,
  with their docstrings.
"""
import inspect
import json
import re

from .i18n import wgettext

# Generic hooks called by the workflow engine (beyond the per-phase validate_* methods)
GENERIC_HANDLERS = ('validate_phase_transition', 'after_state_transition', 'get_workflow_snapshot')

# Phase-level keys shown in the detailed configuration table (texts are shown elsewhere)
_PHASE_KEYS = ('read', 'edit', 'admin', 'is_closed', 'allow_release', 'allow_delegate',
               'snapshot', 'properties')
_TEXT_KEYS = ('caption', 'description', 'reachable_phases')


def anchor(phase):
    return f'phase-{_slug(phase)}'


def _slug(phase):
    return re.sub(r'[^0-9A-Za-z_-]', '-', str(phase))


def _node(phase):
    return 'start' if phase is None else f'phase_{re.sub(r"[^0-9A-Za-z_]", "_", str(phase))}'


def _mermaid_label(text):
    return str(text).replace('"', '#quot;')


def _cell(value):
    """Value of a configuration key, readable in a Markdown table cell."""
    if callable(value):
        doc = inspect.getdoc(value)
        name = getattr(value, '__name__', repr(value))
        return f'`{name}()`' + (f' — {doc.splitlines()[0]}' if doc else '')
    if isinstance(value, (set, frozenset)):
        value = sorted(value)
    if isinstance(value, (list, tuple)):
        text = ', '.join(str(v) for v in value) if value else '—'
    elif isinstance(value, dict):  # non-empty dicts are rendered as YAML blocks (_yaml_block)
        text = '{}' if not value else ', '.join(f'{k}: {_yaml_scalar(v)}' for k, v in value.items())
    else:
        text = str(value)
    return text.replace('|', '\\|').replace('\n', ' ')


def _yaml_scalar(value):
    if callable(value):
        return getattr(value, '__name__', repr(value)) + '()'
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (set, frozenset)):
        value = sorted(value)
    if isinstance(value, (list, tuple)):
        return '[' + ', '.join(_yaml_scalar(v) for v in value) + ']'
    if isinstance(value, dict):
        return '{' + ', '.join(f'{k}: {_yaml_scalar(v)}' for k, v in value.items()) + '}'
    text = str(value)
    plain = (text and text.strip() == text and not text[0] in '-?:,[]{}#&*!|>\'"%@`'
             and ': ' not in text and ' #' not in text
             and text.lower() not in ('true', 'false', 'yes', 'no', 'null', '~', 'on', 'off'))
    return text if plain else json.dumps(text, ensure_ascii=False)


def _yaml(value, indent=0):
    """Block-style YAML lines of a dict/list of plain values (no dependency on PyYAML)."""
    pad = '  ' * indent
    lines = []
    if isinstance(value, (set, frozenset)):
        value = sorted(value)
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list, tuple, set, frozenset)) and item:
                lines.append(f'{pad}{_yaml_scalar(str(key))}:')
                lines += _yaml(item, indent + 1)
            else:
                lines.append(f'{pad}{_yaml_scalar(str(key))}: {_yaml_scalar(item)}')
    else:
        for item in value:
            if isinstance(item, (dict, list, tuple, set, frozenset)) and item:
                sub_lines = _yaml(item, indent + 1)
                lines.append(f'{pad}- {sub_lines[0].lstrip()}')
                lines += sub_lines[1:]
            else:
                lines.append(f'{pad}- {_yaml_scalar(item)}')
    return lines


def _yaml_block(value, prefix=''):
    return [f'{prefix}```yaml', *(prefix + line for line in _yaml(value)), f'{prefix}```']


def _docstring(obj):
    doc = inspect.getdoc(obj)
    return doc.strip() if doc else ''


def _own_method(model, name):
    """The model's method `name`, if defined by the model (not inherited from WorkflowModel)."""
    from .models import WorkflowModel
    method = getattr(model, name, None)
    if not callable(method):
        return None
    if getattr(WorkflowModel, name, None) is method:
        return None
    return method


def _transition_caption(conf):
    caption = conf.get('caption')
    return caption if isinstance(caption, str) else ''


def _graph(cfg):
    lines = ['```mermaid', 'flowchart TD']
    lines.append(f'    start(("{_mermaid_label(wgettext("Start"))}"))')
    for phase in cfg.get_phases_list():
        label = _mermaid_label(cfg.phase_caption(phase))
        shape = f'(["{label}"])' if cfg[phase].get('is_closed') else f'["{label}"]'
        lines.append(f'    {_node(phase)}{shape}')
    for source in [None, *cfg.get_phases_list()]:
        for dest, conf in cfg[source]['reachable_phases'].items():
            if dest == source or cfg.is_auto_reject(source, dest):
                continue
            caption = _transition_caption(conf)
            arrow = '-.->' if conf.get('reject') else '-->'
            edge_label = f'|"{_mermaid_label(caption)}"|' if caption else ''
            lines.append(f'    {_node(source)} {arrow}{edge_label} {_node(dest)}')
    for phase in cfg.get_phases_list():
        lines.append(f'    click {_node(phase)} "#{anchor(phase)}"')
    lines.append('```')
    return lines


def _transitions(cfg, phase, detailed):
    lines = []
    reachable = cfg[phase]['reachable_phases']
    if not reachable:
        return [f'_{wgettext("No outgoing transitions.")}_']
    for dest, conf in reachable.items():
        if dest == phase:
            continue
        item = f'- [{cfg.phase_caption(dest)}](#{anchor(dest)})'
        caption = _transition_caption(conf)
        if caption:
            item += f' — «{caption}»'
        if conf.get('reject'):
            item += f' ({wgettext("send back")})'
        lines.append(item)
        if detailed:
            keys = {k: v for k, v in conf.items() if k not in ('caption', 'reject')}
            if cfg.is_auto_reject(phase, dest):
                keys['auto'] = wgettext('generated from the forward transition')
            for key, value in keys.items():
                if isinstance(value, dict) and value:
                    lines += [f'    - `{key}`:', '', *_yaml_block(value, prefix='      '), '']
                else:
                    lines.append(f'    - `{key}`: {_cell(value)}')
    return lines


def _validators(model, cfg, phase):
    names = [f'validate_{phase}_to_any', f'validate_any_to_{phase}']
    names += [f'validate_{phase}_to_{dest}' for dest in cfg[phase]['reachable_phases'] if dest != phase]
    lines = []
    for name in names:
        method = _own_method(model, name)
        if method is None:
            continue
        lines.append(f'- `{name}()`')
        doc = _docstring(method)
        if doc:
            lines.extend(f'    {row}' if row else '' for row in doc.splitlines())
    return lines


def workflow_markdown(model, detailed=True, graph=True):
    cfg = model.wfm_config
    title = str(model._meta.verbose_name)
    lines = [f'# {title[:1].upper()}{title[1:]} — {wgettext("workflow")}', '']

    initial = [d for d in cfg[None]['reachable_phases']]
    if initial:
        link = ', '.join(f'[{cfg.phase_caption(p)}](#{anchor(p)})' for p in initial)
        lines += [f'**{wgettext("Start")}**: {link}', '']

    if graph:
        lines += _graph(cfg) + ['']

    lines += [f'## {wgettext("Phases")}', '']
    for phase in cfg.get_phases_list():
        conf = cfg[phase]
        lines += [f'<a id="{anchor(phase)}"></a>', '', f'### {cfg.phase_caption(phase)}', '']
        if conf.get('description'):
            lines += [f'_{conf["description"]}_', '']
        if conf.get('is_closed'):
            lines += [f'**{wgettext("Final phase")}**', '']
        long_description = cfg.phase_long_description(phase).strip()
        if long_description:
            lines += [long_description, '']
        if detailed:
            lines += [f'#### {wgettext("Configuration")}', '',
                      f'| {wgettext("Key")} | {wgettext("Value")} |', '|---|---|',
                      f'| {wgettext("phase code")} | `{phase}` |']
            others = [k for k in conf if k not in _PHASE_KEYS and k not in _TEXT_KEYS]
            keys = [k for k in (*_PHASE_KEYS, *others) if k in conf]
            blocks = [k for k in keys if isinstance(conf[k], dict) and conf[k]]
            for key in keys:
                if key not in blocks:
                    lines.append(f'| `{key}` | {_cell(conf[key])} |')
            lines.append('')
            for key in blocks:  # dicts (e.g. properties) as YAML, after the table
                lines += [f'`{key}`:', '', *_yaml_block(conf[key]), '']
        lines += [f'#### {wgettext("Next phases")}', '', *_transitions(cfg, phase, detailed), '']
        if detailed:
            validators = _validators(model, cfg, phase)
            if validators:
                lines += [f'#### {wgettext("Validations")}', '', *validators, '']

    if detailed:
        handlers = [(name, _own_method(model, name)) for name in GENERIC_HANDLERS]
        handlers = [(name, method) for name, method in handlers if method is not None]
        if handlers:
            lines += [f'## {wgettext("Generic workflow handlers")}', '']
            for name, method in handlers:
                lines += [f'### `{name}()`', '']
                doc = _docstring(method)
                lines += [doc, ''] if doc else []

    return '\n'.join(lines).rstrip() + '\n'
