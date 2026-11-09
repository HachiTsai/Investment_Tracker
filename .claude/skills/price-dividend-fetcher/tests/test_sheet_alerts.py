"""巡檢頁讀波段觀察 Sheet「告警紀錄」的單元測試（離線，不連網）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import swing  # noqa: E402

CSV = """"偵測時間","代號","名稱","上次組合","這次組合","狀態","收盤","2xATR停損價"
"2026-11-05 23:50:37 (TPE)","TPE:00882","中信中國高股息","其他","長多短回檔","x","15","14"
"2026-11-06 01:13:00 (TPE)","TPE:0050","元大台灣50","其他","共振偏多","x","60","58"
"2026-11-06 01:13:00 (TPE)","NASDAQ:AAPL","Apple","長多短回檔","共振偏空","x","200","190"
"""


def test_parse_takes_latest_detection_date():
    got = swing.parse_sheet_alerts(CSV, "2026-11-09")
    assert set(got) == {"TPE:0050", "NASDAQ:AAPL"}
    assert got["NASDAQ:AAPL"] == {"prev_combo": "長多短回檔", "combo": "共振偏空", "date": "2026-11-06"}


def test_parse_ignores_stale_or_empty():
    assert swing.parse_sheet_alerts(CSV, "2026-11-11") == {}  # 距最近偵測日 5 天
    assert swing.parse_sheet_alerts('"偵測時間","代號"\n', "2026-11-09") == {}
    assert swing.parse_sheet_alerts("", "2026-11-09") == {}


def test_apply_only_when_combo_still_matches():
    alerts = swing.parse_sheet_alerts(CSV, "2026-11-09")
    rows = [
        {"ticker": "TPE:0050", "combo": "共振偏多", "alert": False},
        {"ticker": "NASDAQ:AAPL", "combo": "其他", "alert": False},  # 組合已變回，不再提醒
        {"ticker": "TPE:00882", "combo": "長多短回檔", "alert": False},  # 不在最近一批
    ]
    lit = swing.apply_sheet_alerts(rows, alerts)
    assert lit == ["TPE:0050"]
    assert rows[0]["alert"] is True and rows[0]["prev_combo"] == "其他"
    assert rows[1]["alert"] is False and rows[2]["alert"] is False


def test_sheet_id_from_drive_ids(monkeypatch):
    monkeypatch.setenv("DRIVE_IDS", '{"SWING_SHEET_ID": "TEST_SWING"}')
    assert swing._swing_sheet_id() == "TEST_SWING"
    monkeypatch.setenv("DRIVE_IDS", "not json")
    assert swing._swing_sheet_id() is None
    monkeypatch.delenv("DRIVE_IDS")
    assert swing._swing_sheet_id() is None


def test_parse_sheet_last_updated_handles_both_labels():
    assert swing.parse_sheet_last_updated('"lastUpdated","2026-11-06 15:50:42 (TPE)"\n"executor","GitHub Actions"\n') == "2026-11-06 15:50:42 (TPE)"
    assert swing.parse_sheet_last_updated('"最後巡檢時間","2026-11-07 01:02:03 (TPE)"\n"狀態","休市略過"\n') == "2026-11-07 01:02:03 (TPE)"
    assert swing.parse_sheet_last_updated("") is None
