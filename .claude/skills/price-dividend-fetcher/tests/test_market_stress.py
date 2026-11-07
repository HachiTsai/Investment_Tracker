import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch_common as fc  # noqa: E402
import market_stress as ms  # noqa: E402
import swing as sw  # noqa: E402

TW = timezone(timedelta(hours=8))


def chart(closes, start=datetime(2026, 1, 5, 9, tzinfo=TW), divs=None):
    ts = [int((start + timedelta(days=i)).timestamp()) for i in range(len(closes))]
    ev = {str(t): {"date": t, "amount": a} for t, a in (divs or [])}
    return json.dumps({"chart": {"result": [{"timestamp": ts, "events": {"dividends": ev},
                                             "indicators": {"quote": [{"close": closes}], "adjclose": [{"adjclose": closes}]}}]}})


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(fc, "TWSE_MIN_INTERVAL", 0.0)
    monkeypatch.setattr(fc.time, "sleep", lambda s: None)


def fake_http(routes):
    def get(url, *_, **__):
        for key, body in routes.items():
            if key in url:
                if isinstance(body, Exception):
                    raise body
                return body
        raise RuntimeError("HTTP 404")
    return get


TAIFEX = json.dumps([
    {"Date": "20261104", "ContractCode": "臺股期貨", "Item": "投信", "OpenInterest(Net)": "89500"},
    {"Date": "20261104", "ContractCode": "臺股期貨", "Item": "外資及陸資", "OpenInterest(Net)": "-93647"},
    {"Date": "20261104", "ContractCode": "電子期貨", "Item": "外資及陸資", "OpenInterest(Net)": "-1"},
])
INST = json.dumps({"stat": "OK", "data": [["投信", "1", "1", "27,258,458,843"],
                                          ["外資及陸資(不含外資自營商)", "1", "1", "-149,899,834,076"]]})
MARGIN = json.dumps({"stat": "OK", "tables": [{"data": [["融資(交易單位)", "1", "1", "1", "1", "9,514,915"],
                                                        ["融資金額(仟元)", "1", "1", "1", "599,774,466", "596,945,870"]]}]})


def test_parsers():
    http = fake_http({"taifex": TAIFEX, "BFI82U": INST, "MI_MARGN": MARGIN})
    assert ms.taifex_futures_oi(http) == {"date": "20261104", "trust_net": 89500.0, "foreign_net": -93647.0}
    assert ms.twse_foreign_net("20261104", http) == pytest.approx(-149899834076.0)
    assert ms.twse_margin_balance("20261104", http) == pytest.approx(596945870.0)


def test_parsers_not_ok_returns_none():
    http = fake_http({"BFI82U": json.dumps({"stat": "很抱歉，沒有符合條件的資料!"}), "MI_MARGN": json.dumps({"stat": "NO"})})
    assert ms.twse_foreign_net("20261101", http) is None
    assert ms.twse_margin_balance("20261101", http) is None


def test_episode_detects_correction_and_none_when_calm():
    up = [100 + i * 0.5 for i in range(80)]
    crash = up + [up[-1] * (1 - 0.02 * k) for k in range(1, 8)]
    st = ms.index_state([f"d{i}" for i in range(len(crash))], crash)
    assert st["episode_start"] is not None and st["dd60_pct"] < -7
    assert st["above_ma10"] is False
    calm = ms.index_state([f"d{i}" for i in range(len(up))], up)
    assert calm["episode_start"] is None and calm["dd60_pct"] == 0.0


def test_capture_asymmetric():
    idx, etf = {}, {}
    a = b = 100.0
    for i in range(60):
        r = 0.01 if i % 2 else -0.01
        a *= 1 + r
        b *= 1 + (r * 1.1 if r > 0 else r * 1.4)
        idx[f"{i:03d}"], etf[f"{i:03d}"] = a, b
    c = ms.capture(etf, idx)
    assert c["up_capture"] == pytest.approx(1.1, abs=0.01)
    assert c["down_capture"] == pytest.approx(1.4, abs=0.01)
    assert ms.capture({"a": 1}, {"a": 1}) is None


def test_signals_status_and_missing():
    sig = ms.signals({"above_ma10": False, "rv10": 25.0, "ma10": 1}, {"ret5_pct": 1.0},
                     {"foreign_net": -93647}, [-1e10, -2e10], [4, 4, 5, 5])
    st = {s["key"]: s["status"] for s in sig}
    assert st == {"spot": "ok", "fut": "bad", "margin": "ok", "ma10": "warn", "rv": "warn", "sox": "ok"}
    none = {s["key"]: s["status"] for s in ms.signals(None, None, None, [], [])}
    assert set(none.values()) == {"na"}


def test_holding_breakeven_months():
    t0 = int(datetime(2026, 1, 20, 9, tzinfo=TW).timestamp())
    http = fake_http({"00406A.TW": chart([8.6] * 20 + [7.36], divs=[(t0, 0.138)])})
    h = ms.holding_state("00406A", 8.51, {}, http)
    assert h["vs_cost_pct"] == pytest.approx(-13.5)
    assert h["last_div"] == 0.138 and h["months_to_breakeven"] == 9


