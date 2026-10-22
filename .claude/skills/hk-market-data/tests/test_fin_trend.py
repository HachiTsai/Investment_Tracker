import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from fin_trend import enrich  # noqa: E402


def _h(p, k, eps, rev=100.0, np=10.0, **kw):
    return dict(p=p, k=k, eps=eps, rev=rev, np=np, **kw)


def test_single_quarter_eps_and_yoy():
    hist = [_h("2026-06-30", "2026年中报", 0.63, 110, 11), _h("2026-03-31", "2026年一季报", 0.36),
            _h("2025-12-31", "2025年年报", 1.2), _h("2025-09-30", "2025年三季报", 0.89),
            _h("2025-06-30", "2025年中报", 0.62, 100, 10), _h("2025-03-31", "2025年一季报", 0.36)]
    out = enrich({"hist": hist, "org": "一般企业"})
    assert round(out["hist"][0]["qeps"], 2) == 0.27 and out["hist"][1]["qeps"] == 0.36
    assert out["yoy_rev"] == 10.0 and out["yoy_np"] == 10.0
    assert any(s["t"].startswith("營收年增") for s in out["sigs"])


def test_half_year_only_reporter_uses_cumulative_as_period():
    hist = [_h("2026-06-30", "2026年中报", 0.2), _h("2025-12-31", "2025年年报", 0.8), _h("2025-06-30", "2025年中报", 0.18)]
    out = enrich({"hist": hist})
    assert out["hist"][0]["qeps"] == 0.2 and round(out["hist"][1]["qeps"], 2) == 0.62


def test_cash_flow_and_payout_signals_skip_financials():
    base = [_h("2026-06-30", "2026年中报", 1.0, np=10.0, ocf=-5.0)]
    assert any("現金流為負" in s["t"] for s in enrich({"hist": base, "org": "一般企业"})["sigs"])
    assert not any("現金流" in s["t"] for s in enrich({"hist": base, "org": "银行"})["sigs"])
    assert any("配發率" in s["t"] for s in enrich({"hist": base, "payout": 150})["sigs"])


def test_no_history_returns_input():
    assert enrich({"eps": 1}) == {"eps": 1}


def test_dividends_paid_ytd_and_payout_ratios():
    from datetime import date
    from fin_trend import add_dividends, rmb_hint
    hist = [_h("2026-06-30", "2026年中报", 0.63), _h("2025-12-31", "2025年年报", 1.2)]
    divs = [
        dict(nd="2026-08-26", year="2026", kind="中期分配", pay="2026-12-22", amt=0.203, cur="人民币", hkd=0.2346),
        dict(nd="2026-03-20", year="2025", kind="年度分配", pay="2026-07-06", amt=0.193, cur="人民币", hkd=0.2207),
        dict(nd="2025-08-27", year="2025", kind="中期分配", pay="2025-12-29", amt=0.188, cur="人民币", hkd=0.2061),
    ]
    out = add_dividends({"hist": hist, "cur": "人民币"}, divs, date(2026, 10, 22))
    assert out["ytd"] == 0.2207 and out["pending"] == 0.2346
    assert out["dr_cur"] == 32.2 and round(out["dr_fy"], 1) == 31.8
    assert rmb_hint([divs])["人民币"] > 1


def test_dividends_negative_eps_and_missing_rate_blank():
    from datetime import date
    from fin_trend import add_dividends
    hist = [_h("2026-06-30", "2026年中报", -0.1)]
    divs = [dict(nd="2026-08-28", year="2026", kind="中期分配", amt=0.0, cur=None, hkd=0.0)]
    assert "dr_cur" not in add_dividends({"hist": hist, "cur": "港元"}, divs, date(2026, 10, 22))


def test_undeclared_latest_period_leaves_current_ratio_blank():
    from datetime import date
    from fin_trend import add_dividends
    hist = [_h("2026-06-30", "2026年中报", 0.5)]
    divs = [dict(nd="2026-08-28", year="2026", kind="中期分配", amt=0.0, cur=None, hkd=0.0)]
    assert "dr_cur" not in add_dividends({"hist": hist, "cur": "人民币"}, divs, date(2026, 10, 22))


def test_dividend_streak_cagr_and_cover():
    from datetime import date
    from fin_trend import add_dividends
    hist = [_h("2025-12-31", "2025年年报", 1.0)]
    divs = [dict(nd=f"{y + 1}-03-20", year=str(y), kind="年度分配", pay=f"{y + 1}-07-01", amt=0.1 * (1.1 ** (y - 2020)), cur="港币", hkd=0.1 * (1.1 ** (y - 2020))) for y in range(2025, 2019, -1)]
    out = add_dividends({"hist": hist, "cur": "港元"}, divs, date(2026, 10, 22))
    assert out["streak"] == 6 and out["cagr_n"] == 5 and abs(out["cagr"] - 10.0) < 0.2
    assert out["cover"] == round(100 / out["dr_fy"], 2)


def test_gross_margin_and_current_ratio_signals_skip_financials():
    base = [dict(_h("2026-06-30", "2026年中报", 1.0), gpm=30.0), dict(_h("2025-06-30", "2025年中报", 0.9), gpm=35.0)]
    out = enrich({"hist": base, "org": "一般企业", "cr": 0.8})
    assert any("毛利率" in s["t"] for s in out["sigs"]) and any("流動比率" in s["t"] for s in out["sigs"])
    assert not any("流動比率" in s["t"] for s in enrich({"hist": base, "org": "银行", "cr": 0.8})["sigs"])
