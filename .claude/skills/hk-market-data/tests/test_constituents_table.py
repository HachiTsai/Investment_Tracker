import py_compile
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "constituents_table.py"
TEMPLATE = ROOT.parent / "tw-etf-fetcher" / "references" / "constituents_template.html"
PAGE = ROOT.parent / "tw-etf-fetcher" / "scripts" / "etf_page.py"

sys.path.insert(0, str(SCRIPT.parent))
from constituents_table import check_gate


def test_script_compiles():
    py_compile.compile(str(SCRIPT), doraise=True)


def test_every_placeholder_the_script_fills_exists_in_template():
    # 腳本載入時就會連網抓資料，所以只做靜態比對：replace("__X__") 的每個佔位符都要在範本裡
    used = set(re.findall(r'\("(__[A-Z0-9]+__)"', PAGE.read_text(encoding="utf-8")))
    tpl = TEMPLATE.read_text(encoding="utf-8")
    assert {"__DATA__", "__ASOF__", "__N__", "__TOP__", "__UNIT__", "__FIN__", "__MISS__"} <= used
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
