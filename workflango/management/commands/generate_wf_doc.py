from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import translation

from workflango.management.utils import get_model_list
from workflango.wf_doc import check_template, workflow_document


class Command(BaseCommand):

    help = ('Writes the Markdown documentation of a model\'s workflow configuration (graph, phases '
            'and configuration details; --plain without details), after checking the configuration.')

    def add_arguments(self, parser):
        parser.add_argument('model', metavar='appname.model', help='The WorkflowModel to document.')
        parser.add_argument('output', nargs='?',
            help='Output file (default: docs/workflow/<Model>.md).')
        parser.add_argument('--plain', action='store_true',
            help='Leave out configuration keys, validate_* methods and workflow handlers.')
        parser.add_argument('--nograph', action='store_true',
            help='Leave out the mermaid graph of the phases.')
        parser.add_argument('--print', action='store_true', dest='print_only',
            help='Print the document instead of writing a file.')
        parser.add_argument('--language', default=settings.LANGUAGE_CODE,
            help='Language of the generated labels (default: LANGUAGE_CODE).')
        parser.add_argument('--template', metavar='FILE',
            help='Markdown template wrapping the document (placeholders {{ title }}, {{ version }}, '
                 '{{ version_label }}, {{ model }}, {{ verbose_name }}, {{ date }}, {{ content }}; '
                 '{{ content }} required). Default: settings.WF_DOC_TEMPLATE, if set.')
        parser.add_argument('--no-template', action='store_true',
            help='Ignore settings.WF_DOC_TEMPLATE.')
        parser.add_argument('--no-changelog', action='store_true',
            help='Version without the link to the workflow changelog (e.g. for an online help, '
                 'where the changelog is not reachable).')

    def handle(self, *args, **options):
        [model] = get_model_list(options['model'])
        try:
            model.wfm_config.check()
        except Exception as e:
            raise CommandError(f'{model.__name__}: {e}') from e
        for warning in [*model.wfm_config.check_descriptions(), *model.wfm_config.check_version()]:
            self.stderr.write(self.style.WARNING(f'WARNING: {warning}'))

        template = self._template(options)
        output = options['output'] or str(Path('docs') / 'workflow' / f'{model.__name__}.md')
        with translation.override(options['language']):
            text = workflow_document(model, template, detailed=not options['plain'],
                                     graph=not options['nograph'],
                                     base_dir=Path(output).parent.resolve(),
                                     changelog=not options['no_changelog'])

        if options['print_only']:
            self.stdout.write(text, ending='')
            return
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(f'{model.__name__}: {path}'))

    def _template(self, options):
        """Text of the document template (--template, else settings.WF_DOC_TEMPLATE), None for
        no template. CommandError, before anything is written, if missing or without
        {{ content }}."""
        path = options['template']
        if path is None and not options['no_template']:
            path = getattr(settings, 'WF_DOC_TEMPLATE', None)
        if not path:
            return None
        path = Path(path)
        if not path.is_file():
            raise CommandError(f'Template not found: {path}')
        template = path.read_text(encoding='utf-8')
        try:
            check_template(template)
        except ValueError as e:
            raise CommandError(f'{path}: {e}') from e
        return template
