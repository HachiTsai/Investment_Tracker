import json
import sys
from datetime import datetime, timedelta, timezone
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
    tickers = [i["ticker"] for i in sw.watchlist(filter_tier="all")]
    assert "HKG:1919" in tickers and "TPE:2356" in tickers


def test_watchlist_includes_etf_cards():
    by = {i["ticker"]: i for i in sw.watchlist(filter_tier="all")}
    assert by["TPE:00882"]["source"] == "ETF 卡片" and by["TPE:0050"]["source"] == "ETF 卡片"
    assert by["TPE:2356"]["source"] == "個股卡片"


def test_watchlist_tier_filtering(tmp_path, monkeypatch):
    c1 = tmp_path / "0050" / "cards" / "ticker.yml"
    c1.parent.mkdir(parents=True)
    c1.write_text("ticker: '0050'\ntitle: '台灣50'\ntier: core\n", encoding="utf-8")

    c2 = tmp_path / "00922" / "cards" / "ticker.yml"
    c2.parent.mkdir(parents=True)
    c2.write_text("ticker: '00922'\ntitle: '領袖50'\ntier: pool\n", encoding="utf-8")

    monkeypatch.setattr("pathlib.Path.glob", lambda self, pattern: [c1, c2])

    core_items = [i["ticker"] for i in sw.watchlist()]
    assert "TPE:0050" in core_items
    assert "TPE:00922" not in core_items

    pool_items = [i["ticker"] for i in sw.watchlist(filter_tier="pool")]
    assert "TPE:00922" in pool_items
    assert "TPE:0050" not in pool_items

    all_items = [i["ticker"] for i in sw.watchlist(filter_tier="all")]
    assert "TPE:0050" in all_items and "TPE:00922" in all_items


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
    cur = sw.scan([{"ticker": "TPE:1", "name": "a"}], now=last_day)[0]
    assert cur["combo"] and cur["long"] and cur["mid"] in ("偏多", "中性", "偏空") and cur["short"] and cur["fib3"]
    row = sw.scan([{"ticker": "TPE:1", "name": "a"}], prev={"TPE:1": {"label": "⚪ 未觸發條件", "combo": "其他"}}, now=last_day)[0]
    assert row["prev_label"] == "⚪ 無明確型態"  # 舊名「未觸發條件」對應到新名，不算狀態變化
    assert row["changed"] == (row["label"] != "⚪ 無明確型態")
    assert row["combo_changed"] == (row["combo"] != "其他")
    from swing_levels import KEY_COMBOS
    assert row["alert"] == (row["combo_changed"] and row["combo"] in KEY_COMBOS)
    # 舊狀態檔沒有 combo：不提醒；舊「過熱」標籤對應到新用語，不算變化
    old = sw.scan([{"ticker": "TPE:1", "name": "a"}], prev={"TPE:1": {"label": "🟠 過熱"}}, now=last_day)[0]
    assert old["combo_changed"] is False and old["alert"] is False
    assert old["prev_label"] == "🟠 短線偏熱"
    assert sw.scan([{"ticker": "TPE:1", "name": "a"}], prev={"TPE:1": {"label": "⚪ 無訊號"}}, now=last_day)[0]["prev_label"] == "⚪ 無明確型態"


def test_sheet_table_columns_fixed_order():
    t = sw.sheet_table([{"ticker": "TPE:1", "name": "a", "long": "偏多", "combo": "其他"}])
    assert t[0][0] == "代號" and t[0][-1] == "三週期組合" and len(t[0]) == len(t[1]) == 24
    assert t[1][0] == "TPE:1" and t[1][19] == "偏多" and t[1][5] == ""


def test_render_page_fills_template():
    html = sw.render_page([{"ticker": "TPE:1", "name": "a", "market": "台股", "state": "NEUTRAL", "label": "⚪ 無明確型態"}], "2026-10-21")
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


def _bars(rows):
    return [dict(ts=i * 86400, open=c, high=h, low=l, close=c, volume=1000, adj=c) for i, (h, l, c) in enumerate(rows)]


def test_fib_zone_uptrend_retracement():
    # 低點在前、高點在後：100 → 200，收在 150 為回檔 50%
    rows = [(101 + i, 100 + i, 100 + i) for i in range(30)]
    rows[-1] = (200, 100, 150)
    z = sw.fib_zone(_bars(rows[:-1] + [(200, 195, 150)]))
    assert z["dir"] == "up" and z["bucket"] == "38.2-61.8"


