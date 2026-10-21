import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import swing as sw  # noqa: E402
import swing_scores as ss  # noqa: E402


def bars_from(closes, volume=1000):
    return [dict(ts=i, open=c, high=c, low=c, close=c, adj=c, volume=volume) for i, c in enumerate(closes)]


def test_return_score_anchors():
    assert ss.return_score(0) == 40
    assert ss.return_score(15) == 55
    assert ss.return_score(35) == 75
    assert ss.return_score(60) == 90
    assert ss.return_score(-30) == 0


def test_scores_need_60_bars():
    assert ss.compute_scores(bars_from([10.0] * 59)) is None


def test_flat_series_is_neutral():
    s = ss.compute_scores(bars_from([10.0] * 80))
    assert s["trend_score"] == pytest.approx(50, abs=0.1)
    assert s["macd_score"] == pytest.approx(50, abs=0.1)
    assert s["vol_score"] == 50
    assert s["return_score"] == 40


def test_uptrend_scores_above_neutral():
    s = ss.compute_scores(bars_from([10 + i * 0.1 for i in range(120)]))
    assert s["trend_score"] > 50 and s["return_1y_pct"] > 0


def test_merge_patrol_and_kind():
    rows = [{"ticker": "TPE:00882"}, {"ticker": "HKG:1919"}]
    patrol = {"fleet": [{"ticker": "00882", "posture_label": "🔵 穩健複利", "yield_pct": 5.7, "watchdog": {"label": "✅ 正常"}}]}
    sw.merge_patrol(rows, patrol)
    assert rows[0]["posture_label"] == "🔵 穩健複利" and rows[0]["yield_pct"] == 5.7
    assert "posture_label" not in rows[1]
    assert sw.kind_of("ETF 卡片") == "ETF" and sw.kind_of("個股卡片") == "個股" and sw.kind_of("00882 成分股") == "個股"


def test_render_daily_page_embeds_data():
    html = sw.render_daily_page([{"ticker": "TPE:1", "name": "測試", "market": "台股", "source": "ETF 卡片"}], {"macro_feed": "x", "fleet": []}, "2026-10-20")
    assert "__DAILY_DATA__" not in html and "2026-10-20" in html and '"kind": "ETF"' in html


def test_chart_series_lengths_and_page_embeds_chart():
    bars = [dict(ts=1_700_000_000 + i * 86400, open=10 + i * .1, high=11 + i * .1, low=9 + i * .1, close=10 + i * .1, adj=10 + i * .1, volume=1000) for i in range(150)]
    ch = sw.chart_series(bars)
    assert all(len(ch[k]) == sw.CHART_BARS for k in ("d", "o", "h", "l", "c", "ma20", "bu", "bl", "rsi", "hist"))
    html = sw.render_daily_page([{"ticker": "TPE:1", "name": "測試", "market": "台股", "source": "ETF 卡片", "chart": ch}], {"fleet": []}, "2026-10-20")
    assert '"chart"' in html and "openDlg" in html


def test_daily_template_has_matrix_quadrant_3d_views():
    import swing
    tpl = (swing.REF_DIR / "daily_patrol_template.html").read_text(encoding="utf-8") if hasattr(swing, "REF_DIR") else None
    if tpl is None:
        from pathlib import Path
        tpl = (Path(swing.__file__).resolve().parent.parent / "references" / "daily_patrol_template.html").read_text(encoding="utf-8")
    for key in ("vMatrix", "vQuad", "v3d", "three.min.js", "data-vw", "drawQuad", "draw3d"):
        assert key in tpl


def test_score_history_length_and_last_matches_compute_scores():
    from swing_scores import compute_scores, score_history
    bars = [{"close": 100 + i * 0.3, "adj": 100 + i * 0.3, "volume": 1000 + i} for i in range(200)]
    h = score_history(bars, 60)
    assert len(h["t"]) == len(h["m"]) == len(h["v"]) == 60
    last = compute_scores(bars)
    assert h["t"][-1] == last["trend_score"] and h["m"][-1] == last["macd_score"]


def test_daily_template_has_popup_matrix_and_trajectory():
    from pathlib import Path
    import swing
    tpl = (Path(swing.__file__).resolve().parent.parent / "references" / "daily_patrol_template.html").read_text(encoding="utf-8")
    for key in ("dMatrix", "trajInit", "data-dt", "cvJ"):
        assert key in tpl


def test_render_daily_page_excludes_constituents():
    rows = [{"ticker": "TPE:1", "name": "留下", "market": "台股", "source": "ETF 卡片"},
            {"ticker": "HKG:1288", "name": "港股成分", "market": "港股", "source": "00882 成分股"}]
    html = sw.render_daily_page(rows, {"fleet": []}, "2026-10-20")
    assert "留下" in html and "港股成分" not in html


def test_daily_template_uses_latest_quote_wording_and_refresh():
    from pathlib import Path
    import swing
    tpl = (Path(swing.__file__).resolve().parent.parent / "references" / "daily_patrol_template.html").read_text(encoding="utf-8")
    for key in ("最新報價", "qRefresh", "firecrawl_scrape", "mis.twse.com.tw", "function px(r)", "function sd(r)"):
        assert key in tpl
    assert "<th data-k=\"close\">收盤</th>" not in tpl and "<span>收盤</span>" not in tpl


def test_daily_template_has_favorites():
    from pathlib import Path
    import swing
    tpl = (Path(swing.__file__).resolve().parent.parent / "references" / "daily_patrol_template.html").read_text(encoding="utf-8")
    for key in ("我的最愛", "data-fav", "favOnly", "function saveFav", 'use("db")', "data/users/"):
        assert key in tpl


def test_daily_template_caps_table_height():
    from pathlib import Path
    import swing
    tpl = (Path(swing.__file__).resolve().parent.parent / "references" / "daily_patrol_template.html").read_text(encoding="utf-8")
    for key in ("CAPN=20", "function capH", "overflowY"):
        assert key in tpl


def test_daily_template_small_dots_with_hover_labels():
    from pathlib import Path
    import swing
    tpl = (Path(swing.__file__).resolve().parent.parent / "references" / "daily_patrol_template.html").read_text(encoding="utf-8")
    for key in ("function qFit", "data-qz", ".qd .pt:hover .lb", "fit3", "貼合資料"):
        assert key in tpl


def test_render_daily_page_excludes_listed_tickers():
    rows = [{"ticker": "TPE:1", "name": "留下", "market": "台股", "source": "ETF 卡片"},
            {"ticker": "HKG:1919", "name": "中遠海控", "market": "港股", "source": "個股卡片"}]
    html = sw.render_daily_page(rows, {"fleet": []}, "2026-10-20")
    assert "留下" in html and "中遠海控" not in html
