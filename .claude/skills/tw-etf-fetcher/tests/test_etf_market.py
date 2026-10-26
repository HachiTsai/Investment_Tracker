"""tw-etf-fetcher 市場介面與安全防線（etf_market）單元測試：離線、只用標準函式庫。"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import etf_market  # noqa: E402

CORE_ID = "1QBEgUi-kTOuLgj2yGHmP-0g_ug-Sl_M21SN0g93b6xI"
PUBLIC_ID = "1GIhbRyL-h96ACVjlSSW9YUFMiAItg_SP9Wi0o3WwG70"


@pytest.mark.parametrize("raw,code", [
    ("2330.TW", "2330"), ("00878.TWO", "00878"), ("TPE:2330", "2330"), ("nvda.us", "NVDA"), ("CASH", "CASH"),
])
def test_pure_code_strips_prefix_and_suffix(raw, code):
    assert etf_market.pure_code(raw) == code


def test_find_forbidden_suffix_flags_exchange_tokens_only():
    assert etf_market.find_forbidden_suffix("台積電 2330.TW 與 2330.TWO、NVDA.US") == ["2330.TW", "2330.TWO", "NVDA.US"]
    # 小寫網域（.com.tw）、冒號格式與日期不算後綴
    assert etf_market.find_forbidden_suffix("https://www.moneydj.com.tw/x 2330:TPE 1.5 2026/10/21") == []


def test_guard_refuses_core_and_allows_public_sheet():
    with pytest.raises(etf_market.CoreWriteRefused):
        etf_market.guard_sheet_id(CORE_ID)
    assert etf_market.guard_sheet_id(PUBLIC_ID) == PUBLIC_ID


def test_json_for_script_escapes_markup_and_round_trips():
    obj = {"name": "</script><b>A&B</b> ", "n": 1}
    text = etf_market.json_for_script(obj)
    for bad in ("<", ">", "&", " "):
        assert bad not in text
    assert json.loads(text) == obj


def test_coverage_label_marks_source_completeness():
    assert etf_market.coverage_label({"source": "MoneyDJ"}) == "full"
    assert etf_market.coverage_label({"source": "models 持股卡片（備援）"}) == "fallback"
    assert etf_market.coverage_label({"source": "其他來源"}) == "partial"


def test_market_stocks_keeps_only_this_markets_codes():
    market = etf_market.Market(code="X", name="x", profile="tw", currency="TWD",
                               parse_code=lambda s: s.split(".")[0] if s.split(".")[0].isdigit() else None,
                               holdings=None, stock=None, industry=None)
    holdings = {"constituents": [{"symbol": "2330.TW"}, {"symbol": "NVDA.US"}, {"symbol": "CASH"}]}
    assert etf_market.market_stocks(market, holdings) == [{"symbol": "2330.TW"}]


def test_gate_reasons_applies_min_and_max_rules():
    assert etf_market.gate_reasons([("ETF 數量不足", 15, 15, "min"), ("缺檔超標", 10, 10, "max")]) == []
    assert etf_market.gate_reasons([("ETF 數量不足", 14, 15, "min"), ("缺檔超標", 11, 10, "max")]) == [
        "ETF 數量不足：14 < 15", "缺檔超標：11 > 10"]
    with pytest.raises(ValueError):
        etf_market.gate_reasons([("未知規則", 1, 1, "eq")])


def test_default_limits_and_gate_keep_the_tw_contract():
    assert etf_market.Limits() == etf_market.Limits(workers=6, retries=1, retry_wait=3.0, max_seconds=900.0)
    gate = etf_market.Gate()
    assert (gate.min_pool_etfs, gate.max_pool_missing, gate.max_pool_error_etfs) == (15, 10, 0)
    assert (gate.min_summary_rows, gate.min_constituent_rows) == (200, 10000)
    assert issubclass(etf_market.TimeLimitExceeded, RuntimeError)


def test_coverage_label_counts_ctbc_as_full_and_tw_skips_the_holdings_floor():
    assert etf_market.coverage_label({"source": etf_market.CTBC_SOURCE}) == "full"
    assert etf_market.Gate().min_holdings == 0