def test_fib_zone_downtrend_rebound():
    rows = [(200 - i, 199 - i, 200 - i) for i in range(30)]
    z = sw.fib_zone(_bars(rows))
    assert z["dir"] == "down" and z["bucket"] == "0-23.6"


def test_fib_zone_needs_data_and_range():
    assert sw.fib_zone(_bars([(10, 9, 9.5)] * 3)) is None
    assert sw.fib_zone(_bars([(10, 10, 10)] * 30)) is None


def test_backtest_fib_groups_by_zone():
    rows = [(100 + i + 1, 100 + i, 100 + i) for i in range(80)]
    res = sw.backtest_fib({"A": _bars(rows)}, horizons=(5,))
    assert res["baseline"][5]["n"] > 0 and any("上升波" in k for k in res["zones"])


def test_swing_levels_horizons_and_combo():
    import swing_levels as sl
    rows = [(100 + i * 0.5 + 1, 100 + i * 0.5 - 1, 100 + i * 0.5) for i in range(300)]
    bars = _bars(rows)
    ser = sl.build_series(bars)
    assert sl.horizon_states(bars, ser, 50) is None  # 資料不足
    st = sl.horizon_states(bars, ser, 299)
    assert st["長"]["state"] in sl.STATES.values() and sl.combo(st) == "三週期共振偏多"
    assert sl.fib_level(bars, 299, 20)["level"] == "F1"


def test_swing_levels_combo_names():
    import swing_levels as sl
    mk = lambda s, m, l_: {"短": {"score": s}, "中": {"score": m}, "長": {"score": l_}}
    assert sl.combo(mk(-1, -1, -2)) == "三週期共振偏空"
    assert sl.combo(mk(0, 1, 2)) == "長多短回檔"
    assert sl.combo(mk(1, 0, -1)) == "長空短反彈"


def test_backtest_levels_runs():
    import swing_levels as sl
    rows = [(100 + i * 0.5 + 1, 100 + i * 0.5 - 1, 100 + i * 0.5 + (i % 7) * 0.3) for i in range(420)]
    res = sl.backtest_levels({"A": _bars(rows)})
    assert res["baseline"][5]["n"] > 0 and res["combo"]


def test_current_levels_and_fib3():
    import swing_levels as sl
    bars = make_bars([100 + i * 0.3 for i in range(300)])
    lv = sl.current_levels(bars)
    assert lv["long"] in ("強勢", "偏多", "中性", "偏弱", "弱勢") and lv["mid"] in ("偏多", "中性", "偏空")
    assert lv["fib3"] in ("近前高", "回檔中段", "深度回檔", "近波段低點", "反彈中段", "反彈近前高")
    assert sl.current_levels(make_bars([100.0] * 30)) is None
    assert sl.mid_label(2) == "偏多" and sl.mid_label(0) == "中性" and sl.mid_label(-1) == "偏空"


def test_fill_gaps_from_twse_adds_missing_day_only_before_today():
    tz8 = timedelta(hours=8)
    now = datetime(2026, 10, 22, 1, 40, tzinfo=timezone.utc)

    def bar(day, close):
        ts = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) + 3600
        return dict(ts=ts, open=close, high=close, low=close, close=close, volume=1.0, adj=close)

    bars = [bar("2026-10-19", 108.15), bar("2026-10-20", 107.25), bar("2026-10-22", 108.65)]
    js = {"data": [
        ["115/10/20", "1", "1", "107", "108", "106", "107.25", "0", "1"],
        ["115/10/21", "1,000", "1", "107.5", "108.5", "107", "108.15", "0", "1"],
        ["115/10/22", "1", "1", "1", "1", "1", "1", "0", "1"],
    ]}
    out = sw.fill_gaps_from_twse(bars, "0050", now=now, fetch=lambda url: json.dumps(js))
    days = [(datetime.fromtimestamp(b["ts"], timezone.utc) + tz8).strftime("%Y-%m-%d") for b in out]
    assert days == ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22"]
    assert out[2]["close"] == 108.15 and out[2]["volume"] == 1000.0
    assert out[3]["close"] == 108.65


def _yahoo_bar(day, close):
    ts = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) + 3600
    return dict(ts=ts, open=close, high=close, low=close, close=close, volume=1.0, adj=close)


