"""台股 ETF 資料管線與成分股穿透分析技能單元測試 (Unit Tests for tw-etf-fetcher)。"""

import json
import sys
from pathlib import Path
import pytest

TEST_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TEST_DIR.parent / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import etf_fetcher as facade  # noqa: E402
from etf_holdings_scraper import (  # noqa: E402
    clean_ticker,
    fetch_etf_holdings,
    format_holdings_ascii,
)
from etf_list_scraper import (  # noqa: E402
    fetch_twse_etf_list,
    filter_etfs,
    format_etf_list_ascii,
)
from etf_lookthrough import calculate_lookthrough, format_lookthrough_ascii  # noqa: E402
from etf_model_scaffolder import scaffold_etf_model  # noqa: E402


MOCK_TWSE_OPENAPI = [
    {
        "出表日期": "1151017",
        "基金代號": "0050",
        "基金簡稱": "元大台灣50",
        "基金類型": "國內成分證券指數股票型基金(股票)",
        "基金中文名稱": "元大台灣卓越50證券投資信託基金",
        "經理公司董事長": "劉宗聖",
        "標的指數/追蹤指數名稱": "臺灣50指數",
    },
    {
        "出表日期": "1151017",
        "基金代號": "00878",
        "基金簡稱": "國泰永續高股息",
        "基金類型": "國內成分證券指數股票型基金(股票)",
        "基金中文名稱": "國泰台灣ESG永續高股息ETF證券投資信託基金",
        "經理公司董事長": "張錫",
        "標的指數/追蹤指數名稱": "MSCI臺灣ESG永續高股息精選30指數",
    },
    {
        "出表日期": "1151017",
        "基金代號": "00919",
        "基金簡稱": "群益台灣精選高息",
        "基金類型": "國內成分證券指數股票型基金(股票)",
        "基金中文名稱": "群益台灣精選高息ETF證券投資信託基金",
        "經理公司董事長": "賴政昇",
        "標的指數/追蹤指數名稱": "臺灣精選高息指數",
    },
]

MOCK_MONEYDJ_HTML = """
<html>
<body>
<table>
  <tr><th>個股名稱</th><th>投資比例(%)</th><th>持有股數 / 口數</th></tr>
  <tr><td>中信金(2891.TW)</td><td>10.16</td><td>926,187,000</td></tr>
  <tr><td>廣達(2382.TW)</td><td>8.63</td><td>179,841,000</td></tr>
  <tr><td>國泰金(2882.TW)</td><td>6.57</td><td>379,840,486</td></tr>
</table>
</body>
</html>
"""


def test_clean_ticker():
    assert clean_ticker("00878.TW") == "00878"
    assert clean_ticker("TPE:0050") == "0050"
    assert clean_ticker("00919.TWO") == "00919"
    assert clean_ticker(" 0056 ") == "0056"


def test_fetch_twse_etf_list_with_mock():
    data = fetch_twse_etf_list(mock_data=MOCK_TWSE_OPENAPI)
    assert len(data) == 3
    assert data[0]["ticker"] == "0050"
    assert data[1]["ticker"] == "00878"
    assert data[1]["benchmark"] == "MSCI臺灣ESG永續高股息精選30指數"


def test_filter_etfs():
    data = fetch_twse_etf_list(mock_data=MOCK_TWSE_OPENAPI)
    filtered = filter_etfs(data, keyword="高息")
    assert len(filtered) == 2
    assert {e["ticker"] for e in filtered} == {"00878", "00919"}

    limited = filter_etfs(data, limit=1)
    assert len(limited) == 1


def test_format_etf_list_ascii():
    data = fetch_twse_etf_list(mock_data=MOCK_TWSE_OPENAPI)
    out = format_etf_list_ascii(data, keyword="高息")
    assert "全市場台股 ETF 清單" in out
    assert "00878" in out
    assert "國泰永續高股息" in out


def test_fetch_etf_holdings_with_mock_html():
    res = fetch_etf_holdings("00878", mock_html=MOCK_MONEYDJ_HTML)
    assert res["ticker"] == "00878"
    assert res["total_count"] == 3
    assert res["total_weight_pct"] == 25.36
    assert res["constituents"][0]["symbol"] == "2891.TW"
    assert res["constituents"][0]["name"] == "中信金"
    assert res["constituents"][0]["weight_pct"] == 10.16
    assert res["constituents"][0]["shares"] == 926187000


