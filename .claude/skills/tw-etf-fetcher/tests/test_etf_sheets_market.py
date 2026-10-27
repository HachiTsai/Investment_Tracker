"""外幣市場寫入 Sheet 的離線測試（etf_sheets_sync）：pool.json 轉成兩張表、Core 與錯誤市場拒絕、國別後綴在寫檔前攔截、分頁補建與範圍寬度。全部用假資料，不連網。"""

import json
import sys
import types
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent.parent
for sub in ("tw-etf-fetcher", "price-dividend-fetcher"):
    sys.path.insert(0, str(SKILLS / sub / "scripts"))
import etf_market  # noqa: E402
import etf_sheets_sync  # noqa: E402

CORE = "1QBEgUi-kTOuLgj2yGHmP-0g_ug-Sl_M21SN0g93b6xI"
HK_SHEET = etf_sheets_sync.MARKET_SHEET_IDS["HK"]


def _payload(market="HK", stock_name="中遠海控", coverage="full"):
    return dict(
        schema_version=etf_market.SCHEMA_VERSION, market=market, asof="2026-10-27",
        stocks=[dict(code="1919", name=stock_name), dict(code="0700", name="騰訊控股")],
        holdings=[dict(etf="00882", code="1919", weightPct=50.0, shares=100),
                  dict(etf="00882", code="0700", weightPct=30.0, shares=None)],
        summaries=[dict(etf="00882", coverage=coverage, holdings_asof="2026-10-21")],
    )


def _write_pool(tmp_path, payload):
    p = tmp_path / "pool.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


_REAL_FETCH_PRICE = etf_sheets_sync.fetch_live_etf_price


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """市場表測試不連網：現價與評分預設拿不到，要測的情境在測試內另外設定。"""
    monkeypatch.setattr(etf_sheets_sync, "fetch_live_etf_price", lambda ticker: None)
    monkeypatch.setattr(etf_sheets_sync, "_load_aggregate_func", lambda: None)


def test_foreign_price_and_scores_use_tw_source_and_method(monkeypatch, tmp_path):
    monkeypatch.setattr(etf_sheets_sync, "fetch_live_etf_price",
                        lambda ticker: 16.83)

    def fake_aggregate(etf_id, top_n=10, repo_root=None):
        return dict(status="success", weighted_roe=12.98,
                    scores=dict(netScore=69.6, divScore=65.4, valScore=69.8, fricScore=75.0))

    monkeypatch.setattr(etf_sheets_sync, "_load_aggregate_func", lambda: fake_aggregate)
    row = etf_sheets_sync.market_tables(_payload(), tmp_path)[0][0]
    assert row["current_price"] == "16.83"
    assert row["weighted_roe"] == "12.98%"
    assert [row[k] for k in ("net_score", "div_score", "val_score", "fric_score")] == ["69.6", "65.4", "69.8", "75.0"]


def test_foreign_price_and_scores_dash_on_fallback_or_error(monkeypatch, tmp_path):
    def fallback(etf_id, top_n=10, repo_root=None):
        return dict(status="fallback", weighted_roe=None,
                    scores=dict(netScore=60.0, divScore=55.0, valScore=70.0, fricScore=80.0))

    monkeypatch.setattr(etf_sheets_sync, "_load_aggregate_func", lambda: fallback)
    row = etf_sheets_sync.market_tables(_payload(), tmp_path)[0][0]
    assert row["weighted_roe"] == "-"
    assert row["net_score"] == "-" and row["fric_score"] == "-"

    def boom(etf_id, top_n=10, repo_root=None):
        raise RuntimeError("no fundamentals")

    monkeypatch.setattr(etf_sheets_sync, "_load_aggregate_func", lambda: boom)
    row = etf_sheets_sync.market_tables(_payload(), tmp_path)[0][0]
    assert row["net_score"] == "-"