def test_drop_unsettled_bar_removes_todays_intraday_bar_before_close():
    # 2026-11-05 台北 09:40（盤中）：今天的盤中棒要丟掉，前一交易日保留
    now = datetime(2026, 11, 5, 1, 40, tzinfo=timezone.utc)
    bars = [_yahoo_bar("2026-11-03", 16.1), _yahoo_bar("2026-11-04", 15.3), _yahoo_bar("2026-11-05", 15.4)]
    out = sw.drop_unsettled_bar(bars, "台股", now=now)
    assert [b["close"] for b in out] == [16.1, 15.3]


def test_drop_unsettled_bar_keeps_todays_bar_after_close():
    # 台北 14:30（收盤後）：今天的收盤棒保留，fresh 才能判定
    now = datetime(2026, 11, 5, 6, 30, tzinfo=timezone.utc)
    bars = [_yahoo_bar("2026-11-04", 15.3), _yahoo_bar("2026-11-05", 15.4)]
    assert sw.drop_unsettled_bar(bars, "台股", now=now) == bars


def test_drop_unsettled_bar_uses_market_local_date():
    # 美股：UTC 2026-11-05 15:00 是 ET 上午 11 點（盤中）；美股日線時戳落在 UTC 14:00，ET 日期為 11/05，要丟掉
    now = datetime(2026, 11, 5, 15, 0, tzinfo=timezone.utc)
    ts = lambda day: int(datetime.strptime(day + " 14:00", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())  # noqa: E731
    bars = [dict(ts=ts("2026-11-04"), close=100.0), dict(ts=ts("2026-11-05"), close=101.0)]
    out = sw.drop_unsettled_bar(bars, "美股", now=now)
    assert [b["close"] for b in out] == [100.0]


def test_load_ohlcv_does_not_return_intraday_bar(monkeypatch):
    now = datetime(2026, 11, 5, 1, 40, tzinfo=timezone.utc)
    ts = lambda day: int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) + 3600  # noqa: E731
    result = {"timestamp": [ts("2026-11-03"), ts("2026-11-04"), ts("2026-11-05")],
              "indicators": {"quote": [{"open": [16, 15, 15.4], "high": [16, 15, 15.4], "low": [16, 15, 15.4],
                                        "close": [16.1, 15.3, 15.4], "volume": [1, 1, 1]}]}}
    monkeypatch.setattr(sw, "get_yahoo", lambda exch, code, rng: None)
    monkeypatch.setattr(sw, "yahoo_result", lambda raw, exch, code: result)
    monkeypatch.setattr(sw, "fill_gaps_from_twse", lambda bars, code, now=None, fetch=None: bars)
    bars = sw.load_ohlcv("TPE:00882", "1y", now=now)
    assert [b["close"] for b in bars] == [16.1, 15.3]


def test_fill_gaps_from_twse_ignores_fetch_failure():
    def boom(url):
        raise RuntimeError("blocked")
    bars = [dict(ts=1, open=1, high=1, low=1, close=1, volume=1, adj=1)]
    assert sw.fill_gaps_from_twse(bars, "0050", fetch=boom) == bars


def test_lagging_tickers_per_market():
    rows = [
        {"ticker": "A", "market": "台股", "last_date": "2026-10-21"},
        {"ticker": "B", "market": "台股", "last_date": "2026-10-20"},
        {"ticker": "C", "market": "港股", "last_date": "2026-10-20"},
        {"ticker": "D", "market": "台股", "last_date": None},
    ]
    assert sw.lagging_tickers(rows) == ["B"]


def test_fill_gaps_logs_fetch_failure(capsys):
    def blocked(url):
        raise RuntimeError("HTTP 307（https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY）")
    bars = [dict(ts=1, open=1, high=1, low=1, close=1, volume=1, adj=1)]
    assert sw.fill_gaps_from_twse(bars, "00882", fetch=blocked) == bars
    err = capsys.readouterr().err
    assert "證交所補缺失敗（00882" in err and "HTTP 307" in err


