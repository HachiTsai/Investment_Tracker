#!/usr/bin/env python3
"""ETF 穿透基本面聚合器 (Look-through Fundamental Aggregator)。

職責：
讀取 models/<etf_id>/cards/constituents.jsonl 之成分股與權重，
對底層持倉計算財務指標與評分，並依歸一化權重執行加權聚合。
"""

import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fundamental_calculator import calculate_stock_fundamentals, has_netscore_input

ETF_CACHE_FILE = Path.home() / ".cache" / "investment_tracker" / "etf_fundamentals.json"
CACHE_TTL_DAYS = 7
CACHE_SCHEMA = 2  # 快取格式版本，與 fundamental_calculator 同步遞增（v3）
COVERAGE_MIN_PCT = 60.0  # 有 netScore 輸入的權重占比低於此值＝資料不足：不判定、不快取


def _load_etf_cache() -> Dict[str, Any]:
    if not ETF_CACHE_FILE.exists():
        return {}
    try:
        with open(ETF_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_etf_cache(cache: Dict[str, Any]) -> None:
    try:
        ETF_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ETF_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_etf_constituents(etf_id: str, repo_root: Path) -> List[Dict[str, Any]]:
    """讀取指定 ETF 的成分股清單。"""
    cards_file = repo_root / "models" / etf_id / "cards" / "constituents.jsonl"
    if not cards_file.exists():
        return []

    constituents: List[Dict[str, Any]] = []
    for line in cards_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                item = json.loads(line)
                ticker = item.get("ticker") or item.get("code")
                if ticker and str(ticker).isdigit() and etf_id == "00882":
                    ticker = f"{ticker}.HK"
                weight_pct = item.get("weight_pct")
                if weight_pct is None and "weight" in item:
                    w = float(item["weight"])
                    weight_pct = w * 100.0 if w <= 1.0 else w
                item["ticker"] = ticker
                item["weight_pct"] = float(weight_pct or 0.0)
                constituents.append(item)
            except (json.JSONDecodeError, ValueError):
                continue

    constituents.sort(key=lambda x: float(x.get("weight_pct", 0.0)), reverse=True)
    return constituents


def aggregate_etf_fundamentals(
    etf_id: str,
    top_n: int = 10,
    repo_root: Optional[Path] = None,
    mock_constituents: Optional[List[Dict[str, Any]]] = None,
    mock_stock_fundamentals: Optional[Dict[str, Dict[str, Any]]] = None,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """計算 ETF 穿透加權基本面評分。"""
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[4]

    # 檢查快取（債券 ETF 不走快取：本地解析毫秒級，也避免讀到舊版固定預設分）
    if mock_constituents is None and mock_stock_fundamentals is None and use_cache and "B" not in etf_id.upper():
        cache = _load_etf_cache()
        cached_entry = cache.get(etf_id)
        if cached_entry and isinstance(cached_entry, dict) and cached_entry.get("schema") == CACHE_SCHEMA:
            c_date_str = cached_entry.get("cached_at")
            if c_date_str:
                try:
                    c_date = datetime.date.fromisoformat(c_date_str)
                    if (datetime.date.today() - c_date).days <= CACHE_TTL_DAYS:
                        return cached_entry.get("data", {})
                except Exception:
                    pass

    constituents = mock_constituents or load_etf_constituents(etf_id, repo_root)
    is_bond = "B" in etf_id.upper()
    if is_bond:
        # 債券 ETF：不套股票財報分數，改做持股結構與信用風險代理（bond_lookthrough，純本地字串解析，全部持股也只需毫秒）。
        # scores 留空：不再寫固定預設分，下游（試算表同步、巡檢）遇空一律寫 "-"。
        from bond_lookthrough import analyze_bond_etf

        return {
            "etf_id": etf_id,
            "status": "bond",
            "is_bond": True,
            "covered_holdings_count": len(constituents),
            "total_weight_covered_pct": round(sum(float(c.get("weight_pct", 0.0)) for c in constituents), 2),
            "weighted_roe": None,
            "scores": {},
            "holdings_breakdown": [],
            "coverage_pct": None,
            "coverage_sufficient": False,
            "bond": analyze_bond_etf(constituents),
        }
    if not constituents:
        return {
            "etf_id": etf_id,
            "status": "fallback",
            "is_bond": False,
            "covered_holdings_count": 0,
            "total_weight_covered_pct": 0.0,
            "weighted_roe": None,
            "scores": {"netScore": None, "divScore": None, "valScore": None, "fricScore": None},  # 無成分股資料：不回填固定預設分
            "holdings_breakdown": [],
            "coverage_pct": None,
            "coverage_sufficient": False,
        }

    # 取前 N 大持股
    selected = constituents[:top_n]
    total_raw_weight = sum(float(c.get("weight_pct", 0.0)) for c in selected)
    if total_raw_weight <= 0:
        total_raw_weight = 1.0

    holdings_breakdown = []
    weighted_net = 0.0
    weighted_div = 0.0
    weighted_val = 0.0
    weighted_fric = 0.0
    weighted_roe = 0.0
    has_roe_count = 0
    covered_w = 0.0  # 有 netScore 輸入的持股權重
    net_norm_w = 0.0  # 有 netScore 輸入的持股（歸一化後）權重合計，用於 netScore 重新歸一化

    for c in selected:
        ticker = c.get("ticker", "")
        name = c.get("name", ticker)
        raw_w = float(c.get("weight_pct", 0.0))
        norm_w = raw_w / total_raw_weight

        # 取得個股財報指標
        mock_data = mock_stock_fundamentals.get(ticker) if mock_stock_fundamentals else None
        fund = calculate_stock_fundamentals(ticker, mock_data=mock_data, use_cache=use_cache)

        scores = fund["scores"]
        weighted_div += scores["divScore"] * norm_w
        weighted_val += scores["valScore"] * norm_w
        weighted_fric += scores["fricScore"] * norm_w

        # netScore 只計入有財報輸入的持股，權重在這些持股之間重新歸一化；缺值持股不以 50 分拉低整體分數
        if has_netscore_input(fund) and scores.get("netScore") is not None:
            weighted_net += scores["netScore"] * norm_w
            net_norm_w += norm_w
            covered_w += raw_w

        if fund.get("roe") is not None:
            weighted_roe += fund["roe"] * norm_w
            has_roe_count += 1

        holdings_breakdown.append({
            "ticker": ticker,
            "name": name,
            "weight_pct": raw_w,
            "norm_weight_pct": round(norm_w * 100.0, 2),
            "roe": fund.get("roe"),
            "pe": fund.get("pe"),
            "scores": scores,
        })

    coverage_pct = round(covered_w / total_raw_weight * 100.0, 1)
    result = {
        "etf_id": etf_id,
        "status": "success",
        "is_bond": "B" in etf_id.upper(),
        "covered_holdings_count": len(selected),
        "total_weight_covered_pct": round(total_raw_weight, 2),
        "weighted_roe": round(weighted_roe, 2) if has_roe_count > 0 else None,
        "scores": {
            # 沒有任何持股有財報輸入時 netScore 留空（None），不回填預設分
            "netScore": round(weighted_net / net_norm_w, 1) if net_norm_w > 0 else None,
            "divScore": round(weighted_div, 1),
            "valScore": round(weighted_val, 1),
            "fricScore": round(weighted_fric, 1),
        },
        "holdings_breakdown": holdings_breakdown,
        "coverage_pct": coverage_pct,
        "coverage_sufficient": coverage_pct >= COVERAGE_MIN_PCT,
    }

    if mock_constituents is None and mock_stock_fundamentals is None and use_cache and result["coverage_sufficient"]:
        cache = _load_etf_cache()
        cache[etf_id] = {
            "schema": CACHE_SCHEMA,
            "cached_at": datetime.date.today().isoformat(),
            "data": result,
        }
        _save_etf_cache(cache)

    return result
