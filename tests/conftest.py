"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def mini_sde_path() -> Path:
    """Path to the tiny synthetic SDE used by unit tests.

    The fixture is built by scripts/build_test_fixture.py and committed to the repo so
    unit tests can run without the 700MB production SDE.
    """
    path = FIXTURES_DIR / "sde_mini.sqlite"
    if not path.exists():
        pytest.skip("mini SDE fixture not built; run scripts/build_test_fixture.py")
    return path
