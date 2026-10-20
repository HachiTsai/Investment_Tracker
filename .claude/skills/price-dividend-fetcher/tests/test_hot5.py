import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import hot5_fetch as h  # noqa: E402
import hot5_report as r  # noqa: E402


def test_ok_filters_ordinary_stocks_and_etfs():
    assert h.ok("2330") and h.ok("0050") and h.ok("00882") and h.ok("00981A")
    assert not h.ok("910001") and not h.ok("9101") and not h.ok("03001P")


def test_rank_sums_window_and_uses_base_close():
    d0, d1, d2 = date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)
    src = {
        d0: {"A": dict(name="甲", sh=1000, amt=100, close=10.0), "B": dict(name="乙", sh=1000, amt=900, close=10.0)},
        d1: {"A": dict(name="甲", sh=2000, amt=300, close=11.0), "B": dict(name="乙", sh=1000, amt=100, close=9.0)},
        d2: {"A": dict(name="甲", sh=3000, amt=500, close=12.0), "B": dict(name="乙", sh=1000, amt=100, close=9.0)},
    }
    out = h.rank(src, [d1, d2], d0)
    assert [x["code"] for x in out] == ["A", "B"]
    assert out[0]["amt"] == 800 and out[0]["lots"] == 5
    assert round(out[0]["chg"], 2) == 20.0 and round(out[1]["chg"], 2) == -10.0


def test_main_exits_3_when_today_has_no_data(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(h, "twse", lambda d: None)
    monkeypatch.setattr(h.time, "sleep", lambda s: None)
    monkeypatch.chdir(tmp_path)
    assert h.main(["2026-10-20"]) == 3
    assert not (tmp_path / "hot5.json").exists()
    assert "NO_DATA_FOR_TODAY" in capsys.readouterr().out


def test_render_contains_range_and_three_markets():
    row = dict(code="2330", name="台積電", amt=5e10, lots=12345.0, base=100.0, last=105.0, chg=5.0)
    html = r.render({"days": ["2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19", "2026-10-20"],
                     "twse": [row], "tpex": [row], "emerging": [row]})
    assert "10/15–10/20" in html and "基準日 10/14" in html
    assert html.count("<section>") == 3 and "+5.00%" in html and "<title>台股五日熱門股</title>" in html