def test_live_price_stays_none_when_quote_fails(monkeypatch):
    def offline(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(etf_sheets_sync.urllib.request, "urlopen", offline)
    assert _REAL_FETCH_PRICE("0050") is None
    assert not hasattr(etf_sheets_sync, "ETF_PRICE_SNAPSHOTS")


def test_market_tables_have_the_tw_columns_plus_coverage(tmp_path):
    summary, cons = etf_sheets_sync.market_tables(_payload(), tmp_path)
    assert list(summary[0]) == etf_sheets_sync.FOREIGN_SUMMARY_FIELDS
    assert list(cons[0]) == etf_sheets_sync.CONSTITUENT_FIELDS
    assert summary[0]["coverage"] == "完整" and summary[0]["constituent_count"] == 2
    assert summary[0]["top1_holding"] == "中遠海控 (50.00%)"
    assert summary[0]["top2_holding"] == "騰訊控股 (30.00%)" and summary[0]["top3_holding"] == "-"
    assert cons[0] == dict(etf_id="00882", etf_name="-", constituent_ticker="1919", constituent_name="中遠海控",
                           weight_pct="50.00", shares=100, update_date="2026-10-21")
    assert cons[1]["shares"] == ""


def test_partial_coverage_is_labelled_for_the_sheet(tmp_path):
    summary, _ = etf_sheets_sync.market_tables(_payload(coverage="partial"), tmp_path)
    assert summary[0]["coverage"] == "前幾大"


def test_model_date_and_holdings_date_are_separate_columns(tmp_path):
    payload = _payload()
    payload["summaries"] = [dict(etf="00882", coverage="fallback", holdings_asof="無", model_date="2026-10-18")]
    summary, cons = etf_sheets_sync.market_tables(payload, tmp_path)
    assert summary[0]["last_model_update"] == "2026-10-18" and summary[0]["holdings_asof"] == "無"
    assert all(c["update_date"] == "無" for c in cons)
    payload["summaries"] = [dict(etf="00882", coverage="full", holdings_asof="2026-10-21")]
    summary, _ = etf_sheets_sync.market_tables(payload, tmp_path)
    assert summary[0]["last_model_update"] == "無" and summary[0]["holdings_asof"] == "2026-10-21"


def test_etf_name_comes_from_the_model_card_when_there_is_one(tmp_path):
    card = tmp_path / "00882" / "cards"
    card.mkdir(parents=True)
    (card / "ticker.yml").write_text('title: "測試標題"\ncategory: ETF\n', encoding="utf-8")
    summary, cons = etf_sheets_sync.market_tables(_payload(), tmp_path)
    assert summary[0]["etf_name"] == "測試標題" and cons[0]["etf_name"] == "測試標題"


def test_national_suffix_is_stripped_from_names(tmp_path):
    summary, cons = etf_sheets_sync.market_tables(_payload(stock_name="中遠海控.HK"), tmp_path)
    assert cons[0]["constituent_name"] == "中遠海控" and summary[0]["top1_holding"] == "中遠海控 (50.00%)"


def test_suffix_left_in_a_code_refuses_before_any_file_is_written(tmp_path):
    payload = _payload()
    payload["holdings"][0]["code"] = "1919.HK"
    out = tmp_path / "out"
    res = etf_sheets_sync.run_market_sheets_pipeline(_write_pool(tmp_path, payload), out, HK_SHEET, tmp_path, dry_run=True)
    assert res["status"] == "error" and "國別後綴" in res["message"]
    assert not out.exists()


def test_core_sheet_is_refused(tmp_path):
    res = etf_sheets_sync.run_market_sheets_pipeline(_write_pool(tmp_path, _payload()), tmp_path, CORE, tmp_path, dry_run=True)
    assert res["status"] == "error" and res["synced"] is False


def test_each_market_writes_only_to_its_own_sheet(tmp_path):
    res = etf_sheets_sync.run_market_sheets_pipeline(_write_pool(tmp_path, _payload("HK")), tmp_path,
                                                     etf_sheets_sync.MARKET_SHEET_IDS["US"], tmp_path, dry_run=True)
    assert res["status"] == "error" and "只能寫入" in res["message"]


def test_dry_run_cli_writes_csv_and_never_uploads(tmp_path, capsys):
    out = tmp_path / "out"
    rc = etf_sheets_sync.main(["--market", "HK", "--pool-json", str(_write_pool(tmp_path, _payload())),
                               "--output-dir", str(out), "--models-dir", str(tmp_path), "--dry-run"])
    assert rc == 0
    header = (out / "hk_etf_summary.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.split(",")[:3] == ["etf_id", "etf_name", "current_price"] and header.endswith(",coverage,holdings_asof")
    assert (out / "hk_etf_constituents.csv").exists()
    assert "未上傳雲端" in capsys.readouterr().out


def test_upload_needs_gcp_key_and_never_falls_back_to_the_gsheets_cli(tmp_path, monkeypatch):
    monkeypatch.delenv("GCP_SA_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    res = etf_sheets_sync.run_market_sheets_pipeline(_write_pool(tmp_path, _payload()), tmp_path, HK_SHEET, tmp_path)
    assert res["status"] == "error" and res["synced"] is False and "GCP_SA_KEY" in res["message"]


class FakeSheets:
    """假的 Google Sheets 客戶端：只記錄呼叫，不連網。"""

    def __init__(self, titles):
        self.sheets = [{"properties": {"sheetId": i, "title": t}} for i, t in enumerate(titles)]
        self.requests, self.updates = [], []

    def get_spreadsheet(self, sheet_id):
        return {"sheets": self.sheets}

    def batch_update(self, sheet_id, requests_list):
        for r in requests_list:
            title = r["addSheet"]["properties"]["title"]
            self.sheets.append({"properties": {"sheetId": 100 + len(self.sheets), "title": title}})
        self.requests.extend(requests_list)
        return {}

    def ensure_sheet_capacity(self, sheet_id, tab_id, rows):
        return None

    def format_columns_as_text(self, sheet_id, tab_id, columns):
        return None

    def update_values(self, sheet_id, range_name, values, value_input_option=None):
        self.updates.append((range_name, len(values)))

    def clear_hyperlinks(self, **kwargs):
        return None


@pytest.fixture
def fake_sheets(monkeypatch):
    """讓 sync_via_google_api 內的 `from google_sheets import GoogleSheetsClient` 拿到假客戶端；回傳安裝函式，實例清單由它給出。"""
    instances = []

    def install(titles):
        class Client(FakeSheets):
            def __init__(self):
                super().__init__(titles)
                instances.append(self)

        module = types.ModuleType("google_sheets")
        module.GoogleSheetsClient = Client
        monkeypatch.setitem(sys.modules, "google_sheets", module)
        return instances

    return install


def _csvs(tmp_path, payload):
    summary_rows, cons_rows = etf_sheets_sync.market_tables(payload, tmp_path)
    s, c = tmp_path / "summary.csv", tmp_path / "constituents.csv"
    etf_sheets_sync.write_csv(summary_rows, etf_sheets_sync.FOREIGN_SUMMARY_FIELDS, s)
    etf_sheets_sync.write_csv(cons_rows, etf_sheets_sync.CONSTITUENT_FIELDS, c)
    return s, c


def test_missing_tabs_are_created_and_the_summary_range_follows_its_width(tmp_path, fake_sheets):
    instances = fake_sheets(["Sheet1"])
    s, c = _csvs(tmp_path, _payload())
    ok, msg = etf_sheets_sync.sync_via_google_api(HK_SHEET, s, c, summary_width=len(etf_sheets_sync.FOREIGN_SUMMARY_FIELDS))
    assert ok, msg
    client = instances[0]
    assert [r["addSheet"]["properties"]["title"] for r in client.requests] == ["ETF_Summary", "ETF_Constituents"]
    assert ("ETF_Summary!A1:R2", 2) in client.updates
    assert ("ETF_Constituents!A1:G3", 3) in client.updates
    assert ("ETF_Summary!S1:S2", 2) in client.updates  # 外幣市場的 S 欄是舊版元資訊，先清掉
    assert ("ETF_Summary!T1:U2", 2) in client.updates  # 同步元資訊放在 A:R 以外


def test_tw_keeps_its_original_summary_range_and_creates_nothing(tmp_path, fake_sheets):
    instances = fake_sheets(["ETF_Summary", "ETF_Constituents"])
    s, c = tmp_path / "s.csv", tmp_path / "c.csv"
    s.write_text("a,b\n1,2\n", encoding="utf-8")
    c.write_text("a,b\n1,2\n", encoding="utf-8")
    ok, msg = etf_sheets_sync.sync_via_google_api(etf_sheets_sync.DEFAULT_SHEET_ID, s, c)
    assert ok, msg
    assert instances[0].requests == []
    assert ("ETF_Summary!A1:P2", 2) in instances[0].updates


def test_tw_summary_rows_do_not_fabricate_scores_or_prices(monkeypatch):
    """台股全表：穿透評分失敗或 fallback、報價失敗時一律寫 "-"，不補預設分或舊價。"""
    model = dict(ticker="00878", title="國泰永續高股息", exchange="TWSE", category="ETF", benchmark="x",
                 last_model_update="2026-10-27",
                 constituents=[dict(ticker="2891.TW", name="中信金", weight_pct=10.0, shares=1)])

    def fallback(etf_id, top_n=10, repo_root=None):
        return dict(status="fallback", weighted_roe=9.9,
                    scores=dict(netScore=60.0, divScore=55.0, valScore=70.0, fricScore=80.0))

    monkeypatch.setattr(etf_sheets_sync, "_load_aggregate_func", lambda: fallback)
    row = etf_sheets_sync.generate_summary_rows([model])[0]
    assert row["current_price"] == "-" and row["weighted_roe"] == "-"
    assert [row[k] for k in ("net_score", "div_score", "val_score", "fric_score")] == ["-"] * 4
