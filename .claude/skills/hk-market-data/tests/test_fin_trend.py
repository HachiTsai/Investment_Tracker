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
