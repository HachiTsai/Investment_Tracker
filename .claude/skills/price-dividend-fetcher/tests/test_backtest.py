import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import backtest as bt  # noqa: E402


def bars_from(closes, spread=0.5):
    return [dict(ts=86400 * i, open=c, high=c + spread, low=c - spread, close=c, volume=1, adj=c) for i, c in enumerate(closes)]


def always_long(i, ctx):
    return "long" if i == 1 else None


def never_exit(j, pos, ctx):
    return None


def exit_at(n):
    return lambda j, pos, ctx: "time" if j - pos["entry_i"] >= n else None


def test_long_profit_no_costs():
    b = bars_from([100, 100, 110, 120])
    r = bt.run(b, always_long, exit_at(2), capital=1000)
    assert r["trades"][0]["price_ret_pct"] == pytest.approx(20.0)
    assert r["final_equity"] == pytest.approx(1200)


def test_isolated_liquidation_loses_only_margin():
    # 20 倍、保證金 1%：價格跌 5% 就清算，只虧那 1%
    b = bars_from([100, 100, 94, 90], spread=0)
    r = bt.run(b, always_long, never_exit, leverage=20, margin_pct=1, capital=15000)
    t = r["trades"][0]
    assert t["reason"] == "liquidated" and t["pnl"] == pytest.approx(-150)
    assert r["final_equity"] == pytest.approx(14850)


def test_five_x_survives_same_drop():
    b = bars_from([100, 100, 94, 96], spread=0)
    r = bt.run(b, always_long, exit_at(2), leverage=5, margin_pct=1, capital=15000)
    assert r["trades"][0]["reason"] == "time"
    assert r["trades"][0]["pnl"] == pytest.approx(150 * 5 * -0.04)


def test_short_side_and_liquidation():
    short = lambda i, ctx: "short" if i == 1 else None
    b = bars_from([100, 100, 90, 80], spread=0)
    r = bt.run(b, short, exit_at(2), capital=1000)
    assert r["trades"][0]["price_ret_pct"] == pytest.approx(20.0)
    b2 = bars_from([100, 100, 106], spread=0)
    r2 = bt.run(b2, short, never_exit, leverage=20, margin_pct=10, capital=1000)
    assert r2["trades"][0]["reason"] == "liquidated"


def test_stop_gap_fills_at_open():
    b = bars_from([100, 100, 100], spread=0)
    b[2].update(open=90, low=89, high=91, close=90)
    stop = lambda i, side, ctx: 95
    r = bt.run(b, always_long, never_exit, stop, capital=1000)
    assert r["trades"][0]["reason"] == "stop" and r["trades"][0]["exit"] == 90


def test_costs_and_tax_deducted():
    b = bars_from([100, 100, 100], spread=0)
    r = bt.run(b, always_long, exit_at(1), capital=1000, costs=dict(fee_bps=10, slip_bps=0, sell_tax_bps=30))
    assert r["trades"][0]["pnl"] == pytest.approx(-1000 * (0.001 * 2 + 0.003))


def test_funding_charged_to_longs():
    b = bars_from([100, 100, 100, 100], spread=0)
    fund = {86400 * 2: 0.001, 86400 * 3: 0.001}
    r = bt.run(b, always_long, exit_at(2), capital=1000, funding=fund)
    assert r["trades"][0]["pnl"] == pytest.approx(-2.0)


def test_cooldown_skips_bar_after_loss():
    b = bars_from([100, 100, 90, 100, 100, 100], spread=0)
    every = lambda i, ctx: "long"
    r = bt.run(b, every, exit_at(1), capital=1000, cooldown_after_loss=1)
    assert [t["entry_ts"] // 86400 for t in r["trades"]] == [1, 4]


def test_metrics_drawdown_and_streak():
    b = bars_from([100, 100, 90, 90, 81, 81, 100], spread=0)
    every = lambda i, ctx: "long"
    r = bt.run(b, every, exit_at(1), capital=1000)
    m = bt.metrics(r, 1000, b)
    assert m["longest_losing_streak"] == 2 and m["max_drawdown_pct"] == pytest.approx(19.0)


def test_discipline_warns_on_high_leverage():
    closes = [100 + i * 0.5 for i in range(120)]
    res = bt.backtest("NASDAQ:TEST", "discipline", leverage=20, bars=bars_from(closes), capital=15000)
    assert res["margin_pct"] == 1.0 and any("紀律上限" in w for w in res["warnings"])
    assert res["trades"] >= 1


def test_trend_strategy_enters_uptrend_only_long():
    closes = [100 + i for i in range(80)] + [180 - i * 2 for i in range(40)]
    e, x, _ = bt.strategy("trend", "long")
    ctx = bt.prepare(bars_from(closes))
    assert e(70, ctx) == "long" and e(115, ctx) is None
    e2, _, _ = bt.strategy("trend", "both")
    assert e2(115, ctx) == "short"


def test_market_costs_lookup():
    assert bt.market_key("NASDAQ:TQQQ") == "US" and bt.market_key("0050") == "TPE"
    assert bt.market_key("BINANCE:TQQQUSDT") == "BINANCE"


def test_load_binance_paginates_and_drops_unclosed():
    day = 86400_000

    def k(t, close_t):
        return [t, "1", "2", "0.5", "1.5", "10", close_t]
    calls = []

    def fake(url):
        calls.append(url)
        if len(calls) == 1:
            return [k(i * day, i * day + day - 1) for i in range(1500)]
        return [k(1500 * day, 1500 * day + day - 1), k(1501 * day, 10 ** 15)]
    bars = bt.load_binance("TQQQUSDT", "5y", get=fake, now_ms=1502 * day)
    assert len(calls) == 2 and len(bars) == 1501 and bars[-1]["close"] == 1.5


def test_load_funding_sums_per_day():
    rows = [dict(fundingTime=0, fundingRate="0.0001"), dict(fundingTime=8 * 3600_000, fundingRate="0.0002")]
    assert bt.load_funding("X", 0, get=lambda u: rows)[0] == pytest.approx(0.0003)
