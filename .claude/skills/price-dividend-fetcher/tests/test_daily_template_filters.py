"""每日巡檢頁範本：篩選功能的掛鉤必須存在（狀態、三週期組合、關鍵組合、組合轉換提醒）。"""
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "references" / "daily_patrol_template.html"


def test_template_has_filter_hooks():
    html = TEMPLATE.read_text(encoding="utf-8")
    for hook in ("data-st", "data-cb", "data-tg", 'id="sum"', 'id="cb"', 'id="tg"', "dpSt", "dpCb", "dpKey", "dpAl"):
        assert hook in html, hook