def test_build_survives_source_failures():
    http = fake_http({"%5ETWII": RuntimeError("HTTP 429"), "%5ESOX": RuntimeError("HTTP 429"),
                      "taifex": RuntimeError("timeout"), "00406A": RuntimeError("HTTP 429")})
    out = ms.build([("00406A", 8.51)], http, now=datetime(2026, 11, 5, 8, 50, tzinfo=TW))
    assert out["index"] is None and out["holdings"] == [] and out["calm_count"] == 0
    assert all(s["status"] == "na" for s in out["signals"])


def test_parse_track():
    assert ms.parse_track(["00406A:8.51"]) == [("00406A", 8.51)]
    assert ms.parse_track(["00406A"]) == [("00406A", None)]
    with pytest.raises(ValueError):
        ms.parse_track(["00406A:abc"])


def test_holding_without_cost_hides_cost_fields():
    t0 = int(datetime(2026, 1, 20, 9, tzinfo=TW).timestamp())
    http = fake_http({"00406A.TW": chart([8.6] * 20 + [7.36], divs=[(t0, 0.138)])})
    h = ms.holding_state("00406A", None, {}, http)
    assert h["cost"] is None and h["vs_cost_pct"] is None and h["months_to_breakeven"] is None
    assert h["last_div"] == 0.138


def test_daily_page_embeds_stress():
    page = sw.render_daily_page([], {}, "2026-11-05", stress={"active": True, "signals": []})
    assert '"stress": {"active": true' in page and 'id="mstress"' in page
    assert '"stress": null' in sw.render_daily_page([], {}, "2026-11-05")


def test_twse_index_fills_yahoo_lag():
    body = json.dumps({"stat": "OK", "data": [["115/11/04", "1", "1", "1", "42,948.91", "-358.63"],
                                              ["115/11/05", "1", "1", "1", "41,574.72", "-1,374.19"]]})
    extra = ms.twse_index_month("20261105", fake_http({"FMTQIK": body}))
    assert extra == {"2026-11-04": 42948.91, "2026-11-05": 41574.72}
    d, c, a = ms.fill_index_tail(["2026-11-03", "2026-11-04"], [1.0, 2.0], [1.0, 2.0], extra)
    assert d[-1] == "2026-11-05" and c[-1] == 41574.72 and len(d) == 3


def test_twse_get_backs_off_longer_when_blocked():
    calls, waits = [], []

    def flaky(url, referer=None, attempts=1):
        calls.append(url)
        if len(calls) < 3:
            raise RuntimeError("HTTP 307（https://www.twse.com.tw/x）")
        return "ok"
    assert fc.twse_get("u", http_fn=flaky, sleep=waits.append) == "ok"
    assert len(calls) == 3 and waits == [10, 20]


def test_twse_get_raises_after_attempts():
    def down(url, referer=None, attempts=1):
        raise RuntimeError("HTTP 500（x）")
    waits = []
    with pytest.raises(RuntimeError, match="HTTP 500"):
        fc.twse_get("u", http_fn=down, attempts=3, sleep=waits.append)
    assert waits == [3, 6]


def test_twse_throttle_spaces_requests(monkeypatch):
    monkeypatch.setattr(fc, "TWSE_MIN_INTERVAL", 3.0)
    t = [100.0]
    slept = []

    def sleep(s):
        slept.append(round(s, 2))
        t[0] += s
    monkeypatch.setattr(fc, "_twse_last", [99.0])
    fc._twse_throttle(sleep, clock=lambda: t[0])
    assert slept == [2.0]


def test_holding_tail_filled_from_twse_when_yahoo_lags():
    """Yahoo 個股日線晚一天（00406A 缺 11-06）：以證交所收盤價補在尾端，且不補今天（可能是盤中）。"""
    start = datetime(2026, 11, 2, 9, tzinfo=TW)
    twse = json.dumps({"stat": "OK", "data": [
        ["115/11/05", "1", "1", "1", "1", "1", "7.36", "1", "1"],
        ["115/11/06", "1", "1", "1", "1", "1", "7.10", "1", "1"],
        ["115/11/07", "1", "1", "1", "1", "1", "7.20", "1", "1"]]})
    http = fake_http({"00406A.TW": chart([8.0, 7.9, 7.8, 7.36], start=start), "STOCK_DAY": twse})
    h = ms.holding_state("00406A", None, {}, http, now=datetime(2026, 11, 7, 9, 12, tzinfo=TW))
    assert h["date"] == "2026-11-06" and h["close"] == 7.10


def test_holding_tail_unchanged_when_twse_fails():
    start = datetime(2026, 11, 2, 9, tzinfo=TW)
    http = fake_http({"00406A.TW": chart([8.0, 7.9, 7.8, 7.36], start=start), "STOCK_DAY": RuntimeError("HTTP 307")})
    h = ms.holding_state("00406A", None, {}, http, now=datetime(2026, 11, 7, 9, 12, tzinfo=TW))
    assert h["date"] == "2026-11-05" and h["close"] == 7.36
