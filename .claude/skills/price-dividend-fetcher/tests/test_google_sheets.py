"""Google Sheets API 輕量客戶端與波段同步單元測試。"""

import json
from unittest.mock import MagicMock, patch

import pytest

from google_sheets import GoogleSheetsClient, get_credentials
from swing_sync import extract_prev_from_sheet, merge_sheet_rows


def test_get_credentials_missing_env(monkeypatch):
    monkeypatch.delenv("GCP_SA_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    with pytest.raises(RuntimeError, match="未設定 GCP_SA_KEY"):
        get_credentials()


def test_get_credentials_invalid_json(monkeypatch):
    monkeypatch.setenv("GCP_SA_KEY", "invalid-json")
    with pytest.raises(ValueError, match="無法解析為 JSON"):
        get_credentials()


def test_sheets_client_get_values():
    client = GoogleSheetsClient(token="fake-token")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"values": [["代號", "名稱"], ["2330", "台積電"]]}
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_resp) as mock_get:
        res = client.get_values("fake-sheet-id", "Sheet1!A1:B2")
        assert len(res) == 2
        assert res[1][0] == "2330"
        mock_get.assert_called_once()


def test_sheets_client_update_values():
    client = GoogleSheetsClient(token="fake-token")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"updatedRows": 2}
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.put", return_value=mock_resp) as mock_put:
        res = client.update_values("fake-sheet-id", "Sheet1!A1:B2", [["a", "b"]])
        assert res["updatedRows"] == 2
        mock_put.assert_called_once()


def test_sheets_client_clear_values():
    client = GoogleSheetsClient(token="fake-token")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"clearedRange": "Sheet1!A3:B10"}
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.post", return_value=mock_resp) as mock_post:
        res = client.clear_values("fake-sheet-id", "Sheet1!A3:B10")
        assert res["clearedRange"] == "Sheet1!A3:B10"
        mock_post.assert_called_once()


def test_sheets_client_get_spreadsheet():
    client = GoogleSheetsClient(token="fake-token")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "sheets": [
            {"properties": {"sheetId": 0, "title": "ETF_Summary"}},
            {"properties": {"sheetId": 1048345883, "title": "ETF_Constituents"}},
        ]
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_resp) as mock_get:
        meta = client.get_spreadsheet("fake-sheet-id")
        assert len(meta["sheets"]) == 2
        mock_get.assert_called_once()


def test_sheets_client_clear_hyperlinks():
    client = GoogleSheetsClient(token="fake-token")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"replies": [{}]}
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.post", return_value=mock_resp) as mock_post:
        res = client.clear_hyperlinks("fake-sheet-id", sheet_tab_id=1048345883, start_row_index=1, end_row_index=5000)
        assert "replies" in res
        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert url.endswith(":batchUpdate")
        body = mock_post.call_args[1]["json"]
        assert "repeatCell" in body["requests"][0]
        assert body["requests"][0]["repeatCell"]["range"]["sheetId"] == 1048345883
        assert body["requests"][0]["repeatCell"]["fields"] == "userEnteredFormat.textFormat.link"


def test_extract_prev_from_sheet():
    raw_sheet = [
        ["代號", "名稱", "市場", "來源", "狀態", "收盤", "...", "三週期組合"],
        ["HKG:1919", "中遠海控", "HK", "持股", "🟢 突破", "12.5", "...", "長多短回檔"],
        ["2330", "台積電", "TW", "核心", "⚪ 無訊號", "1000", "..."],
    ]
    # 填充到至少 24 欄
    for r in raw_sheet[1:]:
        while len(r) < 24:
            r.append("")
    raw_sheet[1][23] = "長多短回檔"

    prev = extract_prev_from_sheet(raw_sheet)
    assert len(prev) == 2
    assert prev[0]["ticker"] == "HKG:1919"
    assert prev[0]["label"] == "🟢 突破"
    assert prev[0]["combo"] == "長多短回檔"
    assert prev[1]["ticker"] == "2330"
    assert prev[1]["label"] == "⚪ 無訊號"
    assert "combo" not in prev[1]


def test_merge_sheet_rows_fresh_and_holiday():
    existing = [
        ["代號", "名稱", "市場", "來源", "狀態", "收盤"] + [""] * 18,
        ["HKG:1919", "中遠海控", "HK", "持股", "舊狀態", "10.0"] + [""] * 18,
        ["2330", "台積電", "TW", "核心", "舊狀態", "900.0"] + [""] * 18,
    ]
    new_table = [
        ["代號", "名稱", "市場", "來源", "狀態", "收盤"] + [""] * 18,
        ["HKG:1919", "中遠海控", "HK", "持股", "新狀態", "11.0"] + [""] * 18,
        ["2330", "台積電", "TW", "核心", "新狀態", "950.0"] + [""] * 18,
    ]
    # HKG:1919 休市 (fresh=False)，2330 開市 (fresh=True)
    scan_results = [
        {"ticker": "HKG:1919", "fresh": False, "state": "HOLD"},
        {"ticker": "2330", "fresh": True, "state": "BUY"},
    ]

    merged = merge_sheet_rows(existing, new_table, scan_results)
    assert len(merged) == 3
    # HKG:1919 應保持舊狀態
    assert merged[1][0] == "HKG:1919"
    assert merged[1][4] == "舊狀態"
    assert merged[1][5] == "10.0"

    # 2330 應更新為新狀態
    assert merged[2][0] == "2330"
    assert merged[2][4] == "新狀態"
    assert merged[2][5] == "950.0"


def test_merge_sheet_rows_error_handling():
    existing = [
        ["代號", "名稱", "市場", "來源", "狀態", "收盤"] + [""] * 18,
        ["2330", "台積電", "TW", "核心", "舊狀態", "900.0"] + [""] * 18,
    ]
    new_table = [
        ["代號", "名稱", "市場", "來源", "狀態", "收盤"] + [""] * 18,
        ["2330", "台積電", "TW", "核心", "新狀態", "950.0"] + [""] * 18,
    ]
    scan_results = [
        {"ticker": "2330", "fresh": False, "state": "ERROR", "reason": "網路超時"},
    ]

    merged = merge_sheet_rows(existing, new_table, scan_results)
    assert len(merged) == 2
    assert merged[1][0] == "2330"
    assert merged[1][4] == "⚠️ 抓取失敗"
    assert merged[1][15] == "網路超時"
    # 其餘數值保留舊值
    assert merged[1][5] == "900.0"


def test_run_swing_pipeline_market_closed():
    from swing_sync import run_swing_pipeline

    mock_client = MagicMock()
    mock_client.get_values.return_value = [["代號", "名稱"]]

    fake_scan = [{"ticker": "0050", "fresh": False}]
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0, stdout=json.dumps(fake_scan))
        code = run_swing_pipeline(sheet_id="fake_id", client=mock_client)
        assert code == 0
        # 即使休市亦應更新 Z1:AA2 之巡檢時間戳記
        mock_client.update_values.assert_called_once()
        args, _ = mock_client.update_values.call_args
        assert args[1] == "Untitled!Z1:AA2"
        assert args[2][0][0] == "最後巡檢時間"
        assert args[2][1][0] == "狀態"

