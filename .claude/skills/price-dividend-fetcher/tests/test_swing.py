import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import swing as sw  # noqa: E402


def make_bars(closes, spread=1.0, volume=1000):
    return [dict(ts=i, open=c, high=c + spread, low=c - spread, close=c, volume=volume) for i, c in enumerate(closes)]


def test_sma_and_rsi_extremes():
    assert sw.sma([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]
    assert sw.rsi([float(i) for i in range(1, 40)])[-1] == pytest.approx(100.0)
    assert sw.rsi([float(i) for i in range(40, 1, -1)])[-1] == pytest.approx(0.0)


def test_atr_constant_range():
    bars = make_bars([10.0] * 30, spread=1.0)
    assert sw.atr(bars)[-1] == pytest.approx(2.0)


def test_classify_states():
    base = dict(close=100, sma20=100, sma60=100, sma120=100, rsi14=50, macd_hist=0, bb_lower=90, bb_upper=110)
    assert sw.classify(base)["state"] == "NEUTRAL"
    assert sw.classify({**base, "rsi14": 75})["state"] == "OVERHEATED"
    assert sw.classify({**base, "close": 90, "sma20": 95, "sma60": 98, "macd_hist": -1, "rsi14": 40})["state"] == "DOWNTREND"
    assert sw.classify({**base, "rsi14": 25, "close": 95})["state"] == "OVERSOLD_WATCH"
    assert sw.classify({**base, "close": 105, "sma20": 102, "sma60": 100, "macd_hist": 1})["state"] == "UPTREND"
    assert sw.classify({**base, "sma20": None})["state"] == "NO_DATA"


def test_oversold_knife_filter():
    # 跌離半年線超過 10% 時不給「超跌觀察」
    snap = dict(close=80, sma20=95, sma60=100, sma120=100, rsi14=25, macd_hist=0.5, bb_lower=85, bb_upper=110)
    assert sw.classify(snap)["state"] != "OVERSOLD_WATCH"


def test_snapshot_and_backtest_run_on_synthetic_data():
    closes = [100 + (i % 30) * 0.5 - (i // 30) * 0.2 for i in range(300)]
    bars = make_bars(closes)
    snap = sw.snapshot(bars)
    assert snap["stop_price"] < snap["close"] and "state" in snap
    bt = sw.backtest_oversold(bars)
    assert bt["trades"] == len(bt["returns_pct"])


def test_backtest_many_survives_failures(monkeypatch):
    closes = [100 + (i % 30) * 0.5 - (i // 30) * 0.2 for i in range(300)]

    def fake(t, rng="2y"):
        if t == "BAD":
            raise ValueError("no data")
        return make_bars(closes)

    monkeypatch.setattr(sw, "load_ohlcv", fake)
    res = sw.backtest_many(["A", "BAD", "B"])
    assert res["tickers_ok"] == 2 and "BAD" in res["tickers_failed"]
    assert res["trades"] == sum(v["trades"] for v in res["per_ticker"].values())


def test_scan_records_errors(monkeypatch):
    closes = [100 + (i % 30) * 0.5 for i in range(300)]
    monkeypatch.setattr(sw, "load_ohlcv", lambda t, rng="2y": make_bars(closes) if t == "A" else (_ for _ in ()).throw(ValueError("x")))
    rows = sw.scan([{"ticker": "A", "name": "a"}, {"ticker": "B", "name": "b"}])
    assert rows[0]["state"] != "ERROR" and rows[1]["state"] == "ERROR"


def test_watchlist_includes_stock_cards():
    tickers = [i["ticker"] for i in sw.watchlist()]
    assert "HKG:1919" in tickers and "TPE:2356" in tickers


def test_watchlist_includes_etf_cards():
    by = {i["ticker"]: i for i in sw.watchlist()}
    assert by["TPE:00882"]["source"] == "ETF 卡片" and by["TPE:0050"]["source"] == "ETF 卡片"
    assert by["TPE:2356"]["source"] == "個股卡片"


def test_market_of():
    assert sw.market_of("TPE:2356") == "台股" and sw.market_of("HKG:1919") == "港股"
    assert sw.market_of("TYO:7203") == "日股" and sw.market_of("NASDAQ:AAPL") == "美股"


def test_scan_freshness_and_state_change(monkeypatch):
    from datetime import datetime, timezone
    closes = [100 + (i % 30) * 0.5 for i in range(300)]
    bars = make_bars(closes)
    last_ts = bars[-1]["ts"]
    monkeypatch.setattr(sw, "load_ohlcv", lambda t, rng="2y": bars)
    last_day = datetime.fromtimestamp(last_ts, timezone.utc)
    same_day = sw.scan([{"ticker": "TPE:1", "name": "a"}], now=last_day)[0]
    next_day = sw.scan([{"ticker": "TPE:1", "name": "a"}], now=datetime.fromtimestamp(last_ts + 3 * 86400, timezone.utc))[0]
    assert same_day["fresh"] is True and next_day["fresh"] is False
    row = sw.scan([{"ticker": "TPE:1", "name": "a"}], prev={"TPE:1": "⚪ 無訊號"}, now=last_day)[0]
    assert row["prev_label"] == "⚪ 無訊號"
    assert row["changed"] == (row["label"] != "⚪ 無訊號")
    assert row["alert"] == (row["changed"] and row["state"] in sw.ALERT_STATES)


def test_render_page_fills_template():
    html = sw.render_page([{"ticker": "TPE:1", "name": "a", "market": "台股", "state": "NEUTRAL", "label": "⚪ 無訊號"}], "2026-10-21")
    assert "__SWING_" not in html and "TPE:1" in html and '"2026-10-21"' in html


def test_period_returns_total_vs_price():
    closes = [100.0] * 300
    adj = [100.0 + i * 0.1 for i in range(300)]  # 還原價逐步上升，代表配息再投入
    r = sw.period_returns(adj, closes)
    assert r["price"]["1M"] == 0.0 and r["total"]["1M"] > 0
    assert sw.period_returns(adj[:50], closes[:50])["total"]["1Y"] is None


def test_stock_profile_degrades_on_error(monkeypatch):
    monkeypatch.setattr(sw, "load_ohlcv", lambda t, rng="2y": (_ for _ in ()).throw(ValueError("x")))
    with pytest.raises(ValueError):
        sw.stock_profile("TPE:1")