def test_format_holdings_ascii():
    res = fetch_etf_holdings("00878", mock_html=MOCK_MONEYDJ_HTML)
    out = format_holdings_ascii(res)
    assert "00878 成分股持股明細" in out
    assert "中信金" in out
    assert "10.16%" in out


def test_calculate_lookthrough():
    # 組合：10張 00878 (市價20) + 5張 00919 (市價20)
    # 00878 市值: 200,000; 00919 市值: 100,000; 總市值: 300,000
    holdings_map = {
        "00878": {
            "constituents": [
                {"symbol": "2891.TW", "name": "中信金", "weight_pct": 10.0},
                {"symbol": "2382.TW", "name": "廣達", "weight_pct": 5.0},
            ]
        },
        "00919": {
            "constituents": [
                {"symbol": "2891.TW", "name": "中信金", "weight_pct": 20.0},
                {"symbol": "2454.TW", "name": "聯發科", "weight_pct": 10.0},
            ]
        },
    }

    res = calculate_lookthrough(
        portfolio_sheets={"00878": 10.0, "00919": 5.0},
        holdings_map=holdings_map,
        price_map={"00878": 20.0, "00919": 20.0},
    )

    assert res["total_portfolio_value"] == 300000.0
    # 中信金貢獻: 200,000 * 10% = 20,000 + 100,000 * 20% = 20,000 -> 總計 40,000
    top_stock = res["stocks"][0]
    assert top_stock["symbol"] == "2891.TW"
    assert top_stock["effective_value"] == 40000.0
    assert top_stock["effective_pct"] == round(40000.0 / 300000.0 * 100.0, 2)

    ascii_out = format_lookthrough_ascii(res)
    assert "投資組合實質穿透持股報告" in ascii_out
    assert "中信金" in ascii_out


def test_scaffold_etf_model(tmp_path):
    holdings = {
        "as_of_date": "2026-10-18",
        "constituents": [
            {"symbol": "2891.TW", "name": "中信金", "weight_pct": 10.16, "shares": 926187000},
            {"symbol": "2382.TW", "name": "廣達", "weight_pct": 8.63, "shares": 179841000},
        ],
    }
    etf_info = {
        "name": "國泰永續高股息",
        "full_name": "國泰台灣ESG永續高股息ETF證券投資信託基金",
        "manager": "張錫",
        "benchmark": "MSCI臺灣ESG永續高股息精選30指數",
    }

    target_cards = scaffold_etf_model(
        ticker="00878",
        repo_root=tmp_path,
        holdings_data=holdings,
        etf_info=etf_info,
        custom_models_dir=tmp_path / "models",
    )

    assert (target_cards / "ticker.yml").exists()
    assert (target_cards / "constituents.jsonl").exists()
    assert (target_cards / "loop_dividend_500k.yml").exists()
    assert (target_cards / "interlock_yield_trap.yml").exists()

    ticker_content = (target_cards / "ticker.yml").read_text(encoding="utf-8")
    assert "card:ticker:00878" in ticker_content
    assert "國泰永續高股息" in ticker_content

    lines = (target_cards / "constituents.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    record1 = json.loads(lines[0])
    assert record1["ticker"] == "2891.TW"
    assert record1["weight_pct"] == 10.16


def test_cli_subcommands(tmp_path, monkeypatch, capsys):
    # 測試 list
    monkeypatch.setattr(facade, "fetch_twse_etf_list", lambda: fetch_twse_etf_list(mock_data=MOCK_TWSE_OPENAPI))
    rc_list = facade.main(["list", "--filter", "高息"])
    assert rc_list == 0
    captured = capsys.readouterr()
    assert "00878" in captured.out

    # 測試 holdings
    monkeypatch.setattr(facade, "fetch_etf_holdings", lambda t: fetch_etf_holdings(t, mock_html=MOCK_MONEYDJ_HTML))
    rc_h = facade.main(["holdings", "00878"])
    assert rc_h == 0
    captured_h = capsys.readouterr()
    assert "00878 成分股持股明細" in captured_h.out

    # 測試 lookthrough
    rc_lt = facade.main(["lookthrough", "--portfolio", "00878:10"])
    assert rc_lt == 0
    captured_lt = capsys.readouterr()
    assert "投資組合實質穿透持股報告" in captured_lt.out

    # 測試 scaffold-model
    rc_scaffold = facade.main(["scaffold-model", "00878", "--models-dir", str(tmp_path / "models")])
    assert rc_scaffold == 0
    assert (tmp_path / "models" / "00878" / "cards" / "ticker.yml").exists()
