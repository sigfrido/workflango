from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import translation

from workflango import wf_version
from workflango.i18n import wgettext
from workflango.management.utils import get_model_list


class Command(BaseCommand):

    help = ('Compares a model\'s workflow with its last recorded version (wf_version.json in the '
            'description folder), lists the changes (major / minor / patch) and proposes the next '
            'version; --write records it and adds the entry to the workflow CHANGELOG.md. '
            'Development tool, not for production.')

    def add_arguments(self, parser):
        parser.add_argument('model', metavar='appname.model', help='The WorkflowModel.')
        parser.add_argument('--new-version', dest='new_version',
            help='Version to record (default: the one in configure_workflow, else the proposed one).')
        parser.add_argument('--write', action='store_true',
            help='Record the version: write wf_version.json and the CHANGELOG.md entry.')
        parser.add_argument('--check', action='store_true',
            help='Fail if the workflow has unrecorded changes or its version is not the recorded one.')
        parser.add_argument('--language', default=settings.LANGUAGE_CODE,
            help='Language of the changelog entry (default: LANGUAGE_CODE).')

    def handle(self, *args, **options):
        [model] = get_model_list(options['model'])
        cfg = model.wfm_config
        try:
            cfg.check()
        except Exception as e:
            raise CommandError(f'{model.__name__}: {e}') from e

        with translation.override(options['language']):
            self._handle(model, cfg, options)

    def _handle(self, model, cfg, options):
        name = model.__name__
        recorded = wf_version.read_snapshot(cfg)
        declared = cfg.version

        if options['check']:
            warnings = wf_version.check_version(cfg)
            if declared is None:
                raise CommandError(f'{name}: no version in configure_workflow(version=...)')
            if warnings:
                raise CommandError('\n'.join(warnings))
            self.stdout.write(self.style.SUCCESS(f'{name}: version {declared} recorded, no changes'))
            return

        if recorded is None:
            version = options['new_version'] or declared or '1.0.0'
            wf_version.parse_version(version)
            self.stdout.write(f'{name}: no recorded version; initial version {version}')
            if options['write']:
                self._write(cfg, name, version, [], initial=True)
            self._remind(name, declared, version)
            return

        changes = wf_version.diff(recorded, wf_version.snapshot(cfg))
        level = wf_version.required_level(changes)
        if not changes:
            self.stdout.write(f'{name}: no changes since version {recorded["version"]}')
            self._remind(name, declared, recorded['version'])
            return

        proposed = wf_version.bump(recorded['version'], level)
        self.stdout.write(f'{name}: {len(changes)} changes since version {recorded["version"]} '
                          f'({level}) — proposed version {proposed}\n')
        for change in changes:
            self.stdout.write(f'  [{change.level}] {change.text}')
        self.stdout.write('')

        version = options['new_version'] or (declared if declared != recorded['version'] else None) or proposed
        wf_version.parse_version(version)
        if not wf_version.is_enough(version, recorded['version'], level):
            raise CommandError(f'{name}: version {version} too low for {level} changes '
                               f'(at least {proposed})')
        if options['write']:
            self._write(cfg, name, version, changes)
        else:
            self.stdout.write(f'Run with --write to record version {version}.')
        self._remind(name, declared, version)

    def _write(self, cfg, name, version, changes, initial=False):
        entry = wf_version.changelog_entry(version, changes, initial=initial)
        title = f'{cfg._model._meta.verbose_name} — {wgettext("workflow changelog")}'
        path = wf_version.write_changelog(cfg, entry, title[:1].upper() + title[1:])
        wf_version.write_snapshot(cfg, version)
        self.stdout.write(self.style.SUCCESS(
            f'{name}: version {version} recorded ({wf_version.snapshot_path(cfg)}, {path})'))

    def _remind(self, name, declared, version):
        if declared != version:
            self.stdout.write(self.style.WARNING(
                f'{name}: set configure_workflow(version={version!r}, ...)'
                + (f' (now {declared!r})' if declared else '')))
