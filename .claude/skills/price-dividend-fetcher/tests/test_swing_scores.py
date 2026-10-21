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
