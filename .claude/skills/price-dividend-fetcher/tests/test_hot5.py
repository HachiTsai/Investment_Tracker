import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import hot5  # noqa: E402

SAMPLE = {
    "days": ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19"],
    "twse": [{"code": "2330", "name": "台積電", "amt": 486137908632.0, "lots": 198136.488, "base": 2540.0, "last": 2420.0, "chg": -4.72}],
    "tpex": [{"code": "1815", "name": "富喬", "amt": 83388418805.0, "lots": 600443.067, "base": 133.0, "last": 154.0, "chg": 15.79}],
    "emerging": [{"code": "6696", "name": "仁新*", "amt": 5955812699.0, "lots": 36842.116, "base": None, "last": None, "chg": None}],
}


def test_code_filter_keeps_common_stock_and_etf_only():
    assert hot5.ok("2330") and hot5.ok("00882") and hot5.ok("00980D")
    assert not hot5.ok("9101") and not hot5.ok("030001") and not hot5.ok("2330A")


def test_number_parser():
    assert hot5.n("1,234.5") == 1234.5
    assert hot5.n("--") is None


def test_render_range_and_colors():
    html = hot5.render(SAMPLE)
    assert "10/13、10/14、10/15、10/16、10/19" in html
    assert "基準日 10/12" in html
    assert '<td class="n dn">-4.72%</td>' in html
    assert '<td class="n up">+15.79%</td>' in html
    assert "4,861.38" in html  # 億元


def test_render_handles_missing_price():
    assert "<td class=\"n \">—</td>" in hot5.render(SAMPLE)


def test_fetch_exits_3_when_today_has_no_data(monkeypatch, tmp_path):
    monkeypatch.setattr(hot5, "fetch", lambda today: None)
    out = tmp_path / "h.json"
    assert hot5.main(["fetch", "2026-10-20", "--out", str(out)]) == hot5.NO_DATA == 3
    assert not out.exists()


def test_fetch_writes_json_and_render_cli(monkeypatch, tmp_path):
    monkeypatch.setattr(hot5, "fetch", lambda today: SAMPLE)
    j, h = tmp_path / "h.json", tmp_path / "h.html"
    assert hot5.main(["fetch", "2026-10-19", "--out", str(j)]) == 0
    assert json.loads(j.read_text())["days"][-1] == "2026-10-19"
    assert hot5.main(["render", str(j), "--out", str(h)]) == 0
    assert "台股三市場" in h.read_text()


def test_rank_cumulative_amount_and_change():
    d0, d1 = '2026-10-12', '2026-10-13'
    src = {
        d0: {'A': dict(name='甲', amt=0, sh=0, close=10.0), 'B': dict(name='乙', amt=0, sh=0, close=20.0)},
        d1: {'A': dict(name='甲', amt=800, sh=5000, close=12.0), 'B': dict(name='乙', amt=100, sh=1000, close=18.0)},
    }
    out = hot5.rank(src, [d1], d0)
    assert [r['code'] for r in out] == ['A', 'B']
    assert out[0]['amt'] == 800 and out[0]['lots'] == 5
    assert round(out[0]['chg'], 1) == 20.0 and round(out[1]['chg'], 1) == -10.0
