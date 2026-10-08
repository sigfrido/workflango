from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import translation

from workflango.management.utils import get_model_list
from workflango.wf_doc import workflow_markdown


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

    def handle(self, *args, **options):
        [model] = get_model_list(options['model'])
        try:
            model.wfm_config.check()
        except Exception as e:
            raise CommandError(f'{model.__name__}: {e}') from e
        for warning in model.wfm_config.check_descriptions():
            self.stderr.write(self.style.WARNING(f'WARNING: {warning}'))

        with translation.override(options['language']):
            text = workflow_markdown(model, detailed=not options['plain'], graph=not options['nograph'])

        if options['print_only']:
            self.stdout.write(text, ending='')
            return
        output = options['output'] or str(Path('docs') / 'workflow' / f'{model.__name__}.md')
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(f'{model.__name__}: {path}'))