def test_refresh_lagging_adopts_newer_row_and_rescans_only_laggards(monkeypatch):
    rows = [
        {"ticker": "TPE:A", "market": "台股", "last_date": "2026-10-28", "label": "ok"},
        {"ticker": "TPE:B", "market": "台股", "last_date": "2026-10-27", "label": "old"},
    ]
    items = [{"ticker": "TPE:A"}, {"ticker": "TPE:B"}]
    calls = []

    def fake_scan(sub, prev, with_chart=False, now=None):
        calls.append([it["ticker"] for it in sub])
        return [{"ticker": "TPE:B", "market": "台股", "last_date": "2026-10-28", "label": "new"}]

    monkeypatch.setattr(sw, "scan", fake_scan)
    slept = []
    out = sw.refresh_lagging(rows, items, None, delays=(30,), sleep=slept.append)
    assert calls == [["TPE:B"]] and slept == [30]
    assert [r["label"] for r in out] == ["ok", "new"]
    assert sw.lagging_tickers(out) == []


def test_refresh_lagging_keeps_row_when_retry_still_behind(monkeypatch):
    rows = [
        {"ticker": "TPE:A", "market": "台股", "last_date": "2026-10-28", "label": "ok"},
        {"ticker": "TPE:B", "market": "台股", "last_date": "2026-10-27", "label": "old"},
    ]
    items = [{"ticker": "TPE:A"}, {"ticker": "TPE:B"}]
    monkeypatch.setattr(sw, "scan", lambda sub, prev, with_chart=False, now=None: [
        {"ticker": "TPE:B", "market": "台股", "last_date": "2026-10-27", "label": "still-old"},
    ])
    slept = []
    out = sw.refresh_lagging(rows, items, None, delays=(30, 60), sleep=slept.append)
    assert slept == [30, 60]
    assert out == rows
    assert sw.lagging_tickers(out) == ["TPE:B"]


