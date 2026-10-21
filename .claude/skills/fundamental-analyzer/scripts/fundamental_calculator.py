#!/usr/bin/env python3
"""個股財務指標與基本面評分演算核心 (Fundamental Calculator Core)。

實作 scoring-model.md 定義之四大象限量化評分：
- divScore: 股利可持續性評分（自由現金流覆蓋、盈餘配發率、現金含金量）
- netScore: 綜合財務健康評分（ROE、負債比、營業利益率）
- valScore: 估值與安全邊際評分（P/E、P/B、殖利率）
- fricScore: 摩擦阻力評分（稅費、二代健保、匯率）
"""

import datetime
import json
import math
from pathlib import Path
from typing import Any, Dict, Optional

CACHE_DIR = Path.home() / ".cache" / "investment_tracker"
CACHE_FILE = CACHE_DIR / "stock_fundamentals.json"
CACHE_TTL_DAYS = 7


def _load_cache() -> Dict[str, Any]:
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(cache: Dict[str, Any]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def score_fcf_coverage(coverage: Optional[float]) -> float:
    """計算自由現金流覆蓋倍數得分 (權重 40%)。"""
    if coverage is None or math.isnan(coverage):
        return 50.0
    if coverage >= 2.0:
        return 100.0
    elif coverage >= 1.5:
        return 85.0 + (coverage - 1.5) / 0.5 * 15.0
    elif coverage >= 1.0:
        return 60.0 + (coverage - 1.0) / 0.5 * 25.0
    elif coverage >= 0.5:
        return 30.0 + (coverage - 0.5) / 0.5 * 30.0
    else:
        return max(10.0, coverage * 40.0)


def score_payout_ratio(payout: Optional[float]) -> float:
    """計算盈餘配發率得分 (權重 35%)。健康區間為 40% ~ 70%。"""
    if payout is None or math.isnan(payout):
        return 50.0
    if 0.40 <= payout <= 0.70:
        return 100.0
    elif 0.70 < payout <= 0.85:
        return 90.0 - (payout - 0.70) / 0.15 * 15.0
    elif 0.85 < payout <= 1.00:
        return 75.0 - (payout - 0.85) / 0.15 * 25.0
    elif payout > 1.00:
        return max(20.0, 50.0 - (payout - 1.00) * 30.0)
    elif 0.20 <= payout < 0.40:
        return 60.0 + (payout - 0.20) / 0.20 * 40.0
    else:
        return 50.0


def score_ocf_quality(ratio: Optional[float]) -> float:
    """計算營業現金流品質 OCF / Net Income 得分 (權重 25%)。"""
    if ratio is None or math.isnan(ratio):
        return 50.0
    if ratio >= 1.2:
        return 100.0
    elif ratio >= 1.0:
        return 80.0 + (ratio - 1.0) / 0.2 * 20.0
    elif ratio >= 0.8:
        return 60.0 + (ratio - 0.8) / 0.2 * 20.0
    else:
        return max(20.0, ratio * 50.0)


def calculate_div_score(
    fcf_coverage: Optional[float],
    payout_ratio: Optional[float],
    ocf_quality: Optional[float],
) -> float:
    """計算綜合股利可持續性評分 (0 ~ 100)。"""
    s_fcf = score_fcf_coverage(fcf_coverage)
    s_payout = score_payout_ratio(payout_ratio)
    s_ocf = score_ocf_quality(ocf_quality)
    total = s_fcf * 0.40 + s_payout * 0.35 + s_ocf * 0.25
    return round(min(100.0, max(0.0, total)), 1)


def score_roe(roe: Optional[float]) -> float:
    """計算股東權益報酬率 ROE 得分 (權重 40%)。"""
    if roe is None or math.isnan(roe):
        return 50.0
    if roe >= 0.20:
        return 100.0
    elif roe >= 0.15:
        return 85.0 + (roe - 0.15) / 0.05 * 15.0
    elif roe >= 0.10:
        return 70.0 + (roe - 0.10) / 0.05 * 15.0
    elif roe >= 0.05:
        return 45.0 + (roe - 0.05) / 0.05 * 25.0
    else:
        return max(10.0, roe * 200.0)


def score_debt_to_equity(dte: Optional[float]) -> float:
    """計算負債權益比得分 (權重 30%)，越低越優。"""
    if dte is None or math.isnan(dte):
        return 50.0
    # yfinance 中的 debtToEquity 常以百分比數值呈現（如 50 代表 50%）
    ratio = dte / 100.0 if dte > 10.0 else dte
    if ratio <= 0.50:
        return 100.0
    elif ratio <= 1.00:
        return 80.0 + (1.00 - ratio) / 0.50 * 20.0
    elif ratio <= 1.50:
        return 65.0 + (1.50 - ratio) / 0.50 * 15.0
    elif ratio <= 2.00:
        return 45.0 + (2.00 - ratio) / 0.50 * 20.0
    else:
        return max(20.0, 45.0 - (ratio - 2.00) * 10.0)


def score_operating_margin(margin: Optional[float]) -> float:
    """計算營業利益率得分 (權重 30%)。"""
    if margin is None or math.isnan(margin):
        return 50.0
    if margin >= 0.30:
        return 100.0
    elif margin >= 0.20:
        return 85.0 + (margin - 0.20) / 0.10 * 15.0
    elif margin >= 0.10:
        return 65.0 + (margin - 0.10) / 0.10 * 20.0
    elif margin >= 0.05:
        return 45.0 + (margin - 0.05) / 0.05 * 20.0
    else:
        return max(20.0, margin * 400.0)


def calculate_net_score(
    roe: Optional[float],
    debt_to_equity: Optional[float],
    operating_margin: Optional[float],
) -> float:
    """計算綜合財務健康評分 (0 ~ 100)。"""
    s_roe = score_roe(roe)
    s_dte = score_debt_to_equity(debt_to_equity)
    s_margin = score_operating_margin(operating_margin)
    total = s_roe * 0.40 + s_dte * 0.30 + s_margin * 0.30
    return round(min(100.0, max(0.0, total)), 1)


def score_pe(pe: Optional[float]) -> float:
    """計算本益比得分。"""
    if pe is None or math.isnan(pe) or pe <= 0:
        return 50.0
    if pe <= 12.0:
        return 100.0
    elif pe <= 18.0:
        return 80.0 + (18.0 - pe) / 6.0 * 20.0
    elif pe <= 25.0:
        return 60.0 + (25.0 - pe) / 7.0 * 20.0
    else:
        return max(20.0, 60.0 - (pe - 25.0) * 2.0)


def score_pb(pb: Optional[float]) -> float:
    """計算股價淨值比得分。"""
    if pb is None or math.isnan(pb) or pb <= 0:
        return 50.0
    if pb <= 1.2:
        return 100.0
    elif pb <= 2.0:
        return 80.0 + (2.0 - pb) / 0.8 * 20.0
    elif pb <= 3.5:
        return 55.0 + (3.5 - pb) / 1.5 * 25.0
    else:
        return max(25.0, 55.0 - (pb - 3.5) * 5.0)


def score_yield(y: Optional[float]) -> float:
    """計算殖利率得分。"""
    if y is None or math.isnan(y) or y <= 0:
        return 40.0
    rate = y / 100.0 if y > 1.0 else y
    if rate >= 0.07:
        return 100.0
    elif rate >= 0.05:
        return 80.0 + (rate - 0.05) / 0.02 * 20.0
    elif rate >= 0.03:
        return 60.0 + (rate - 0.03) / 0.02 * 20.0
    else:
        return 40.0


def calculate_val_score(
    pe: Optional[float],
    pb: Optional[float],
    dividend_yield: Optional[float],
) -> float:
    """計算估值與安全邊際評分 (0 ~ 100)。"""
    s_pe = score_pe(pe)
    s_pb = score_pb(pb)
    s_y = score_yield(dividend_yield)
    total = s_pe * 0.40 + s_pb * 0.30 + s_y * 0.30
    return round(min(100.0, max(0.0, total)), 1)


def calculate_fric_score(symbol: Optional[str], asset_category: str = "STOCK") -> float:
    """根據資產類別與交易所屬性計算摩擦阻力評分 (0 ~ 100)。"""
    if not symbol or not isinstance(symbol, str):
        return 70.0
    sym = symbol.upper()
    cat = asset_category.upper()

    if cat == "BOND" or "B" in sym or "TREASURY" in sym or "BOND" in sym:
        return 95.0
    elif ".HK" in sym or "00882" in sym:
        return 85.0
    elif ".TW" in sym or (sym.isdigit() and len(sym) in (4, 5)):
        return 80.0
    elif ".JP" in sym or ".T" in sym:
        return 75.0
    elif ".US" in sym or sym.isalpha():
        return 55.0
    return 70.0


def normalize_ticker_for_yf(symbol: Optional[str]) -> str:
    """將各市場成分股後綴轉換為 yfinance 標準代號格式。"""
    if not symbol or not isinstance(symbol, str):
        return ""
    sym = symbol.strip().upper()
    if sym.endswith(".US"):
        return sym[:-3]
    elif sym.endswith(".JP"):
        return f"{sym[:-3]}.T"
    elif sym.endswith(".HK"):
        code = sym[:-3]
        return f"{code.zfill(4)}.HK"
    elif sym.isdigit():
        return f"{sym}.TW"
    return sym


def calculate_stock_fundamentals(
    symbol: Optional[str],
    mock_data: Optional[Dict[str, Any]] = None,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """獲取單一股票基本面數據並進行評分計算。"""
    if not symbol or not isinstance(symbol, str):
        return {
            "symbol": str(symbol),
            "roe": None,
            "debt_to_equity": None,
            "operating_margin": None,
            "payout_ratio": None,
            "fcf_coverage": None,
            "pe": None,
            "pb": None,
            "yield_pct": None,
            "scores": {
                "netScore": 60.0,
                "divScore": 60.0,
                "valScore": 60.0,
                "fricScore": 70.0,
            },
        }

    # 檢查是否為國債、期貨或債券型成分標的
    sym_upper = symbol.upper()
    if "TREASURY" in sym_upper or "期貨" in sym_upper or "BOND" in sym_upper:
        return {
            "symbol": symbol,
            "roe": None,
            "debt_to_equity": None,
            "operating_margin": None,
            "payout_ratio": None,
            "fcf_coverage": None,
            "pe": None,
            "pb": None,
            "yield_pct": None,
            "scores": {
                "netScore": 75.0,
                "divScore": 85.0,
                "valScore": 70.0,
                "fricScore": 95.0,
            },
        }

    # 檢查快取
    if mock_data is None and use_cache:
        cache = _load_cache()
        cached_entry = cache.get(symbol)
        if cached_entry and isinstance(cached_entry, dict):
            cached_date_str = cached_entry.get("cached_at")
            if cached_date_str:
                try:
                    c_date = datetime.date.fromisoformat(cached_date_str)
                    if (datetime.date.today() - c_date).days <= CACHE_TTL_DAYS:
                        return cached_entry.get("data", {})
                except Exception:
                    pass

    data = mock_data
    if data is None:
        try:
            from fetchers import fetch_info
            data = fetch_info(symbol)
        except Exception:
            data = {}
    if data is None or (mock_data is None and not data):
        try:
            import yfinance as yf
            yf_sym = normalize_ticker_for_yf(symbol)
            if yf_sym:
                ticker = yf.Ticker(yf_sym)
                data = ticker.info or {}
            else:
                data = {}
        except Exception:
            data = {}

    roe = data.get("returnOnEquity")
    dte = data.get("debtToEquity")
    op_margin = data.get("operatingMargins")

    fcf = data.get("freeCashflow")
    ocf = data.get("operatingCashflow")
    net_inc = data.get("netIncomeToCommon") or data.get("netIncome")
    payout = data.get("payoutRatio")

    pe = data.get("trailingPE") or data.get("forwardPE")
    pb = data.get("priceToBook")
    div_yield = data.get("dividendYield")

    # 推估 FCF 覆蓋率 (若有股利支付與 FCF)
    fcf_coverage = None
    if fcf is not None and net_inc is not None and payout is not None and payout > 0:
        est_div_paid = net_inc * payout
        if est_div_paid > 0:
            fcf_coverage = fcf / est_div_paid

    ocf_quality = None
    if ocf is not None and net_inc is not None and net_inc != 0:
        ocf_quality = ocf / net_inc

    div_score = calculate_div_score(fcf_coverage, payout, ocf_quality)
    net_score = calculate_net_score(roe, dte, op_margin)
    val_score = calculate_val_score(pe, pb, div_yield)
    fric_score = calculate_fric_score(symbol)

    result = {
        "symbol": symbol,
        "roe": round(roe * 100.0, 2) if roe is not None else None,
        "debt_to_equity": round(dte, 2) if dte is not None else None,
        "operating_margin": round(op_margin * 100.0, 2) if op_margin is not None else None,
        "payout_ratio": round(payout * 100.0, 2) if payout is not None else None,
        "fcf_coverage": round(fcf_coverage, 2) if fcf_coverage is not None else None,
        "pe": round(pe, 2) if pe is not None else None,
        "pb": round(pb, 2) if pb is not None else None,
        "yield_pct": round(div_yield * 100.0, 2) if div_yield is not None else None,
        "scores": {
            "netScore": net_score,
            "divScore": div_score,
            "valScore": val_score,
            "fricScore": fric_score,
        },
    }

    # 寫入快取 (僅在非 mock 且有有效數據時)
    if mock_data is None and use_cache and data:
        cache = _load_cache()
        cache[symbol] = {
            "cached_at": datetime.date.today().isoformat(),
            "data": result,
        }
        _save_cache(cache)

    return result
