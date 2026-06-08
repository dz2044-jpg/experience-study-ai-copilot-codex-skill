from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sample_csv_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "input" / "synthetic_inforce.csv"
