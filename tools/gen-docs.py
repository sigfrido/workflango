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
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'testproject'))

import django  # noqa: E402

import os  # noqa: E402
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
django.setup()

import pdoc  # noqa: E402
import pdoc.render  # noqa: E402

OUT_DIR = ROOT / 'docs' / 'api'

if __name__ == '__main__':
    shutil.rmtree(OUT_DIR, ignore_errors=True)
    pdoc.render.configure(docformat='restructuredtext')
    pdoc.pdoc('workflango', output_directory=OUT_DIR)
    print(f'Generated {OUT_DIR}/workflango.html')
