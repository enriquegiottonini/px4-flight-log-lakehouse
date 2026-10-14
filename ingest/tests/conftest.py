import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def expected() -> dict:
    return json.loads((FIXTURES / "expected.json").read_text())


@pytest.fixture(scope="session")
def load_json():
    return lambda name: json.loads((FIXTURES / name).read_text())
