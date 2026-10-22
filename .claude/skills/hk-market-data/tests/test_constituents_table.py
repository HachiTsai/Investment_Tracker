import py_compile
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "constituents_table.py"
TEMPLATE = ROOT / "references" / "constituents_template.html"


def test_script_compiles():
    py_compile.compile(str(SCRIPT), doraise=True)


def test_every_placeholder_the_script_fills_exists_in_template():
    # 腳本載入時就會連網抓資料，所以只做靜態比對：replace("__X__") 的每個佔位符都要在範本裡
    used = set(re.findall(r'\.replace\("(__[A-Z0-9]+__)"', SCRIPT.read_text(encoding="utf-8")))
    tpl = TEMPLATE.read_text(encoding="utf-8")
    assert {"__DATA__", "__ASOF__", "__N__", "__TOP__", "__UNIT__", "__FIN__"} <= used
    assert [p for p in sorted(used) if p not in tpl] == []


def test_template_is_complete_page():
    tpl = TEMPLATE.read_text(encoding="utf-8")
    assert "<title>00882 成分股股利與財報明細</title>" in tpl
    assert "const D=__DATA__;\n" in tpl


def test_template_has_financials_tab():
    tpl = TEMPLATE.read_text(encoding="utf-8")
    assert "const F=__FIN__;\n" in tpl and 'id="tb-fin"' in tpl and 'id="pg-fin"' in tpl


def test_template_has_dialog_and_financial_main_page():
    tpl = TEMPLATE.read_text(encoding="utf-8")
    assert '<dialog id="dlg"' in tpl and "const fcols=" in tpl and "'qeps'" in tpl
