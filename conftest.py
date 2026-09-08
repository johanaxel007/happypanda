"""Pytest configuration.

The application modules import each other flatly (``import app_constants`` rather than
``import version.app_constants``), so ``version/`` itself has to be importable as a
top-level package directory. The repository root goes on the path too, for the tests that
import through ``version.<module>``.
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
VERSION_DIR = os.path.join(ROOT, 'version')

for path in (ROOT, VERSION_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)
