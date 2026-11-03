"""債券 ETF 穿透（兩層，純本地、標準函式庫、不連網）。

資料只用 models/<代號>/cards/constituents.jsonl 的債券代號字串（票息與到期日寫在代號裡），
不逐檔抓財報，檔數多（數百檔）也只是毫秒級字串解析，不增加巡檢負擔。

第一層（持股結構）：加權票息、到期年限分布、發行人集中度。
第二層（信用風險代理）：沒有逐檔信評資料，改用「票息減無風險參考利率」的利差代理分級。
  這是代理指標，不是信評；報告與輸出一律標示「非信評」。參考利率是假設值（預設 4.0%），可由呼叫端覆寫。
"""

from __future__ import annotations

import datetime
import re
from typing import Any, Dict, List, Optional, Tuple

# 無風險參考利率（假設值，單位 %）；只用於利差代理，非查證數字
DEFAULT_RISK_FREE_PCT = 4.0

# 利差代理分級：(利差上限 %, 標籤, 壓力分)。壓力分 0 最安全、100 最危險
SPREAD_BANDS: List[Tuple[float, str, int]] = [
    (1.5, "投資等級區間", 0),
    (3.5, "BB 區間", 25),
    (5.5, "B 區間", 60),
    (float("inf"), "CCC 以下壓力區間", 100),
]

# 到期年限分組（年）
MATURITY_BUCKETS: List[Tuple[float, str]] = [
    (3.0, "3年內"),
    (5.0, "3到5年"),
    (10.0, "5到10年"),
    (float("inf"), "10年以上"),
]

# 到期日後的選用尾綴：C、MTN、GMTN、* 等
_SUFFIX = r"(?:\s+[A-Z]{1,5})?\s*\*?"
_COUPON = r"(?P<cpn>\d+\.\d+|\d+ \d+/\d+|\d+/\d+|\d+)"
# 格式一：BBDBCN 8 3/4 11/15/30 或 ABIBB 4.9 02/01/46 *
_FMT_SLASH = re.compile(rf"^(?P<issuer>\S+)\s+{_COUPON}\s+(?P<m>\d\d)/(?P<d>\d\d)/(?P<y>\d{{2}}|\d{{4}}){_SUFFIX}$")
# 格式二：PFIZER INVESTMENT ENTER 5.3% 05/19/2053 或 US TREASURY N/B 4.75% 05/15/2055
_FMT_PCT = re.compile(rf"^(?P<issuer>.+?)\s+{_COUPON}%\s+(?P<m>\d\d)/(?P<d>\d\d)/(?P<y>\d{{4}}){_SUFFIX}$")
# 格式三：GOLDMAN SACHS GROUP INC 6.75-2037/10/01
_FMT_DASH = re.compile(rf"^(?P<issuer>.+?)\s+{_COUPON}-(?P<y>\d{{4}})/(?P<m>\d\d)/(?P<d>\d\d){_SUFFIX}$")


def _coupon_value(text: str) -> float:
    """解析票息字串：4.9、8 3/4、1/2、7。"""
    if " " in text:
        whole, frac = text.split(" ", 1)
        num, den = frac.split("/")
        return float(whole) + int(num) / int(den)
    if "/" in text:
        num, den = text.split("/")
        return int(num) / int(den)
    return float(text)


def parse_bond(code: str) -> Optional[Dict[str, Any]]:
    """把債券代號解析成發行人、票息（%）與到期日；格式不符回傳 None。"""
    s = (code or "").strip()
    for pat in (_FMT_PCT, _FMT_DASH, _FMT_SLASH):
        m = pat.match(s)
        if not m:
            continue
        year = int(m.group("y"))
        if year < 100:
            year += 2000
        try:
            maturity = datetime.date(year, int(m.group("m")), int(m.group("d")))
            coupon = _coupon_value(m.group("cpn"))
        except (ValueError, ZeroDivisionError):
            return None
        return {"issuer": m.group("issuer").strip(), "coupon_pct": coupon, "maturity": maturity}
    return None


def _band(spread_pct: float) -> Tuple[str, int]:
    for upper, label, stress in SPREAD_BANDS:
        if spread_pct < upper:
            return label, stress
    return SPREAD_BANDS[-1][1], SPREAD_BANDS[-1][2]


def _bucket(years: float) -> str:
    for upper, label in MATURITY_BUCKETS:
        if years < upper:
            return label
    return MATURITY_BUCKETS[-1][1]


