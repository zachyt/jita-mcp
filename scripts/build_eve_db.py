#!/usr/bin/env python3
"""Build vendor/pyfa/eve.db from pyfa's bundled JSON staticdata.

Wraps pyfa's db_update.py so it runs through our eos import shim — pyfa's
script does `import eos.db` directly, which without the shim pulls in
pyfa's wx-dependent root config.py.

Idempotent: pyfa's db_update.py drops and recreates eve.db on each run.
"""

from __future__ import annotations

import os
import runpy
from pathlib import Path

from jita_mcp.engine.eos_setup import setup

setup()

PYFA_DIR = Path(__file__).resolve().parent.parent / "vendor" / "pyfa"

# db_update.py uses relative paths into staticdata/ — run from pyfa's root.
os.chdir(PYFA_DIR)
runpy.run_path("db_update.py", run_name="__main__")
