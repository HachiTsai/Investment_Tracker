"""etf_page 的收益平準金分頁（pool 參數）離線測試。"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import etf_page  # noqa: E402

ROWS = [["2026-07-15", 15.25, 1.02, -0.77], ["2026-07-16", 14.78, 0.47, -0.69], ["2026-10-27", 14.86, 0.8, -0.94]]
EVENTS = [dict(ex_date="2026-07-16", pre_date="2026-07-15", pre=1.02, post=0.47, paid=0.55, ratio=0.539)]
POOL = dict(rows=ROWS, events=EVENTS)
ARGS = ("hk", "00882", 1, [], [], {}, "d", 0, "t", "u")


def test_without_pool_page_is_unchanged_and_has_no_pool_tab():
    base = etf_page.render(*ARGS)
    assert etf_page.render(*ARGS, pool=None) == base == etf_page.render(*ARGS, pool={})
    assert "tb-pool" not in base and "pg-pool" not in base and "POOL" not in base
    assert etf_page.render(*ARGS, pool=dict(rows=[], events=[])) == base  # 沒有任何列也不顯示空分頁


def test_pool_page_adds_tab_section_and_script_without_leftover_placeholders():
    page = etf_page.render(*ARGS, pool=POOL)
    assert 'id="tb-pool"' in page and 'id="pg-pool"' in page and page.count("<script>") == 2
    assert "__" not in page.replace("__proto__", "")
    assert "資料至 2026-10-27，有紀錄起日 2026-07-15" in page and "00882" in page
    # 原本的兩個分頁與腳本都還在
    assert 'id="tb-fin"' in page and 'id="tb-div"' in page and "const D=" in page


def test_embedded_pool_data_round_trips_through_json():
    page = etf_page.render(*ARGS, pool=POOL)
    m = re.search(r"const P=(\{.*?\}),ETF=", page, flags=re.S)
    assert json.loads(m.group(1)) == POOL


def test_pool_data_is_escaped_for_script_block():
    evil = dict(rows=ROWS, events=[dict(EVENTS[0], ex_date="</script><b>")])
    page = etf_page.render(*ARGS, pool=evil)
    assert "</script><b>" not in page and "\\u003c/script\\u003e" in page


def test_pool_section_is_ordered_after_existing_pages_and_script_after_main_script():
    page = etf_page.render(*ARGS, pool=POOL)
    assert page.index('id="pg-div"') < page.index('id="pg-pool"') < page.index("</main>")
    assert page.rindex("<script>") > page.index("function tab(f)")