def test_refresh_lagging_does_nothing_when_no_laggards(monkeypatch):
    rows = [
        {"ticker": "TPE:A", "market": "台股", "last_date": "2026-10-28"},
        {"ticker": "TPE:B", "market": "台股", "last_date": "2026-10-28"},
    ]
    monkeypatch.setattr(sw, "scan", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not rescan")))
    slept = []
    assert sw.refresh_lagging(rows, [{"ticker": "TPE:A"}, {"ticker": "TPE:B"}], None, sleep=slept.append) == rows
    assert slept == []


GAP_DAYS = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"]


def _gap_row(ticker, dates, label="x"):
    return {"ticker": ticker, "market": "台股", "last_date": dates[-1], "bar_dates": dates, "label": label}


def test_missing_days_flags_middle_gap_when_majority_has_day():
    rows = [
        _gap_row("TPE:A", GAP_DAYS),
        _gap_row("TPE:B", [d for d in GAP_DAYS if d != "2026-10-21"]),
        _gap_row("TPE:C", GAP_DAYS),
        _gap_row("TPE:D", GAP_DAYS),
    ]
    assert sw.missing_days(rows) == {"TPE:B": ["2026-10-21"]}


def test_missing_days_ignores_market_wide_holiday():
    no_21 = [d for d in GAP_DAYS if d != "2026-10-21"]
    rows = [_gap_row("TPE:A", no_21), _gap_row("TPE:B", no_21)]
    assert sw.missing_days(rows) == {}


def test_missing_days_ignores_trailing_lag_and_new_listing():
    rows = [
        _gap_row("TPE:A", GAP_DAYS),
        _gap_row("TPE:B", GAP_DAYS[:-1]),  # 尾端落後，交給 lagging_tickers
        _gap_row("TPE:C", GAP_DAYS[2:]),  # 新掛牌，前段沒有資料不算缺口
        _gap_row("TPE:D", GAP_DAYS),
    ]
    assert sw.missing_days(rows) == {}
    assert sw.lagging_tickers(rows) == ["TPE:B"]


def test_refresh_lagging_adopts_row_that_fills_middle_gap(monkeypatch):
    rows = [
        _gap_row("TPE:A", GAP_DAYS),
        _gap_row("TPE:B", [d for d in GAP_DAYS if d != "2026-10-21"]),
        _gap_row("TPE:C", GAP_DAYS),
        _gap_row("TPE:D", GAP_DAYS),
    ]
    items = [{"ticker": r["ticker"]} for r in rows]
    calls = []

    def fake_scan(sub, prev, with_chart=False, now=None):
        calls.append([it["ticker"] for it in sub])
        return [_gap_row("TPE:B", GAP_DAYS, label="filled")]

    monkeypatch.setattr(sw, "scan", fake_scan)
    slept = []
    out = sw.refresh_lagging(rows, items, None, delays=(30,), sleep=slept.append)
    assert calls == [["TPE:B"]] and slept == [30]
    assert out[1]["label"] == "filled"
    assert sw.missing_days(out) == {}


def test_refresh_lagging_keeps_gap_row_when_retry_still_missing(monkeypatch):
    gap = [d for d in GAP_DAYS if d != "2026-10-21"]
    rows = [
        _gap_row("TPE:A", GAP_DAYS),
        _gap_row("TPE:B", gap, label="old"),
        _gap_row("TPE:C", GAP_DAYS),
        _gap_row("TPE:D", GAP_DAYS),
    ]
    items = [{"ticker": r["ticker"]} for r in rows]
    monkeypatch.setattr(sw, "scan", lambda sub, prev, with_chart=False, now=None: [_gap_row("TPE:B", gap, label="still")])
    slept = []
    out = sw.refresh_lagging(rows, items, None, delays=(30, 60), sleep=slept.append)
    assert slept == [30, 60]
    assert [r["label"] for r in out] == ["x", "old", "x", "x"]


def test_check_gate():
    rows_ok = [{"ticker": "2330", "state": "UPTREND", "fresh": True}] * 10
    is_healthy, is_closed, reasons = sw.check_gate(rows_ok, max_errors=5, require_fresh=True)
    assert is_healthy and not is_closed and len(reasons) == 0

    rows_err = [{"ticker": f"ERR_{i}", "state": "ERROR", "fresh": False} for i in range(6)]
    is_healthy, is_closed, reasons = sw.check_gate(rows_err, max_errors=5, require_fresh=False)
    assert not is_healthy and any("ERROR／NO_DATA 狀態標的超標" in r for r in reasons)

    rows_closed = [{"ticker": "2330", "state": "NEUTRAL", "fresh": False, "market": "台股", "last_date": "2026-11-12"}] * 5
    is_healthy, is_closed, reasons = sw.check_gate(rows_closed, max_errors=5, require_fresh=True, now=DAILY_NOW)
    assert is_healthy and is_closed and any("今日所有市場休市" in r for r in reasons)

    is_healthy, is_closed, reasons = sw.check_gate(rows_closed, max_errors=5, require_fresh=False, now=DAILY_NOW)
    assert is_healthy and not is_closed and len(reasons) == 0


def test_check_gate_empty_rows_fail_closed():
    """掃描結果為空不得當作健康或休市（原本會通過，靜默保留舊 Sheet 資料）。"""
    ok, closed, reasons = sw.check_gate([], max_errors=10, require_fresh=True, now=DAILY_NOW)
    assert not ok and not closed and any("為空" in r for r in reasons)


def test_check_gate_counts_no_data_toward_budget():
    """NO_DATA 會保留舊值，必須計入錯誤預算，否則是靜默失效。"""
    rows = [{"ticker": f"N{i}", "state": "NO_DATA", "fresh": False, "market": "台股", "last_date": "2026-11-12"} for i in range(11)]
    ok, _, reasons = sw.check_gate(rows, max_errors=10, require_fresh=False, now=DAILY_NOW)
    assert not ok and any("超標" in r for r in reasons)
    ok, _, _ = sw.check_gate(rows[:10], max_errors=10, require_fresh=False, now=DAILY_NOW)
    assert ok


def test_check_gate_stale_data_is_not_treated_as_closed():
    """來源停滯回舊資料時，所有列都不是 fresh；不得因此判為休市而略過。"""
    rows = [{"ticker": "2330", "state": "NEUTRAL", "fresh": False, "market": "台股", "last_date": "2026-11-01"}] * 5
    ok, closed, reasons = sw.check_gate(rows, max_errors=10, require_fresh=True, now=DAILY_NOW)
    assert not ok and not closed and any("資料日過舊" in r for r in reasons)


def test_check_gate_holiday_closed_still_passes():
    """短假期間最新資料日仍在容許範圍內，照常判為休市。"""
    rows = [{"ticker": "2330", "state": "NEUTRAL", "fresh": False, "market": "台股", "last_date": "2026-11-11"}] * 5
    ok, closed, reasons = sw.check_gate(rows, max_errors=10, require_fresh=True, now=DAILY_NOW)
    assert ok and closed


DAILY_NOW = datetime(2026, 11, 13, 0, 56, tzinfo=timezone.utc)  # 台北 08:56，週五盤前


def _daily_row(ticker, market="台股", state="UPTREND", last_date="2026-11-12"):
    return {"ticker": ticker, "market": market, "state": state, "last_date": last_date, "fresh": False, "missing_days": []}


def _daily_rows():
    """同 2026-11-13 實跑的結構：2 檔核心持股（台股）加 15 列成分股（港股）。"""
    return [_daily_row("TPE:00882"), _daily_row("TPE:00406A")] + [_daily_row(f"HKG:{i:04d}", market="港股") for i in range(1, 16)]


def test_gate_default_for_sheet_path_unchanged():
    assert sw.GATE_MAX_ERRORS == 10


def test_daily_gate_passes_on_healthy_rows():
    ok, reasons = sw.check_daily_gate(_daily_rows(), now=DAILY_NOW)
    assert ok and reasons == []


def test_daily_gate_fails_closed_on_empty_rows():
    ok, reasons = sw.check_daily_gate([], now=DAILY_NOW)
    assert not ok and any("為空" in r for r in reasons)


def test_daily_gate_holding_zero_tolerance_on_error():
    rows = _daily_rows()
    rows[1]["state"] = "ERROR"  # 00406A
    ok, reasons = sw.check_daily_gate(rows, now=DAILY_NOW)
    assert not ok and any("持股資料異常" in r and "TPE:00406A" in r for r in reasons)


def test_daily_gate_holding_stale_by_one_day_fails():
    rows = _daily_rows()
    rows[0]["last_date"] = "2026-11-11"  # 00882 落後同市場最新資料日一天
    ok, reasons = sw.check_daily_gate(rows, now=DAILY_NOW)
    assert not ok and any("TPE:00882" in r for r in reasons)


def test_daily_gate_general_budget_allows_two_rejects_three():
    rows = _daily_rows()
    rows[2]["state"] = "NO_DATA"
    rows[3]["state"] = "NO_DATA"  # 兩檔一般列異常：仍通過
    ok, _ = sw.check_daily_gate(rows, now=DAILY_NOW)
    assert ok
    rows[4]["state"] = "ERROR"  # 第三檔：超過上限
    ok, reasons = sw.check_daily_gate(rows, now=DAILY_NOW)
    assert not ok and any("一般列異常 3 檔" in r for r in reasons)


def test_daily_gate_missing_holding_row_fails():
    rows = [r for r in _daily_rows() if r["ticker"] != "TPE:00406A"]
    ok, reasons = sw.check_daily_gate(rows, now=DAILY_NOW)
    assert not ok and any("持股缺列" in r and "TPE:00406A" in r for r in reasons)


def test_daily_gate_rejects_whole_market_stale_by_age():
    rows = _daily_rows()
    for r in rows:
        if r["market"] == "台股":
            r["last_date"] = "2026-11-01"  # 整個市場停在 12 天前
    ok, reasons = sw.check_daily_gate(rows, now=DAILY_NOW)
    assert not ok and any("台股" in r and "距今" in r for r in reasons)


def test_validate_daily_html_checks_placeholder_date_and_cost():
    html = sw.render_daily_page([], {}, "2026-11-12")
    assert sw.validate_daily_html(html, "2026-11-12") == []
    assert any("占位符" in p for p in sw.validate_daily_html(html + "__DAILY_LEFT__", "2026-11-12"))
    assert any("資料日" in p for p in sw.validate_daily_html(html, "2026-11-13"))
    leaked = html + '<script>var X={"holdings":[{"code":"00882","cost": 15.2}]}</script>'
    assert any("成本" in p for p in sw.validate_daily_html(leaked, "2026-11-12"))


def test_daily_cli_writes_no_page_when_gate_fails(tmp_path, monkeypatch, capsys):
    out = tmp_path / "daily.html"
    monkeypatch.setattr(sw, "watchlist", lambda *a, **k: [])
    monkeypatch.setattr(sw, "scan", lambda items, prev, with_chart=False, now=None: [])
    monkeypatch.setattr(sw, "refresh_lagging", lambda rows, items, prev, with_chart=False: rows)
    rc = sw.main(["--scan", "00882:15", "--daily-html", str(out)])
    assert rc == 1 and not out.exists()
    assert "Gate Failed" in capsys.readouterr().err


def test_publish_gate_config_drives_daily_constants():
    """每日頁門檻改由 portfolio-patrol/references/publish_gate.json 提供，與 patrol.json 門檻共用。"""
    assert sw.DAILY_HOLDINGS == ("TPE:00882", "TPE:00406A")
    assert sw.DAILY_GENERAL_MAX == 2
    assert sw.DAILY_MAX_AGE_DAYS == 7


def test_load_publish_gate_fails_closed(tmp_path):
    with pytest.raises(OSError):
        sw.load_publish_gate(tmp_path / "none.json")
    bad = tmp_path / "gate.json"
    bad.write_text(json.dumps({"zero_tolerance": [], "general_max_anomalies": 2, "max_age_days": 7}), encoding="utf-8")
    with pytest.raises(ValueError):
        sw.load_publish_gate(bad)


def test_sheet_cli_gate_fails_on_empty_scan(tmp_path, monkeypatch):
    """swing_sync 以 --sheet --gate 呼叫；空掃描結果必須回傳非 0，讓排程停止而不是靜默成功。"""
    monkeypatch.setattr(sw, "watchlist", lambda *a, **k: [])
    monkeypatch.setattr(sw, "scan", lambda items, prev, with_chart=False, now=None: [])
    monkeypatch.setattr(sw, "refresh_lagging", lambda rows, items, prev, with_chart=False: rows)
    rc = sw.main(["--scan", "00882:15", "--sheet", str(tmp_path / "sheet.json"), "--gate"])
    assert rc == 1


def test_daily_page_carries_notices_into_head_block():
    """陷阱狀態未寫回時，警示文字放進頁面的 HEAD 資料，由頁面頂端的警示區顯示；沒有警示時為空清單。"""
    notice = "陷阱狀態未寫回：明日陷阱判定可能低估，請人工確認"
    html = sw.render_daily_page([], {}, "2026-10-27", notices=[notice])
    head = json.loads(html.split("var HEAD=", 1)[1].split(";var DATE", 1)[0])
    assert head["notices"] == [notice]
    assert "__DAILY_" not in html

    html_plain = sw.render_daily_page([], {}, "2026-10-27")
    head_plain = json.loads(html_plain.split("var HEAD=", 1)[1].split(";var DATE", 1)[0])
    assert head_plain["notices"] == []



def test_daily_page_links_tw_etf_detail_only_for_etfs_with_tw_constituents(tmp_path):
    """給了明細頁網址才放連結；只有成分股有 5 檔以上台股個股的台股 ETF 卡片列進 codes（00882 港股成分股、個股不列）。"""
    models = tmp_path / "repo" / "models"
    for code, tickers in (("00919", [f"{2300 + i}.TW" for i in range(6)]), ("00882", [f"{i}.HK" for i in range(6)])):
        (models / code / "cards").mkdir(parents=True)
        (models / code / "cards" / "constituents.jsonl").write_text("\n".join(json.dumps({"ticker": t}) for t in tickers), encoding="utf-8")
    rows = [{"ticker": "TPE:00919", "source": "ETF 卡片"}, {"ticker": "TPE:00882", "source": "ETF 卡片"},
            {"ticker": "TPE:2356", "source": "個股卡片"}]
    assert sw.tw_detail_codes(rows, models_dir=models) == ["00919"]
    url = "https://claude.ai/artifact/RoDHVZRr588JCcgzMswsug"
    html = sw.render_daily_page(rows, {}, "2026-11-09", etf_detail_url=url)  # 頁面用 repo 的 models：00919 有台股成分股卡片、00882 是港股
    head = json.loads(html.split("var HEAD=", 1)[1].split(";var DATE", 1)[0])
    assert head["etf_detail"] == {"url": url, "codes": ["00919"]}
    plain = sw.render_daily_page(rows, {}, "2026-11-09")
    assert "etf_detail" not in json.loads(plain.split("var HEAD=", 1)[1].split(";var DATE", 1)[0])

def test_fill_gaps_skips_twse_when_no_weekday_missing():
    now = datetime(2026, 11, 5, 8, 0, tzinfo=timezone.utc)  # 台北 16:00 週四
    start = datetime(2026, 10, 20, tzinfo=timezone.utc)
    bars = []
    for k in range(17):
        d = start + timedelta(days=k)
        if d.weekday() < 5:
            bars.append(dict(ts=int(d.timestamp()) + 3600, open=1, high=1, low=1, close=1, volume=1, adj=1))

    def never(url):
        raise AssertionError("不應呼叫證交所")
    assert sw.fill_gaps_from_twse(bars, "0050", now=now, fetch=never) == bars
