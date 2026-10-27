"""美股、日股持股改讀全市場表（etf_drive）的離線測試：表內解析、建立日期與持股日期分開、表內沒有就退回 Yahoo、表頭改了就拒絕。全部用假列，不連網。"""

import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent.parent
for sub in ("tw-etf-fetcher", "fundamental-analyzer", "price-dividend-fetcher"):
    sys.path.insert(0, str(SKILLS / sub / "scripts"))
import etf_drive  # noqa: E402
import etf_jp  # noqa: E402
import etf_market  # noqa: E402
import etf_us  # noqa: E402

SUMMARY = [
    ["etf_id", "etf_name", "last_model_update"],
    ["00757", "統一FANG+", "2026-10-18"],
    ["00955", "中信日本商社", "2026-10-19"],
    ["00912", "無成分股", ""],
]
CONS = [
    ["etf_id", "etf_name", "constituent_ticker", "constituent_name", "weight_pct", "shares", "update_date"],
    ["00757", "統一FANG+", "PLTR", "Palantir", "10.42", "", "2026-10-18"],
    ["00757", "統一FANG+", "MSFT", "Microsoft", "9.00", "1200", "2026-10-18"],
    ["00955", "中信日本商社", "8001", "伊藤忠", "14.84", "", "2026-10-19"],
]


def test_parse_keeps_only_the_etf_rows_and_puts_the_model_date_in_model_date():
    h = etf_drive.parse(SUMMARY, CONS, "00757")
    assert [c["symbol"] for c in h["constituents"]] == ["PLTR", "MSFT"]
    assert h["model_date"] == "2026-10-18" and h["as_of_date"] is None  # 表內沒有來源持股日期
    assert h["source"] == etf_drive.SOURCE and h["total_count"] == 2 and h["total_weight_pct"] == 19.42
    assert h["constituents"][0]["shares"] is None and h["constituents"][1]["shares"] == 1200


def test_drive_source_is_partial_so_us_and_jp_accept_it():
    assert etf_market.coverage_label(etf_drive.parse(SUMMARY, CONS, "00757")) == "partial"


def test_etf_not_in_the_constituent_table_raises_not_in_pool():
    with pytest.raises(etf_drive.NotInPool):
        etf_drive.parse(SUMMARY, CONS, "0050")
    with pytest.raises(etf_drive.NotInPool):
        etf_drive.parse(SUMMARY, CONS, "00912")  # 摘要有、成分股沒有


def test_empty_model_date_stays_none():
    cons = CONS + [["00912", "無成分股", "2330", "台積電", "5.00", "", ""]]
    assert etf_drive.parse(SUMMARY, cons, "00912")["model_date"] is None


def test_changed_summary_header_is_refused_instead_of_guessed():
    bad = [["etf_id", "last_update"]] + SUMMARY[1:]
    with pytest.raises(RuntimeError, match="last_model_update"):
        etf_drive.parse(bad, CONS, "00757")


def test_us_and_jp_read_the_pool_before_yahoo(monkeypatch):
    monkeypatch.setattr(etf_drive, "_tables", lambda *a, **k: (SUMMARY, CONS))

    def no_yahoo(etf):
        raise AssertionError("全市場表有資料，不該呼叫 Yahoo")
    monkeypatch.setattr(etf_us, "fetch_holdings", no_yahoo)
    monkeypatch.setattr(etf_jp, "fetch_holdings", no_yahoo)
    assert etf_us.holdings("00757")["source"] == etf_drive.SOURCE
    assert etf_jp.holdings("00955")["model_date"] == "2026-10-19"


def test_etf_missing_from_the_pool_falls_back_to_yahoo(monkeypatch):
    monkeypatch.setattr(etf_drive, "_tables", lambda *a, **k: (SUMMARY, CONS))
    monkeypatch.setattr(etf_us, "fetch_holdings", lambda etf: dict(
        ticker=etf, as_of_date=None, source=etf_us.TOP_SOURCE, total_count=0, total_weight_pct=0.0, constituents=[]))
    assert etf_us.holdings("VOO")["source"] == etf_us.TOP_SOURCE
