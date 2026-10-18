"""全市場台股 ETF 清單抓取與過濾模組 (TWSE ETF List Scraper)。

連線台灣證券交易所（TWSE）官方 OpenAPI (t187ap47_L)，支援本機快取與多維度過濾。
"""

import json
import os
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

TWSE_FUND_LIST_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap47_L"
DEFAULT_CACHE_FILE = Path.home() / ".cache" / "investment_tracker" / "tw_etf_list.json"


def fetch_twse_etf_list(
    use_cache: bool = True,
    cache_path: Optional[Path] = None,
    timeout: int = 10,
    mock_data: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """取得台股全市場 ETF 清單（包含代號、簡稱、全名、類型、經理公司與追蹤指數）。"""
    if mock_data is not None:
        return _normalize_twse_data(mock_data)

    target_cache = cache_path or DEFAULT_CACHE_FILE

    # 1. 檢查快取（24 小時內有效）
    if use_cache and target_cache.exists():
        try:
            mtime = datetime.fromtimestamp(target_cache.stat().st_mtime)
            if datetime.now() - mtime < timedelta(hours=24):
                with open(target_cache, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                    if isinstance(cached, list) and len(cached) > 0:
                        return cached
        except (OSError, json.JSONDecodeError):
            pass

    # 2. 請求 TWSE 官方端點
    req = urllib.request.Request(
        TWSE_FUND_LIST_URL,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw_data = json.loads(resp.read().decode("utf-8"))

    normalized = _normalize_twse_data(raw_data)

    # 3. 寫入快取
    if use_cache and normalized:
        try:
            target_cache.parent.mkdir(parents=True, exist_ok=True)
            with open(target_cache, "w", encoding="utf-8") as f:
                json.dump(normalized, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    return normalized


def _normalize_twse_data(raw_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """將 TWSE 原始欄位標準化為內部統一鍵值。"""
    normalized = []
    for item in raw_list:
        code = str(item.get("基金代號", "")).strip()
        name = str(item.get("基金簡稱", "")).strip()
        full_name = str(item.get("基金中文名稱", "")).strip()
        cat = str(item.get("基金類型", "")).strip()
        manager = str(item.get("經理公司董事長", "") or item.get("經理公司", "") or "").strip()
        benchmark = str(item.get("標的指數/追蹤指數名稱", "")).strip()

        if not code or not name:
            continue

        normalized.append({
            "ticker": code,
            "name": name,
            "full_name": full_name,
            "category": cat,
            "manager": manager,
            "benchmark": benchmark,
        })
    return normalized


def filter_etfs(
    etf_list: List[Dict[str, Any]],
    keyword: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """依據關鍵字（代號、名稱、類型）過濾 ETF 清單。"""
    result = etf_list
    if keyword:
        kw = keyword.strip().lower()
        variants = [kw]
        if "高息" in kw:
            variants.append(kw.replace("高息", "高股息"))
        elif "高股息" in kw:
            variants.append(kw.replace("高股息", "高息"))

        result = [
            e for e in result
            if any(
                v in e["ticker"].lower()
                or v in e["name"].lower()
                or v in e["full_name"].lower()
                or v in e["category"].lower()
                or v in e["benchmark"].lower()
                for v in variants
            )
        ]

    if limit is not None and limit > 0:
        result = result[:limit]

    return result


def format_etf_list_ascii(etf_list: List[Dict[str, Any]], keyword: Optional[str] = None) -> str:
    """產出命令列 ASCII 表格排版。"""
    lines = []
    lines.append("=" * 78)
    filter_desc = f"（篩選：{keyword}）" if keyword else ""
    lines.append(f"📋 全市場台股 ETF 清單 {filter_desc} ｜ 共 {len(etf_list)} 檔")
    lines.append("-" * 78)
    lines.append(f"{'代號':<8} {'簡稱':<16} {'類型':<26} {'追蹤指數'}")
    lines.append("-" * 78)

    for item in etf_list:
        ticker = item["ticker"]
        name = item["name"][:14]
        cat = item["category"][:24]
        bench = item["benchmark"][:24] if item["benchmark"] != "不適用" else "-"
        lines.append(f"{ticker:<8} {name:<16} {cat:<26} {bench}")

    lines.append("=" * 78)
    return "\n".join(lines)