def analyze_bond_etf(
    constituents: List[Dict[str, Any]],
    today: Optional[datetime.date] = None,
    risk_free_pct: float = DEFAULT_RISK_FREE_PCT,
) -> Dict[str, Any]:
    """對全部債券持股做兩層穿透。constituents 為含 ticker 與 weight_pct 的清單。"""
    today = today or datetime.date.today()
    total_w = sum(float(c.get("weight_pct") or 0.0) for c in constituents)
    parsed: List[Dict[str, Any]] = []
    unparsed: List[str] = []
    for c in constituents:
        w = float(c.get("weight_pct") or 0.0)
        info = parse_bond(str(c.get("ticker") or c.get("name") or ""))
        if info is None:
            unparsed.append(str(c.get("ticker") or c.get("name") or ""))
            continue
        years = max((info["maturity"] - today).days / 365.25, 0.0)
        info.update(weight=w, years=years)
        parsed.append(info)

    parsed_w = sum(p["weight"] for p in parsed)
    result: Dict[str, Any] = {
        "holdings_count": len(constituents),
        "parsed_count": len(parsed),
        "parse_coverage_pct": round(parsed_w / total_w * 100.0, 1) if total_w > 0 else 0.0,
        "unparsed_sample": unparsed[:5],
        "risk_free_assumption_pct": risk_free_pct,
        "credit_note": "利差代理分級，非信評；參考利率為假設值",
    }
    if parsed_w <= 0:
        result["layer1"] = None
        result["layer2"] = None
        return result

    # 第一層
    wc = sum(p["weight"] * p["coupon_pct"] for p in parsed) / parsed_w
    wam = sum(p["weight"] * p["years"] for p in parsed) / parsed_w
    buckets: Dict[str, float] = {label: 0.0 for _, label in MATURITY_BUCKETS}
    issuers: Dict[str, float] = {}
    for p in parsed:
        buckets[_bucket(p["years"])] += p["weight"]
        issuers[p["issuer"]] = issuers.get(p["issuer"], 0.0) + p["weight"]
    top = sorted(issuers.items(), key=lambda kv: kv[1], reverse=True)
    result["layer1"] = {
        "weighted_coupon_pct": round(wc, 2),
        "weighted_years_to_maturity": round(wam, 2),
        "maturity_buckets_pct": {k: round(v / parsed_w * 100.0, 1) for k, v in buckets.items()},
        "issuer_count": len(issuers),
        "top1_issuer": top[0][0],
        "top1_issuer_pct": round(top[0][1] / parsed_w * 100.0, 2),
        "top10_issuer_pct": round(sum(v for _, v in top[:10]) / parsed_w * 100.0, 1),
    }

    # 第二層：利差代理
    bands: Dict[str, float] = {label: 0.0 for _, label, _ in SPREAD_BANDS}
    stress_sum = 0.0
    for p in parsed:
        label, stress = _band(p["coupon_pct"] - risk_free_pct)
        bands[label] += p["weight"]
        stress_sum += stress * p["weight"]
    stress = stress_sum / parsed_w
    result["layer2"] = {
        "credit_proxy_score": round(100.0 - stress, 1),
        "avg_stress": round(stress, 1),
        "band_pct": {k: round(v / parsed_w * 100.0, 1) for k, v in bands.items()},
        "high_coupon_9pct_share": round(
            sum(p["weight"] for p in parsed if p["coupon_pct"] >= 9.0) / parsed_w * 100.0, 1
        ),
        "long_10y_share": round(sum(p["weight"] for p in parsed if p["years"] >= 10.0) / parsed_w * 100.0, 1),
    }
    return result


def format_bond_ascii(etf_id: str, res: Dict[str, Any]) -> str:
    """債券穿透的終端機輸出。"""
    l1, l2 = res.get("layer1"), res.get("layer2")
    lines = ["=" * 72, f"🏛️ 債券 ETF 穿透：【{etf_id}】（{res['holdings_count']} 檔，解析權重 {res['parse_coverage_pct']}%）", "=" * 72]
    if not l1 or not l2:
        lines.append("  資料不足：持股代號無法解析，不判定。")
        return "\n".join(lines)
    lines += [
        "【第一層 持股結構】",
        f"  加權票息 {l1['weighted_coupon_pct']}% ｜ 加權到期年限 {l1['weighted_years_to_maturity']} 年",
        "  到期分布 " + "、".join(f"{k} {v}%" for k, v in l1["maturity_buckets_pct"].items()),
        f"  發行人 {l1['issuer_count']} 家 ｜ 最大 {l1['top1_issuer']} {l1['top1_issuer_pct']}% ｜ 前十大 {l1['top10_issuer_pct']}%",
        "【第二層 信用風險代理（非信評）】",
        f"  代理分 {l2['credit_proxy_score']} / 100（越高越安全）｜ 參考利率假設 {res['risk_free_assumption_pct']}%",
        "  利差分級 " + "、".join(f"{k} {v}%" for k, v in l2["band_pct"].items()),
        f"  票息 9% 以上占 {l2['high_coupon_9pct_share']}% ｜ 10 年以上占 {l2['long_10y_share']}%",
        "  註：無逐檔信評資料；分數不可與股票型 netScore 比較。",
        "=" * 72,
    ]
    return "\n".join(lines)
