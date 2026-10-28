"""波段關鍵組合告警：先寫「告警紀錄」分頁，寫失敗就不覆寫 A:X。"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from swing_sync import ALERT_TAB, append_alert_rows, fresh_alerts, report_alerts, run_swing_pipeline  # noqa: E402

HEADER = ["代號", "名稱", "市場", "來源", "狀態", "收盤"] + [""] * 18
EXISTING = [HEADER, ["TPE:2330", "台積電", "TW", "核心", "舊狀態", "900.0"] + [""] * 18]
NEW_SHEET = [HEADER, ["TPE:2330", "台積電", "TW", "核心", "新狀態", "950.0"] + [""] * 18]
ALERT = {
    "ticker": "TPE:2330", "name": "台積電", "label": "🟢 突破", "close": 950.0, "stop_price": 900.0,
    "prev_combo": "長多短回檔", "combo": "共振偏多", "alert": True, "fresh": True,
}


def _alert_tab_down(sheet_id, range_name):
    if range_name.startswith(f"'{ALERT_TAB}'!"):
        raise RuntimeError("Sheets API 暫時失敗")
    return EXISTING


def _alert_tab_ready(sheet_id, range_name):
    if range_name.startswith(f"'{ALERT_TAB}'!"):
        return [["偵測時間"]]
    return EXISTING


def _run_with_scan(client, scan_rows):
    Path("/tmp/sheet.json").write_text(json.dumps(NEW_SHEET), encoding="utf-8")
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0, stdout=json.dumps(scan_rows))
        return run_swing_pipeline(sheet_id="fake_id", client=client)


def test_fresh_alerts_skips_stale_and_unchanged_rows():
    stale = dict(ALERT, fresh=False)
    unchanged = dict(ALERT, alert=False)
    assert fresh_alerts([ALERT, stale, unchanged]) == [ALERT]


def test_append_alert_rows_creates_tab_and_keeps_ticker_as_text():
    client = MagicMock()
    client.get_spreadsheet.return_value = {"sheets": [{"properties": {"title": "Untitled"}}]}
    client.get_values.return_value = []

    append_alert_rows(client, "fake_id", [ALERT], "2026-10-28 15:20:00 (TPE)")

    assert client.batch_update.call_args[0][1][0]["addSheet"]["properties"]["title"] == ALERT_TAB
    header_call, row_call = client.update_values.call_args_list
    assert header_call[0][1] == f"'{ALERT_TAB}'!A1:H1"
    assert row_call[0][1] == f"'{ALERT_TAB}'!A2:H2"
    assert row_call[0][2] == [
        ["2026-10-28 15:20:00 (TPE)", "'TPE:2330", "台積電", "長多短回檔", "共振偏多", "🟢 突破", 950.0, 900.0],
    ]


def test_append_alert_rows_goes_below_existing_rows():
    client = MagicMock()
    client.get_spreadsheet.return_value = {"sheets": [{"properties": {"title": ALERT_TAB}}]}
    client.get_values.return_value = [["偵測時間"]] * 5

    append_alert_rows(client, "fake_id", [ALERT], "2026-10-28 15:20:00 (TPE)")

    client.batch_update.assert_not_called()
    client.update_values.assert_called_once()
    assert client.update_values.call_args[0][1] == f"'{ALERT_TAB}'!A6:H6"


def test_alert_write_failure_leaves_sheet_untouched():
    client = MagicMock()
    client.get_values.side_effect = _alert_tab_down

    assert _run_with_scan(client, [ALERT]) == 1
    client.update_values.assert_not_called()


def test_alert_is_recorded_before_sheet_overwrite(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    client = MagicMock()
    client.get_values.side_effect = _alert_tab_ready

    assert _run_with_scan(client, [ALERT]) == 0
    ranges = [c[0][1] for c in client.update_values.call_args_list]
    assert ranges[0].startswith(f"'{ALERT_TAB}'!")
    assert ranges[1].startswith("Untitled!A1:X")


def test_report_alerts_writes_summary_and_warning(tmp_path, monkeypatch, capsys):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    report_alerts([ALERT])

    assert "| TPE:2330 | 台積電 | 長多短回檔 | 共振偏多 |" in summary.read_text(encoding="utf-8")
    assert "::warning title=波段關鍵組合::TPE:2330 由 長多短回檔 轉為 共振偏多" in capsys.readouterr().out
