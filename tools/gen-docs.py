#!/usr/bin/env python
"""
Regenerate the API reference at docs/api/ from the workflango source docstrings.

Requires the dev extra: pip install -e ".[dev]" pdoc

A plain `pdoc workflango` CLI invocation cannot import the package on its own:
workflango/admin.py (and other modules) touch Django's model machinery at
import time, which raises AppRegistryNotReady unless django.setup() has
already run. This script calls django.setup() first (against testproject's
settings, which has workflango + demo in INSTALLED_APPS) and then drives
pdoc's programmatic API instead of its CLI.

workflango.contrib.sebastian additionally requires drf-sebastian, an optional
dependency not published anywhere pip could resolve it from (see
docs/sebastian-integration.md) -- to get it fully documented rather than
stubbed out below, install the sibling checkout editable first:

    pip install -r requirements-dev-local.txt

(gitignored, machine-specific -- not part of the [dev] extra in
pyproject.toml, which must stay installable by anyone). Without it,
`pdoc.pdoc('workflango', ...)` would abort the whole run, since it recurses
into every submodule on its own and fails hard if any single one can't be
imported -- so this script walks the package itself first and pre-registers
a stub module (just a docstring pointing at the doc above) in sys.modules
for anything that fails to import -- pdoc's own import then
hits the cached sys.modules entry instead of re-running the raising import.
"""
import importlib
import pkgutil
import shutil
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'testproject'))

import django  # noqa: E402

import os  # noqa: E402
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
django.setup()

import pdoc  # noqa: E402
import pdoc.render  # noqa: E402

import workflango  # noqa: E402

OUT_DIR = ROOT / 'docs' / 'api'

if __name__ == '__main__':
    for modinfo in pkgutil.walk_packages(workflango.__path__, prefix='workflango.'):
        try:
            importlib.import_module(modinfo.name)
        except ImportError as e:
            print(f'Stubbing {modinfo.name} (optional dependency not installed: {e})', file=sys.stderr)
            stub = types.ModuleType(modinfo.name)
            stub.__doc__ = (
                f'Not documented in this build -- failed to import ({e}). '
                'See docs/sebastian-integration.md.'
            )
            sys.modules[modinfo.name] = stub

    shutil.rmtree(OUT_DIR, ignore_errors=True)
    pdoc.render.configure(docformat='restructuredtext')
    pdoc.pdoc('workflango', output_directory=OUT_DIR)
    print(f'Generated {OUT_DIR}/workflango.html')
