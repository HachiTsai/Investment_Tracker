"""price-dividend-fetcher 測試共用設定：不連網、不依賴真實核心持股清單。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import swing  # noqa: E402
import swing_sync  # noqa: E402

REAL_CORE_TICKERS = swing_sync.core_tickers


@pytest.fixture(autouse=True)
def _offline_and_no_core(monkeypatch):
    """證交所上市日清單一律回空（不連網）；同步管線的核心持股檢查預設無核心持股，要測的測試自行還原 REAL_CORE_TICKERS。"""
    monkeypatch.setattr(swing, "load_listing_dates", lambda fetch=None: {})
    monkeypatch.setattr(swing_sync, "core_tickers", lambda path=None: [])

REAL_LOAD_LISTING_DATES = swing.load_listing_dates
