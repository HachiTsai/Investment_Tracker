"""評分矩陣：趨勢、MACD 動能、均量比、近 1 年含息報酬，各 0–100 分。

與 Stock_AIStudio/src/services/technicalService.ts 同一套算法（還原收盤價；趨勢與動能以日波動標準化後 tanh 壓縮，
50 為持平）。分數描述強度與位置，不是好壞評分，也不是買賣指示。
"""
import math
from typing import Dict, List, Optional

from swing import ema


def _clamp(n: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return min(hi, max(lo, n))


def _squash(z: float) -> float:
    return 50 + 50 * math.tanh(z)


def return_score(total_return_pct: float) -> float:
    """1 年含息報酬評分：0% 為 40 分，負報酬每 -1% 扣 2 分，15%/35%/60% 分別對應 55/75/90 分。"""
    r = total_return_pct
    if r < 0:
        s = _clamp(40 + r * 2, 0, 40)
    elif r <= 15:
        s = 40 + r / 15 * 15
    elif r <= 35:
        s = 55 + (r - 15) / 20 * 20
    elif r <= 60:
        s = 75 + (r - 35) / 25 * 15
    else:
        s = _clamp(90 + (r - 60) / 40 * 10, 90, 100)
    return round(s, 1)


def compute_scores(bars: List[Dict]) -> Optional[Dict[str, float]]:
    """bars 需含 adj 與 volume；不足 60 根回傳 None。"""
    if len(bars) < 60:
        return None
    px = [b.get("adj", b["close"]) for b in bars]
    last = px[-1]
    ma60 = sum(px[-60:]) / 60
    dev_pct = (last - ma60) / ma60 * 100
    dif = [a - b for a, b in zip(ema(px, 12), ema(px, 26))]
    hist_pct = (dif[-1] - ema(dif, 9)[-1]) / last * 100
    rets = [px[i] / px[i - 1] - 1 for i in range(1, len(px))]
    mean = sum(rets) / len(rets)
    vol_pct = max(math.sqrt(sum((r - mean) ** 2 for r in rets) / len(rets)) * 100, 0.1)
    vols = [b["volume"] for b in bars]
    avg60 = sum(vols[-60:]) / 60
    vol_ratio = sum(vols[-5:]) / 5 / avg60 if avg60 > 0 else 1.0
    total = (last - px[0]) / px[0] * 100 if px[0] > 0 else 0.0
    out = {
        "trend_score": _squash(dev_pct / (vol_pct * math.sqrt(30)) / 1.5),
        "macd_score": _squash(hist_pct / vol_pct / 0.8),
        "vol_score": _clamp(vol_ratio * 50),
        "return_score": return_score(total),
        "return_1y_pct": total,
    }
    out["total_score"] = (out["trend_score"] + out["macd_score"] + out["vol_score"] + out["return_score"]) / 4
    return {k: round(v, 1) for k, v in out.items()}
