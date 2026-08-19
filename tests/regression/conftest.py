from __future__ import annotations

import pickle

import pytest

from _project_root import PROJECT_ROOT

GOLDEN_DIR = PROJECT_ROOT / "tests" / "regression"

HAS_GOLDEN_EURUSD = (GOLDEN_DIR / "golden_eurusd_h1.pkl").exists()
HAS_GOLDEN_GBPUSD = (GOLDEN_DIR / "golden_gbpusd_h1.pkl").exists()


def _load_golden(filename: str) -> dict:
    path = GOLDEN_DIR / filename
    with open(path, "rb") as f:
        return pickle.load(f)


@pytest.fixture(scope="session")
def golden_eurusd():
    if not HAS_GOLDEN_EURUSD:
        pytest.skip("golden_eurusd_h1.pkl not found")
    return _load_golden("golden_eurusd_h1.pkl")


@pytest.fixture(scope="session")
def golden_gbpusd():
    if not HAS_GOLDEN_GBPUSD:
        pytest.skip("golden_gbpusd_h1.pkl not found")
    return _load_golden("golden_gbpusd_h1.pkl")


@pytest.fixture(scope="session")
def golden_data(golden_eurusd, golden_gbpusd):
    return {"EURUSD": golden_eurusd, "GBPUSD": golden_gbpusd}


@pytest.fixture(scope="session")
def eurusd_h1_data():
    import pandas as pd

    data_path = PROJECT_ROOT / "data" / "EURUSD_1h.parquet"
    if not data_path.exists():
        pytest.skip("EURUSD H1 data not found")
    df = pd.read_parquet(data_path)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


@pytest.fixture(scope="session")
def gbpusd_h1_data():
    import pandas as pd

    data_path = PROJECT_ROOT / "data" / "GBPUSD_1h.parquet"
    if not data_path.exists():
        pytest.skip("GBPUSD H1 data not found")
    df = pd.read_parquet(data_path)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


@pytest.fixture(scope="session")
def h1_data(eurusd_h1_data, gbpusd_h1_data):
    return {"EURUSD": eurusd_h1_data, "GBPUSD": gbpusd_h1_data}
