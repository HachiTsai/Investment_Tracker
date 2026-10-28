import py_compile
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "constituents_table.py"
TEMPLATE = ROOT.parent / "tw-etf-fetcher" / "references" / "constituents_template.html"
PAGE = ROOT.parent / "tw-etf-fetcher" / "scripts" / "etf_page.py"

sys.path.insert(0, str(SCRIPT.parent))
import constituents_table
from constituents_table import check_gate


def test_script_compiles():
    py_compile.compile(str(SCRIPT), doraise=True)


def test_every_placeholder_the_script_fills_exists_in_template():
    # 腳本載入時就會連網抓資料，所以只做靜態比對：replace("__X__") 的每個佔位符都要在範本裡
    used = set(re.findall(r'\("(__[A-Z0-9]+__)"', PAGE.read_text(encoding="utf-8")))
    tpl = TEMPLATE.read_text(encoding="utf-8")
    assert {"__DATA__", "__ASOFLINE__", "__CUTOFF__", "__N__", "__TOP__", "__UNIT__", "__FIN__", "__MISS__"} <= used
    assert [p for p in sorted(used) if p not in tpl] == []


def test_template_is_complete_page():
    tpl = TEMPLATE.read_text(encoding="utf-8")
    assert "<title>__ETF__ 成分股股利與財報明細</title>" in tpl
    assert "const D=__DATA__;\n" in tpl


def test_template_has_financials_tab():
    tpl = TEMPLATE.read_text(encoding="utf-8")
    assert "const F=__FIN__;\n" in tpl and 'id="tb-fin"' in tpl and 'id="pg-fin"' in tpl


def test_template_has_dialog_and_financial_main_page():
    tpl = TEMPLATE.read_text(encoding="utf-8")
    assert '<dialog id="dlg"' in tpl and "const fcols=" in tpl and "'qeps'" in tpl


def test_template_has_help_dialog_and_new_metrics():
    tpl = TEMPLATE.read_text(encoding="utf-8")
    assert '<dialog id="hdlg"' in tpl and "const HELP=" in tpl
    assert "'fcf_cover'" in tpl and "'pb_fair'" in tpl
    assert "非官方彙整" not in tpl


def test_template_has_column_picker():
    tpl = TEMPLATE.read_text(encoding="utf-8")
    assert '<dialog id="cdlg"' in tpl and "const GRP=" in tpl and "fincols.v1" in tpl and "setShown" in tpl


def test_template_has_index_weighted_pe():
    tpl = TEMPLATE.read_text(encoding="utf-8")
    assert "pe_all" in tpl and "w/o.reduce((a,r)=>a+r.w/r.pe,0)" in tpl


def test_check_gate():
    ok, reasons = check_gate(49, [], 25, [])
    assert ok and len(reasons) == 0

    ok, reasons = check_gate(40, [], 25, [])
    assert not ok and any("成分股檔數不足" in r for r in reasons)

    ok, reasons = check_gate(49, ["0939", "1398", "1919", "1088", "1288", "3988"], 25, [])
    assert not ok and any("缺股價或歷次分配檔數超標" in r for r in reasons)

    ok, reasons = check_gate(49, [], 10, [])
    assert not ok and any("2026分紅公告檔數不足" in r for r in reasons)

    ok, reasons = check_gate(49, [], 25, ["1", "2", "3", "4", "5", "6"])
    assert not ok and any("財報失敗檔數超標" in r for r in reasons)


def test_check_gate_requires_pool_rows():
    assert check_gate(49, [], 25, [], 554)[0]
    ok, reasons = check_gate(49, [], 25, [], 0)
    assert not ok and any("收益平準金" in r for r in reasons)


def test_load_prev_reads_rows(tmp_path):
    page = tmp_path / "prev.html"
    page.write_text('const D=[{"c":"0939","p25":"12.3","cmp":"+1.0"}];\n', encoding="utf-8")
    rows, err = constituents_table.load_prev(str(page))
    assert err == "" and rows["0939"]["p25"] == "12.3"


def test_load_prev_reports_missing_file(tmp_path):
    rows, err = constituents_table.load_prev(str(tmp_path / "none.html"))
    assert rows == {} and "找不到上一版頁面" in err


def test_load_prev_reports_page_without_rows(tmp_path):
    page = tmp_path / "prev.html"
    page.write_text("<html>改版後的頁面</html>", encoding="utf-8")
    rows, err = constituents_table.load_prev(str(page))
    assert rows == {} and "讀不到資料列" in err


def test_check_gate_blocks_when_carry_fails():
    assert check_gate(49, [], 25, [], 554)[0]
    ok, reasons = check_gate(49, [], 25, [], 554, carry_error="上一版頁面讀不到資料列")
    assert not ok and any("上一版頁面無法沿用" in r for r in reasons)


def test_fetch_pool_returns_rows_and_events(monkeypatch):
    from datetime import date

    rows = [dict(date="2026-07-15", nav=15.25, base=15.0, income=1.02, capital=-0.77),
            dict(date="2026-07-16", nav=14.78, base=15.0, income=0.47, capital=-0.69)]
    nc = constituents_table.nav_composition
    monkeypatch.setattr(nc, "Client", lambda: object())
    monkeypatch.setattr(nc, "resolve_fid", lambda c, etf: "E0014")
    monkeypatch.setattr(nc, "fetch_nav", lambda c, fid, start, end: rows)
    got = constituents_table.fetch_pool("00882", date(2026, 7, 17))
    assert got["rows"][1] == ["2026-07-16", 14.78, 0.47, -0.69] and got["events"][0]["paid"] == 0.55


def test_fetch_pool_failure_returns_empty_and_warns(monkeypatch, capsys):
    from datetime import date

    nc = constituents_table.nav_composition

    def boom(*a, **k):
        raise nc.NavError("防護頁")

    monkeypatch.setattr(nc, "Client", lambda: object())
    monkeypatch.setattr(nc, "resolve_fid", boom)
    assert constituents_table.fetch_pool("00882", date(2026, 7, 17)) == {}
    assert "收益平準金資料不可用：防護頁" in capsys.readouterr().err


def test_fetch_pool_rejects_stale_data(monkeypatch, capsys):
    from datetime import date

    nc = constituents_table.nav_composition
    rows = [dict(date="2026-01-02", nav=15.28, base=15.0, income=0.84, capital=-0.56)]
    monkeypatch.setattr(nc, "Client", lambda: object())
    monkeypatch.setattr(nc, "resolve_fid", lambda c, etf: "E0014")
    monkeypatch.setattr(nc, "fetch_nav", lambda c, fid, start, end: rows)
    assert constituents_table.fetch_pool("00882", date(2026, 10, 28)) == {}
    assert "落後" in capsys.readouterr().err
