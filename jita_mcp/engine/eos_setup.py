"""Wire pyfa's eos engine into our project at import time.

eos is vendored as part of pyfa at vendor/pyfa/eos/. It expects:
  - vendor/pyfa/ on sys.path so `import eos` works
  - a `config` module at root that exposes `savePath` and `saveDB` — we shim
    this to avoid pulling in pyfa's wx-dependent root config
  - `TRAVIS=true` (or `_called_from_test`) so saveddata runs in memory; we
    only ever read gamedata, never persist fits

Import this module once, before anything that touches eos. The actual eos.db
import has a circular-import quirk (eos.saveddata.* must not be imported before
eos.db); use `setup()` to do it safely.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PYFA_DIR = Path(__file__).resolve().parent.parent.parent / "vendor" / "pyfa"
_SHIM_DIR = Path(__file__).resolve().parent / "_pyfa_shim"

_initialized = False


def setup() -> None:
    """Idempotent. Adds shim + pyfa to sys.path and sets the test env var.

    Does NOT import eos.db — callers do that themselves. Pre-importing it
    here would open a connection to eve.db (creating an empty file if absent)
    that conflicts with pyfa's db_update.py, which deletes and rebuilds the
    file expecting no live handle.

    Circular-import gotcha: eos.saveddata.* must not be imported before
    eos.db. After setup(), always do `import eos.db` first.
    """
    global _initialized
    if _initialized:
        return

    os.environ.setdefault("TRAVIS", "true")

    # Order matters: each `insert(0, ...)` prepends, so we add pyfa first and
    # the shim second so the shim ends up *ahead* of pyfa in sys.path. That
    # lets our config.py shadow pyfa's wx-tainted root config.py.
    for p in (str(_PYFA_DIR), str(_SHIM_DIR)):
        if p not in sys.path:
            sys.path.insert(0, p)

    _initialized = True
