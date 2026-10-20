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
