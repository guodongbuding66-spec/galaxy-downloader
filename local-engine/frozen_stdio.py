"""Provide writable streams for libraries when launched with pythonw/PyInstaller."""
import os
import sys

for name in ('stdout', 'stderr'):
    if getattr(sys, name) is None:
        path = os.environ.get('GALAXY_DIAGNOSTIC_LOG') or os.devnull
        setattr(sys, name, open(path, 'a', encoding='utf-8', buffering=1))
