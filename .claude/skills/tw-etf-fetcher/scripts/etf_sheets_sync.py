#!/usr/bin/env python3
"""全市場 ETF 成分股與摘要 Google Sheets 雲端同步模組 (ETF Sheets Sync)。

職責：
1. 遍歷 models/*/cards/ 下的所有標的，解析 ticker.yml 與 constituents.jsonl。
2. 匯總輸出兩大標準資料集：
   - ETF_Constituents: 全市場 ETF 扁平化成分股清單（依 tw-etf-architecture.md 規格）
   - ETF_Summary: 全市場 ETF 基本資料與前三大持倉精華摘要
3. 輸出本機 CSV 報告，並透過 gsheets CLI 將數據同步回填至雲端試算表。
4. 外幣市場（港股、美股、日股）：`--market HK|US|JP --pool-json <pool.json>`，把 etf_pool 產出的 pool.json 轉成與台股同名同序的兩張表，
   寫入該市場自己的 Sheet；只用 GCP_SA_KEY 上傳，寫入前一律先過 Core 拒絕與國別後綴掃描。
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# 預設 SSOT 試算表 ID（Project_財商工程/All_Market/全市場_ETF成分股資料庫）
DEFAULT_SHEET_ID = os.environ.get(
    "ETF_CONSTITUENTS_SHEET_ID",
    "1GIhbRyL-h96ACVjlSSW9YUFMiAItg_SP9Wi0o3WwG70",
)

# 外幣市場的外圍試算表（2026-10-26 建立，服務帳號為編輯者）；寫入前一律先過 guard_sheet_id
MARKET_SHEET_IDS = {
    "HK": "1ND1gcxm-fvkx723V-X72QUuwrJvKobCz_etZpUzWrOI",
    "US": "1qfMn6hbPD4qFmlCAm0fC2zTfEtm9uVjdZYL4YDUrmY4",
    "JP": "1XtSRy14KdLMv75g9ShAL6jWpa9XmoUpiSY4Srvuycxc",
}
# 外幣市場的兩張表與台股同名同序；ETF_Summary 多兩欄：coverage（持股完整度）與 holdings_asof（持股日期）。
# last_model_update 在外幣市場是建立日期（模型卡片的日期），持股日期只放 holdings_asof，來源沒有就寫「無」
FOREIGN_SUMMARY_FIELDS = [
    "etf_id", "etf_name", "current_price", "exchange", "category", "benchmark", "constituent_count",
    "top1_holding", "top2_holding", "top3_holding", "weighted_roe", "net_score", "div_score", "val_score",
    "fric_score", "last_model_update", "coverage", "holdings_asof",
]
CONSTITUENT_FIELDS = ["etf_id", "etf_name", "constituent_ticker", "constituent_name", "weight_pct", "shares", "update_date"]
COVERAGE_LABELS = {"full": "完整", "partial": "前幾大", "fallback": "備援"}

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from etf_list_scraper import fetch_twse_etf_list
from etf_holdings_scraper import fetch_etf_holdings
import etf_market

_PATROL_SCRIPTS = Path(__file__).resolve().parents[2] / "portfolio-patrol" / "scripts"
if str(_PATROL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_PATROL_SCRIPTS))
from patrol_cards import load_yaml_simple  # 卡片 YAML 讀取的唯一實作
from etf_sheets_io import (  # noqa: E402,F401  寫出層已拆到 etf_sheets_io，這裡轉出維持舊的引用路徑
    find_gsheets_bin,
    sync_to_google_sheets,
    sync_via_google_api,
    write_csv,
)

def fetch_live_etf_price(ticker: str) -> Optional[float]:
    """自 Yahoo Finance 輕量端點獲取最新收盤/即時市價；抓不到回傳 None，不用任何寫死的備援價。"""
    suffixes = [".TW", ".TWO"]
    for s in suffixes:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}{s}?interval=1d&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                data = json.loads(resp.read().decode())
                meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
                p = meta.get("regularMarketPrice")
                if p:
                    return float(p)
        except Exception:
            continue
    return None


def load_all_etf_models(models_dir: Path) -> List[Dict[str, Any]]:
    """掃描 models 目錄下所有具備 cards/ 的標的資料。"""
    models: List[Dict[str, Any]] = []
    if not models_dir.exists():
        return models

    for model_path in sorted(models_dir.iterdir()):
        if not model_path.is_dir():
            continue

        cards_dir = model_path / "cards"
        ticker_file = cards_dir / "ticker.yml"
        constituents_file = cards_dir / "constituents.jsonl"

        if not ticker_file.exists():
            continue

        ticker_info = load_yaml_simple(ticker_file)
        category = str(ticker_info.get("category", "ETF")).strip().upper()
        # 僅載入 ETF 標的模型，嚴格排除 STOCK（如 1216, 1919, 2356 等個股模型）
        if category != "ETF":
            continue

        ticker_code = model_path.name
        ticker_name = str(ticker_info.get("title", ticker_code)).replace("&amp;", "&")

        constituents: List[Dict[str, Any]] = []
        if constituents_file.exists():
            for line in constituents_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        constituents.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        # 排序權重高者在前
        def _get_w(x: Dict[str, Any]) -> float:
            w = x.get("weight_pct")
            if w is None:
                raw_w = float(x.get("weight", 0.0))
                return raw_w * 100 if raw_w < 1.0 else raw_w
            return float(w)

        constituents.sort(key=_get_w, reverse=True)

        models.append({
            "ticker": ticker_code,
            "title": ticker_name,
            "full_name": ticker_info.get("full_name", ""),
            "currency": ticker_info.get("currency", "TWD"),
            "exchange": ticker_info.get("exchange", "TWSE"),
            "category": ticker_info.get("category", "ETF"),
            "manager": ticker_info.get("manager", ""),
            "benchmark": ticker_info.get("benchmark", ""),
            "last_model_update": ticker_info.get("last_model_update") or "無",
            "constituents": constituents,
        })

    return models


def load_all_market_etfs(
    models_dir: Path,
    include_market_pool: bool = True,
    delay: float = 0.1,
    holdings_fetcher: Optional[Callable[[str], Dict[str, Any]]] = None,
    twse_list_fetcher: Optional[Callable[[], List[Dict[str, Any]]]] = None,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> List[Dict[str, Any]]:
    """聚合全市場 ETF 資料：包含 models/ 既有核心模型與證交所+MoneyDJ之全市場資料池。"""
    # 1. 先讀取 models/ 既有核心模型
    models = load_all_etf_models(models_dir)
    existing_tickers = {m["ticker"].upper() for m in models}

    # 2. 若不包含資料池，直接回傳既有 models
    if not include_market_pool:
        return models

    # 3. 讀取證交所全市場 ETF 清單
    fetch_list_fn = twse_list_fetcher or fetch_twse_etf_list
    fetch_holdings_fn = holdings_fetcher or fetch_etf_holdings

    try:
        twse_list = fetch_list_fn()
    except Exception as e:
        print(f"⚠️ 獲取證交所全市場 ETF 清單失敗，僅回傳既有 models: {e}", file=sys.stderr)
        return models

    pool_candidates = [
        item for item in twse_list
        if str(item.get("ticker", "")).strip().upper() and str(item.get("ticker", "")).strip().upper() not in existing_tickers
    ]

    total_pool = len(pool_candidates)

    for idx, item in enumerate(pool_candidates, 1):
        code = str(item.get("ticker", "")).strip().upper()
        name = str(item.get("name", code)).replace("&amp;", "&")
        full_name = str(item.get("full_name", name)).replace("&amp;", "&")
        manager = str(item.get("manager", ""))
        benchmark = str(item.get("benchmark", ""))
        category = str(item.get("category", "ETF"))

        if progress_callback:
            progress_callback(code, idx, total_pool)

        try:
            h_data = fetch_holdings_fn(code)
        except Exception:
            h_data = {}

        raw_cons = h_data.get("constituents", [])

        constituents: List[Dict[str, Any]] = []
        for c in raw_cons:
            sym = c.get("symbol") or c.get("ticker") or ""
            w = c.get("weight_pct")
            if w is None:
                raw_w = float(c.get("weight", 0.0))
                w = raw_w * 100 if raw_w < 1.0 else raw_w
            w_float = float(w)
            constituents.append({
                "ticker": sym,
                "name": c.get("name", ""),
                "weight_pct": w_float,
                "shares": c.get("shares", 0),
            })

        # 排序權重高者在前
        constituents.sort(key=lambda x: x["weight_pct"], reverse=True)

        models.append({
            "ticker": code,
            "title": name,
            "full_name": full_name,
            "currency": "TWD",
            "exchange": "TWSE",
            "category": "ETF",
            "manager": manager,
            "benchmark": benchmark,
            "last_model_update": "無",  # 候選 ETF 沒有模型卡片，建立日期寫無；持股日期不進全市場表
            "constituents": constituents,
        })

        if delay > 0 and idx < total_pool:
            time.sleep(delay)

    # 依代號排序全市場清單
    models.sort(key=lambda x: x["ticker"])
    return models


def clean_constituent_ticker(ticker: str) -> str:
    """純化成分股代號，剝除 .TW, .TWO, .US, .HK, .JP, .TF 等國別網域名稱後綴，防範 Google Drive 安全機制誤判釣魚。"""
    if not ticker:
        return ""
    t = str(ticker).strip()
    t = re.sub(r"^(TPE:|TWO:|HKG:)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\.(TW|TWO|US|HK|JP|TF|TX)$", "", t, flags=re.IGNORECASE)
    return t.strip()


def generate_flattened_constituents(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """產生符合架構規範的扁平化成分股清單。
    
    欄位：etf_id | etf_name | constituent_ticker | constituent_name | weight_pct | shares | update_date
    """
    rows: List[Dict[str, Any]] = []
    for m in models:
        etf_id = clean_constituent_ticker(m["ticker"])
        etf_name = m["title"]
        update_date = m["last_model_update"]

        for c in m["constituents"]:
            raw_ticker = c.get("ticker") or c.get("symbol") or c.get("code") or ""
            ticker_val = clean_constituent_ticker(raw_ticker)
            weight_val = c.get("weight_pct")
            if weight_val is None:
                raw_w = float(c.get("weight", 0.0))
                weight_val = raw_w * 100 if raw_w < 1.0 else raw_w
            weight_val = float(weight_val)

            name_val = re.sub(r"\.(TW|TWO|US|HK|JP|TF|TX)\b", "", c.get("name", ""), flags=re.IGNORECASE)

            rows.append({
                "etf_id": etf_id,
                "etf_name": etf_name,
                "constituent_ticker": ticker_val,
                "constituent_name": name_val,
                "weight_pct": f"{weight_val:.2f}",
                "shares": c.get("shares", ""),
                "update_date": update_date,
            })

    return rows



def _load_aggregate_func() -> Optional[Any]:
    """載入基本面穿透評分函式（fundamental-analyzer）；匯入失敗回傳 None。"""
    fund_dir = REPO_ROOT / ".claude" / "skills" / "fundamental-analyzer" / "scripts"
    if fund_dir.exists() and str(fund_dir) not in sys.path:
        sys.path.insert(0, str(fund_dir))
    try:
        from lookthrough_fundamentals import aggregate_etf_fundamentals
    except ImportError:
        return None
    return aggregate_etf_fundamentals


def generate_summary_rows(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """產生全市場 ETF 摘要清單（含基本面穿透評分）。"""
    aggregate_func = _load_aggregate_func()

    # 批次並行抓取現價（大幅縮短 240+ 檔標的之抓價耗時）
    tickers = [m["ticker"] for m in models]
    price_map: Dict[str, Optional[float]] = {}
    try:
        with ThreadPoolExecutor(max_workers=10) as executor:
            fetched_prices = list(executor.map(fetch_live_etf_price, tickers))
            for t, p in zip(tickers, fetched_prices):
                price_map[t] = p
    except Exception:
        for t in tickers:
            price_map[t] = fetch_live_etf_price(t)

    rows: List[Dict[str, Any]] = []
    for m in models:
        ticker = m["ticker"]
        constituents = m["constituents"]
        top1 = constituents[0] if len(constituents) > 0 else {}
        top2 = constituents[1] if len(constituents) > 1 else {}
        top3 = constituents[2] if len(constituents) > 2 else {}

        def format_top(c: Dict[str, Any]) -> str:
            if not c:
                return "-"
            w = c.get('weight_pct')
            if w is None:
                raw_w = float(c.get('weight', 0.0))
                w = raw_w * 100 if raw_w < 1.0 else raw_w
            name = c.get('name', '')
            name = re.sub(r"\.(TW|TWO|US|HK|JP|TF|TX)\b", "", name, flags=re.IGNORECASE)
            return f"{name} ({float(w):.2f}%)"

        w_roe = "-"
        score_str = {k: "-" for k in ("netScore", "divScore", "valScore", "fricScore")}

        # 只收穿透計算成功的評分；失敗或 fallback 一律寫 "-"，不補預設分
        if aggregate_func:
            try:
                res = aggregate_func(ticker, top_n=10, repo_root=REPO_ROOT)
                if res.get("status") == "success":
                    sc = res.get("scores", {})
                    if res.get("weighted_roe") is not None:
                        w_roe = f"{res.get('weighted_roe')}%"
                    for k in score_str:
                        if sc.get(k) is not None:
                            score_str[k] = f"{float(sc[k]):.1f}"
            except Exception:
                pass

        price_val = price_map.get(ticker)
        price_str = f"{price_val:.2f}" if price_val is not None else "-"

        rows.append({
            "etf_id": ticker,
            "etf_name": m["title"],
            "current_price": price_str,
            "exchange": m["exchange"],
            "category": m["category"],
            "benchmark": m["benchmark"],
            "constituent_count": len(constituents),
            "top1_holding": format_top(top1),
            "top2_holding": format_top(top2),
            "top3_holding": format_top(top3),
            "weighted_roe": w_roe,
            "net_score": score_str["netScore"],
            "div_score": score_str["divScore"],
            "val_score": score_str["valScore"],
            "fric_score": score_str["fricScore"],
            "last_model_update": m["last_model_update"],
        })

    return rows


def run_sync_pipeline(
    models_dir: Path,
    output_dir: Path,
    sheet_id: str,
    export_only: bool = False,
    dry_run: bool = False,
    include_market_pool: bool = True,
    delay: float = 0.1,
    holdings_fetcher: Optional[Callable[[str], Dict[str, Any]]] = None,
    twse_list_fetcher: Optional[Callable[[], List[Dict[str, Any]]]] = None,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
    gate: Optional[Callable[[int, int], Tuple[bool, List[str]]]] = None,
) -> Dict[str, Any]:
    """執行全套同步管線流程。gate 收到 (ETF 數, 成分股列數)，回傳 (是否通過, 未通過原因)；未通過時不上傳雲端。"""
    models = load_all_market_etfs(
        models_dir=models_dir,
        include_market_pool=include_market_pool,
        delay=delay,
        holdings_fetcher=holdings_fetcher,
        twse_list_fetcher=twse_list_fetcher,
        progress_callback=progress_callback,
    )
    if not models:
        return {"status": "error", "message": f"在 {models_dir} 未發現任何 ETF 模型。"}

    constituents_rows = generate_flattened_constituents(models)
    summary_rows = generate_summary_rows(models)

    summary_fields = [
        "etf_id",
        "etf_name",
        "current_price",
        "exchange",
        "category",
        "benchmark",
        "constituent_count",
        "top1_holding",
        "top2_holding",
        "top3_holding",
        "weighted_roe",
        "net_score",
        "div_score",
        "val_score",
        "fric_score",
        "last_model_update",
    ]

    constituents_fields = [
        "etf_id",
        "etf_name",
        "constituent_ticker",
        "constituent_name",
        "weight_pct",
        "shares",
        "update_date",
    ]

    summary_csv = output_dir / "etf_summary.csv"
    constituents_csv = output_dir / "etf_constituents.csv"

    write_csv(summary_rows, summary_fields, summary_csv)
    write_csv(constituents_rows, constituents_fields, constituents_csv)

    result = {
        "status": "success",
        "etf_count": len(models),
        "constituents_count": len(constituents_rows),
        "summary_csv": str(summary_csv),
        "constituents_csv": str(constituents_csv),
        "sheet_id": sheet_id,
        "synced": False,
    }

    # 閘門必須在上傳前判定：未通過時 Sheet 保持上次的好資料，不被覆寫
    if gate is not None:
        gate_ok, gate_reasons = gate(len(models), len(constituents_rows))
        if not gate_ok:
            result.update(status="error", gate_reasons=gate_reasons, message="；".join(gate_reasons))
            return result

    if export_only or dry_run:
        result["message"] = f"已導出本機 CSV（ETF 數：{len(models)}，成分股數：{len(constituents_rows)}），未上傳雲端。"
        return result

    success, msg = sync_to_google_sheets(sheet_id, summary_csv, constituents_csv)
    result["synced"] = success
    result["message"] = msg
    if not success:
        result["status"] = "error"

    return result


def _clean_name(name: str) -> str:
    """名稱去掉國別後綴，與台股表相同；代號不在這裡處理，留給寫入前的後綴掃描攔截。"""
    return re.sub(r"\.(TW|TWO|US|HK|JP|TF|TX)\b", "", str(name), flags=re.IGNORECASE).strip()


def _etf_title(models_dir: Path, code: str) -> str:
    """ETF 名稱取 models 卡片的標題；沒有卡片就寫 "-"，不從外部猜名稱。"""
    card = models_dir / code / "cards" / "ticker.yml"
    if card.exists():
        title = str(load_yaml_simple(card).get("title", "")).replace("&amp;", "&").strip()
        if title:
            return title
    return "-"


def _foreign_live_fields(etf: str, aggregate_func: Optional[Any]) -> Dict[str, str]:
    """外幣市場的現價與評分，與台股表同一來源與算法；拿不到就寫 "-"，不用快照價，也不用 fallback 的預設分。"""
    out = dict(current_price="-", weighted_roe="-", net_score="-", div_score="-", val_score="-", fric_score="-")
    price = fetch_live_etf_price(etf)
    if price is not None:
        out["current_price"] = f"{price:.2f}"
    if aggregate_func is None:
        return out
    try:
        res = aggregate_func(etf, top_n=10, repo_root=REPO_ROOT)
    except Exception:
        return out
    if res.get("status") != "success":
        return out
    if res.get("weighted_roe") is not None:
        out["weighted_roe"] = f"{res['weighted_roe']}%"
    sc = res.get("scores", {})
    out.update(net_score=f"{sc['netScore']:.1f}", div_score=f"{sc['divScore']:.1f}",
               val_score=f"{sc['valScore']:.1f}", fric_score=f"{sc['fricScore']:.1f}")
    return out


def market_tables(payload: Dict[str, Any], models_dir: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """pool.json（外幣市場）→ ETF_Summary 與 ETF_Constituents 兩張表的列。代號沿用 pool.json 的純代號；現價與評分同台股表的來源，拿不到的欄位寫 "-"，不估值補。"""
    names = {s["code"]: s["name"] for s in payload["stocks"]}
    holds: Dict[str, List[Dict[str, Any]]] = {}
    for h in payload["holdings"]:
        holds.setdefault(h["etf"], []).append(h)
    summaries = {s["etf"]: s for s in payload["summaries"]}

    aggregate_func = _load_aggregate_func()
    summary_rows: List[Dict[str, Any]] = []
    constituent_rows: List[Dict[str, Any]] = []
    for etf in sorted(summaries):
        s = summaries[etf]
        hs = sorted(holds.get(etf, []), key=lambda h: h["weightPct"], reverse=True)
        title = _etf_title(models_dir, etf)
        holdings_asof = s.get("holdings_asof") or "無"
        for h in hs:
            constituent_rows.append(dict(
                etf_id=etf, etf_name=title, constituent_ticker=h["code"],
                constituent_name=_clean_name(names.get(h["code"], h["code"])), weight_pct=f"{h['weightPct']:.2f}",
                shares="" if h.get("shares") is None else h["shares"], update_date=holdings_asof,
            ))
        tops = [f"{_clean_name(names.get(h['code'], h['code']))} ({h['weightPct']:.2f}%)" for h in hs[:3]]
        tops += ["-"] * (3 - len(tops))
        live = _foreign_live_fields(etf, aggregate_func)
        summary_rows.append(dict(
            etf_id=etf, etf_name=title, current_price=live["current_price"], exchange="-", category="ETF",
            benchmark="-", constituent_count=len(hs), top1_holding=tops[0], top2_holding=tops[1],
            top3_holding=tops[2], weighted_roe=live["weighted_roe"], net_score=live["net_score"],
            div_score=live["div_score"], val_score=live["val_score"], fric_score=live["fric_score"],
            last_model_update=s.get("model_date") or "無", coverage=COVERAGE_LABELS.get(s.get("coverage"), "-"),
            holdings_asof=holdings_asof,
        ))
    return summary_rows, constituent_rows


def run_market_sheets_pipeline(
    pool_json: Path,
    output_dir: Path,
    sheet_id: str,
    models_dir: Path,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """外幣市場（港股、美股、日股）：讀 pool.json，寫入該市場自己的 Sheet。
    順序：Core 拒絕 → 市場與 schema 檢查 → 列數檢查 → 國別後綴檢查（先於任何寫檔）→ 寫 CSV → 上傳（只用 GCP_SA_KEY，不退回 gsheets CLI）。"""
    try:
        etf_market.guard_sheet_id(sheet_id)
    except etf_market.CoreWriteRefused as e:
        return dict(status="error", message=str(e), synced=False)
    payload = json.loads(pool_json.read_text(encoding="utf-8"))
    market = str(payload.get("market", ""))
    if payload.get("schema_version") != etf_market.SCHEMA_VERSION or market not in MARKET_SHEET_IDS:
        return dict(status="error", message=f"pool.json 不是外幣市場的 schema（market={market!r}），不寫入", synced=False)
    if sheet_id != MARKET_SHEET_IDS[market]:
        return dict(status="error", message=f"{market} 只能寫入 {MARKET_SHEET_IDS[market]}，拒絕寫入 {sheet_id}", synced=False)

    summary_rows, constituent_rows = market_tables(payload, models_dir)
    if not summary_rows or not constituent_rows:
        return dict(status="error", message="pool.json 沒有持股列，不寫入 Sheet", synced=False)
    leaked = etf_market.find_forbidden_suffix("\n".join(str(v) for r in summary_rows + constituent_rows for v in r.values()))
    if leaked:
        return dict(status="error", message=f"輸出含國別後綴，未寫入任何檔案：{leaked[:5]}", synced=False)

    summary_csv = write_csv(summary_rows, FOREIGN_SUMMARY_FIELDS, output_dir / f"{market.lower()}_etf_summary.csv")
    constituents_csv = write_csv(constituent_rows, CONSTITUENT_FIELDS, output_dir / f"{market.lower()}_etf_constituents.csv")
    result = dict(status="success", market=market, etf_count=len(summary_rows), constituents_count=len(constituent_rows),
                  summary_csv=str(summary_csv), constituents_csv=str(constituents_csv), sheet_id=sheet_id, synced=False)
    if dry_run:
        result["message"] = f"已導出本機 CSV（ETF 數：{len(summary_rows)}，持股數：{len(constituent_rows)}），未上傳雲端。"
        return result
    if not (os.environ.get("GCP_SA_KEY") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")):
        result.update(status="error", message="未提供 GCP_SA_KEY，無法寫入外幣市場 Sheet（CSV 已導出）")
        return result
    ok, msg = sync_via_google_api(sheet_id, summary_csv, constituents_csv, summary_width=len(FOREIGN_SUMMARY_FIELDS))
    result.update(synced=ok, message=msg)
    if not ok:
        result["status"] = "error"
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="全市場 ETF 成分股與摘要 Google Sheets 雲端同步模組")
    parser.add_argument("--models-dir", default=str(REPO_ROOT / "models"), help="models 目錄路徑")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "reports"), help="CSV 匯出目錄路徑")
    parser.add_argument("--market", default="TW", choices=["TW", "HK", "US", "JP"],
                        help="TW：全市場台股表（排程流程）；HK、US、JP：讀 --pool-json 寫入該市場的 Sheet")
    parser.add_argument("--pool-json", help="外幣市場的 pool.json（由 etf_pool.py 產出）")
    parser.add_argument("--sheet-id", default=None, help="目標 Google Sheet ID（預設依市場決定）")
    parser.add_argument("--export-only", action="store_true", help="僅產出本機 CSV，不上傳雲端")
    parser.add_argument("--dry-run", action="store_true", help="模擬執行，不變更雲端試算表")

    args = parser.parse_args(argv)

    if args.market != "TW":
        if not args.pool_json:
            print("❌ 外幣市場需要 --pool-json（etf_pool.py 產出的 pool.json）", file=sys.stderr)
            return 2
        res = run_market_sheets_pipeline(
            pool_json=Path(args.pool_json),
            output_dir=Path(args.output_dir),
            sheet_id=args.sheet_id or MARKET_SHEET_IDS[args.market],
            models_dir=Path(args.models_dir),
            dry_run=args.dry_run or args.export_only,
        )
        if res["status"] == "success":
            print(f"✅ {args.market} 處理完成：{res['etf_count']} 檔 ETF，共 {res['constituents_count']} 筆持股")
            print(f"   📁 摘要 CSV：{res['summary_csv']}")
            print(f"   📁 持股 CSV：{res['constituents_csv']}")
            print(f"   ℹ️ {res.get('message', '')}")
            return 0
        print(f"❌ 同步失敗：{res.get('message', '未知錯誤')}", file=sys.stderr)
        return 1

    print("🚀 啟動全市場 ETF 成分股資料管線同步...")
    res = run_sync_pipeline(
        models_dir=Path(args.models_dir),
        output_dir=Path(args.output_dir),
        sheet_id=args.sheet_id or DEFAULT_SHEET_ID,
        export_only=args.export_only,
        dry_run=args.dry_run,
    )

    if res["status"] == "success":
        print(f"✅ 處理完成：涵蓋 {res['etf_count']} 檔 ETF，共 {res['constituents_count']} 筆底層成分股紀錄。")
        print(f"   📁 摘要 CSV：{res['summary_csv']}")
        print(f"   📁 成分股 CSV：{res['constituents_csv']}")
        if res.get("synced"):
            print(f"   ☁️ 雲端同步成功：試算表 ID [{res['sheet_id']}]")
            print(f"      - 分頁：ETF_Summary 與 ETF_Constituents")
        else:
            print(f"   ℹ️ {res.get('message', '')}")
        return 0
    else:
        print(f"❌ 同步失敗：{res.get('message', '未知錯誤')}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
