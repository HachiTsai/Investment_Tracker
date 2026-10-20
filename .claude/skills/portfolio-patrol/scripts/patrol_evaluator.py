"""投資組合評估與狀態互鎖計算模組 (Patrol Evaluator)。

負責宏觀數據整合、即時行情求值、BLS 狀態互鎖邏輯判斷與全標的巡檢執行。
"""

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from patrol_cards import check_watchdog, discover_tickers, load_cards


def fetch_macro_telemetry(repo_root: Path) -> Dict[str, Any]:
    """獲取宏觀與前饋數據（呼叫 hkdata.py macro 或優雅降級）。"""
    hkdata_script = repo_root / ".claude" / "skills" / "hk-market-data" / "scripts" / "hkdata.py"

    if hkdata_script.exists():
        try:
            proc = subprocess.run(
                [sys.executable, str(hkdata_script), "macro"],
                capture_output=True,
                text=True,
                timeout=25,
            )
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                if "indicators" in data:
                    return data["indicators"]
        except Exception:
            pass

    # 備援預設基準值（當無網路或離線測試時使用）
    return {
        "lpr": {"1Y": 3.0, "5Y": 3.5, "unit": "%", "date": "2026-09-20", "source": "中國人民銀行/東方財富 (基準快照)"},
        "chinabond_yield": {"10Y": 1.6480, "30Y": 2.0600, "unit": "%", "date": "2026-10-16", "source": "中債收益率 (基準快照)"},
        "fx": {
            "USDCNH": {"price": 6.6853, "change_pct": 0.05, "source": "Yahoo Finance (基準快照)"},
            "HKDTWD": {"price": 4.1379, "change_pct": -0.02, "source": "Yahoo Finance (基準快照)"},
        },
        "shipping_freight": {
            "scfi": {"index_name": "SCFI综合指数", "latest_index": 3679.58, "change": 15.47, "date": "2026-10-16", "source": "上海航運交易所 (基準快照)"},
            "coastal_coal_freight": {"index_name": "沿海煤炭运价指数", "latest_index": 758.08, "change": -2.31, "date": "2026-10-16", "source": "上海航運交易所 (基準快照)"},
        },
    }


def fetch_ticker_live_data(ticker: str, cards_data: Dict[str, Any], repo_root: Path) -> Dict[str, Any]:
    """抓取標的即時行情與多空分數（帶安全降級）。"""
    ticker_info = cards_data.get("ticker", {})
    calib = ticker_info.get("calibration", {})
    fail_safe = ticker_info.get("fail_safe", {})

    default_price = 15.20 if ticker == "00882" else 10.00
    fallback_div = fail_safe.get("fallback_annual_dividend", 0.86)
    tax_retention = calib.get("tax_retention_rate", 0.9923)

    price = default_price
    source_notes = "基準校準值"

    # 嘗試調用 price-dividend-fetcher
    fetch_script = repo_root / ".claude" / "skills" / "price-dividend-fetcher" / "scripts" / "fetch.py"
    if fetch_script.exists():
        try:
            out = subprocess.run(
                [sys.executable, str(fetch_script), "price", ticker],
                capture_output=True,
                text=True,
                timeout=6,
            )
            if out.returncode == 0:
                res = json.loads(out.stdout)
                if isinstance(res, list) and res and res[0].get("price"):
                    price = float(res[0]["price"])
                    source_notes = f"live-fetcher ({res[0].get('source', 'web')})"
                elif isinstance(res, dict) and res.get("price"):
                    price = float(res["price"])
                    source_notes = f"live-fetcher ({res.get('source', 'web')})"
        except Exception:
            pass

    scores = {
        "netScore": 75.0,
        "divScore": 70.0,
        "valScore": 75.0,
        "fricScore": 80.0,
    }

    # 動態穿透計算基本面評分
    fund_script_dir = repo_root / ".claude" / "skills" / "fundamental-analyzer" / "scripts"
    if fund_script_dir.exists():
        if str(fund_script_dir) not in sys.path:
            sys.path.insert(0, str(fund_script_dir))
        try:
            from lookthrough_fundamentals import aggregate_etf_fundamentals
            agg = aggregate_etf_fundamentals(ticker, top_n=10, repo_root=repo_root)
            if agg and "scores" in agg:
                scores = agg["scores"]
        except Exception:
            pass

    return {
        "price": price,
        "annual_dividend": fallback_div,
        "tax_retention": tax_retention,
        "source_notes": source_notes,
        "scores": scores,
        "southbound_2d_net": 1250.0,
    }


def fetch_stock_live_data(ticker: str, cards_data: Dict[str, Any], repo_root: Path) -> Dict[str, Any]:
    """個股卡片（category: STOCK）求值：現價與近 12 個月配息取自 price-dividend-fetcher，評分取自 fundamental-analyzer。"""
    info = cards_data.get("ticker", {})
    symbol = info.get("symbol") or ticker
    baseline = (info.get("dividend") or {}).get("annual_dps_baseline")
    live: Dict[str, Any] = {"price": 0.0, "annual_dividend": baseline or 0.0, "source_notes": "個股卡片基準值"}

    fetch_script = repo_root / ".claude" / "skills" / "price-dividend-fetcher" / "scripts" / "fetch.py"
    if fetch_script.exists():
        try:
            out = subprocess.run(
                [sys.executable, str(fetch_script), "both", symbol],
                capture_output=True, text=True, timeout=20,
            )
            res = json.loads(out.stdout) if out.returncode == 0 else {}
            price_info = res.get("price") if isinstance(res.get("price"), dict) else res
            if price_info.get("price"):
                live["price"] = float(price_info["price"])
                live["source_notes"] = f"live-fetcher ({price_info.get('source', 'web')})"
            ttm = (res.get("dividends") or res).get("ttm_total")
            if ttm:
                live["annual_dividend"] = float(ttm)
        except Exception:
            pass

    scores = {"netScore": 50.0, "divScore": 50.0, "valScore": 50.0, "fricScore": 50.0}
    fund_dir = repo_root / ".claude" / "skills" / "fundamental-analyzer" / "scripts"
    if fund_dir.exists():
        if str(fund_dir) not in sys.path:
            sys.path.insert(0, str(fund_dir))
        try:
            from fundamental_calculator import calculate_stock_fundamentals
            scores = calculate_stock_fundamentals(info.get("yf_symbol") or symbol).get("scores", scores)
        except Exception:
            pass
    live["swing"] = None
    pdf_dir = repo_root / ".claude" / "skills" / "price-dividend-fetcher" / "scripts"
    if pdf_dir.exists():
        if str(pdf_dir) not in sys.path:
            sys.path.insert(0, str(pdf_dir))
        try:
            import swing
            live["swing"] = swing.stock_profile(symbol)
        except Exception:
            pass
    live.update({"scores": scores, "tax_retention": info.get("contribution", {}).get("tax_retention_rate") or 1.0,
                 "southbound_2d_net": 0.0})
    return live


_STOCK_POSTURES = {
    "UPTREND": ("🔵 趨勢偏多", "收盤在 20、60 日線之上且 MACD 柱為正", "維持持有；停損價以 2×ATR 為參考，是否進出由 Hachi 決定", 5),
    "NEUTRAL": ("⚪ 未觸發條件", "指標未達任何波段條件", "無新動作，持續觀察", 5),
    "OVERHEATED": ("🟠 短線偏熱", "RSI≥70 或觸及布林上緣", "已持有者留意減碼條件，不追高", 3),
    "OVERSOLD_WATCH": ("🟢 超跌觀察", "RSI≤30 或觸及布林下緣，且未明顯跌離半年線", "可觀察反彈訊號，進場前先決定停損價", 3),
    "DOWNTREND": ("🔴 偏空迴避", "收盤在 20、60 日線之下且 MACD 柱為負", "順勢方向向下，暫不加碼", 4),
}


def _stock_posture(swing: Optional[Dict[str, Any]]):
    """個股狀態：取波段分類；抓不到日線時標示資料不足。回傳 (key, label, name, action, priority)。"""
    if not swing or swing.get("state") not in _STOCK_POSTURES:
        return "NO_DATA", "⚪ 資料不足", "缺日線資料，暫不判定", "待下次巡檢取得日線後再評估", 5
    label, name, action, priority = _STOCK_POSTURES[swing["state"]]
    return f"SWING_{swing['state']}", label, name, action, priority


def evaluate_ticker_posture(
    cards_data: Dict[str, Any],
    live_data: Dict[str, Any],
) -> Dict[str, Any]:
    """評估單一標的之戰術姿態（Interlock BLS）與目標達成率（零隱私外洩）。"""
    ticker_info = cards_data.get("ticker", {})
    title = ticker_info.get("title", cards_data.get("ticker_id", "Unknown"))
    currency = ticker_info.get("currency", "TWD")
    price = live_data["price"]
    annual_div = live_data["annual_dividend"]
    tax_retention = live_data["tax_retention"]
    scores = live_data.get("scores", {})
    southbound_flow = live_data.get("southbound_2d_net", 0.0)

    yield_rate = annual_div / price if price > 0 else 0.0

    net_score = scores.get("netScore", 50)
    div_score = scores.get("divScore", 50)

    # 優先級風控互鎖邏輯 (BLS)
    posture_key = "STEADY_REINVEST"
    posture_label = "🔵 穩健複利"
    posture_name = "預設穩健複利姿態 (Steady Reinvest)"
    valve_action = "維持例行性半年配息再投入，按部就班累積雪球"
    priority = 5

    is_stock = ticker_info.get("category") == "STOCK"
    swing = live_data.get("swing") if is_stock else None

    # 個股：不套高息陷阱互鎖（殖利率門檻是為 ETF 設計），改用波段狀態＋階段性含息報酬率
    if is_stock:
        posture_key, posture_label, posture_name, valve_action, priority = _stock_posture(swing)
    # 無報價或無配息資料：不判定估值姿態，避免殖利率 0% 被誤判為過熱
    elif price <= 0 or annual_div <= 0:
        posture_key = "NO_DATA"
        posture_label = "⚪ 資料不足"
        posture_name = "缺報價或配息資料，暫不判定"
        valve_action = "待下次巡檢取得報價與近 12 個月配息後再評估"
    # 優先級 1：高息陷阱斷路
    elif yield_rate >= 0.08 and (net_score < 50 or div_score < 40):
        posture_key = "TRAP_ALERT"
        posture_label = "🚨 陷阱警戒"
        posture_name = "高息陷阱斷路保護 (Yield Trap Trip)"
        valve_action = "強制關閉加碼閥門！股息暫留現金池，啟動持股專案審查"
        priority = 1
    # 優先級 2：流速過快斷路
    elif southbound_flow < -8000:
        posture_key = "VELOCITY_PAUSE"
        posture_label = "⏸️ 流速警戒"
        posture_name = "資金流速過快警報 (Velocity Trip)"
        valve_action = "暫緩大額市價單買進，等待資金流速放緩再行佈置"
        priority = 2
    # 優先級 3：積極進攻
    elif yield_rate >= 0.082 and net_score >= 70 and div_score >= 60:
        posture_key = "AGGRESSIVE_ACCUMULATE"
        posture_label = "🟢 積極進攻"
        posture_name = "積極進攻姿態 (Aggressive Accumulate)"
        valve_action = "股息 100% 立即再投入，若有閒置資金啟動額外加碼，最大化滾動張數"
        priority = 3
    # 優先級 4：過熱防禦
    elif yield_rate <= 0.048:
        posture_key = "OVERVALUED_HOLD"
        posture_label = "🟡 防禦觀望"
        posture_name = "估值過熱防禦姿態 (Overvalued / Hold)"
        valve_action = "停止加碼買進，維持既有部位持有，股息可部分保留現金儲備"
        priority = 4

    # 個股卡片：以「每一張（lot_shares）對 50 萬目標的貢獻度」取代持股達成率（不輸出個人持股）
    contribution_pct = None
    lot_shares = (ticker_info.get("contribution") or {}).get("lot_shares")
    fx_to_twd = 1.0 if currency == "TWD" else live_data.get("fx_to_twd")
    if ticker_info.get("category") == "STOCK" and lot_shares and annual_div and fx_to_twd:
        contribution_pct = round(lot_shares * annual_div * fx_to_twd * tax_retention / 500000.0 * 100.0, 2)

    # 50 萬被動股利目標達成率計算（比率計算，不輸出個人持股張數）
    progress_pct = 0.0
    sp_title = "50萬被動股利目標"
    loops = cards_data.get("loops", [])
    if loops:
        first_loop = loops[0]
        params = first_loop.get("parameters", {})
        sp = params.get("setpoint_sp", 500000.0)
        snowball = first_loop.get("snowball_simulator", {})
        base_shares = snowball.get("base_shares", 300000)
        pv = base_shares * annual_div * tax_retention
        if sp > 0:
            progress_pct = round((pv / sp) * 100.0, 1)
        sp_title = first_loop.get("title", sp_title)

    return {
        "ticker": cards_data.get("ticker_id"),
        "title": title,
        "currency": currency,
        "price": price,
        "annual_dividend": annual_div,
        "yield_rate": yield_rate,
        "yield_pct": round(yield_rate * 100.0, 2),
        "posture_key": posture_key,
        "posture_label": posture_label,
        "posture_name": posture_name,
        "priority": priority,
        "valve_action": valve_action,
        "goal_progress_pct": progress_pct,
        "goal_title": sp_title,
        "scores": scores,
        "category": ticker_info.get("category", "ETF"),
        "lot_contribution_pct": contribution_pct,
        "swing": swing,
    }


def _format_macro_feed(macro: Dict[str, Any]) -> str:
    """格式化宏觀前饋單行摘要。"""
    parts = []
    lpr = macro.get("lpr", {})
    lpr_1y = lpr.get("lpr_1y") or lpr.get("1Y")
    if lpr_1y is not None:
        parts.append(f"LPR 1Y: {lpr_1y}%")

    cb = macro.get("china_treasury_yield") or macro.get("chinabond_yield", {})
    y10 = cb.get("yield_10y") or cb.get("10Y")
    if y10 is not None:
        parts.append(f"中債10年: {y10}%")

    fx = macro.get("fx", {})
    usd_cnh = fx.get("USD_CNH") or fx.get("USDCNH") or {}
    usd_cnh_rate = usd_cnh.get("rate") or usd_cnh.get("price")
    if usd_cnh_rate is not None:
        parts.append(f"USD/CNH: {usd_cnh_rate}")

    shipping = macro.get("shipping_freight", {})
    scfi = shipping.get("scfi", {})
    scfi_val = scfi.get("current") or scfi.get("latest_index")
    if scfi_val is not None:
        chg = scfi.get("change")
        chg_str = f"({chg:+})" if chg is not None else ""
        parts.append(f"SCFI: {scfi_val} {chg_str}".strip())

    return " ｜ ".join(parts) if parts else "宏觀指標正常運作中"


def run_portfolio_patrol(
    repo_root: Path,
    filter_tickers: Optional[List[str]] = None,
    custom_models_dir: Optional[Path] = None,
    mock_macro: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """執行投資組合全標的巡檢核心主程序。"""
    models_root = custom_models_dir if custom_models_dir else repo_root / "models"
    tickers = discover_tickers(models_root, filter_tickers)

    macro_data = mock_macro if mock_macro is not None else fetch_macro_telemetry(repo_root)

    patrol_results = []
    alerts = []
    has_abnormal_posture = False
    has_watchdog_warning = False

    for ticker in tickers:
        cards = load_cards(models_root, ticker)
        watchdog = check_watchdog(cards)
        if cards.get("ticker", {}).get("category") == "STOCK":
            live_data = fetch_stock_live_data(ticker, cards, repo_root)
            ccy = cards["ticker"].get("currency", "TWD")
            fx_row = macro_data.get("fx", {}).get(f"{ccy}_TWD") or macro_data.get("fx", {}).get(f"{ccy}TWD") or {}
            live_data.setdefault("fx_to_twd", fx_row.get("rate") or fx_row.get("price"))
        else:
            live_data = fetch_ticker_live_data(ticker, cards, repo_root)
        evaluation = evaluate_ticker_posture(cards, live_data)

        evaluation["watchdog"] = watchdog

        if watchdog["is_stale"]:
            has_watchdog_warning = True
            alerts.append({
                "ticker": ticker,
                "type": "WATCHDOG_STALE",
                "message": f"{ticker} 資料心跳過期：{watchdog['label']}",
                "action": "檢查並更新成分股母表或情報資料庫",
            })

        if evaluation["priority"] in (1, 2):
            has_abnormal_posture = True
            alerts.append({
                "ticker": ticker,
                "type": evaluation["posture_key"],
                "message": f"{ticker} 觸發互鎖警報：{evaluation['posture_label']} ({evaluation['posture_name']})",
                "action": evaluation["valve_action"],
            })
        elif evaluation["priority"] in (3, 4):
            alerts.append({
                "ticker": ticker,
                "type": evaluation["posture_key"],
                "message": f"{ticker} 狀態調整：{evaluation['posture_label']} ({evaluation['posture_name']})",
                "action": evaluation["valve_action"],
            })

        patrol_results.append(evaluation)

    # 例外管理（MBE）摘要總結
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    today_date = datetime.date.today().isoformat()
    weekday_cn = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"][datetime.date.today().weekday()]

    if has_abnormal_posture:
        overall_posture = "🚨 發現異常跳脫 / 閥門警報觸發"
        decision_item = "；".join(f"【{a['ticker']}】{a['action']}" for a in alerts if a["type"] in ("TRAP_ALERT", "VELOCITY_PAUSE"))
    elif alerts:
        overall_posture = "🟡 投資組合配置微調"
        decision_item = "；".join(f"【{a['ticker']}】{a['action']}" for a in alerts)
    else:
        overall_posture = "🔵 全投資組合處於【穩健複利】狀態，例行性累積雪球"
        decision_item = "全投資組合無異常跳脫，維持例行性再投入與資產配置。"

    macro_feed_str = _format_macro_feed(macro_data)
    agent = os.environ.get("AGENT_ID") or ("Claude" if os.environ.get("CLAUDECODE") else "Antigravity")

    return {
        "timestamp": now_str,
        "date_str": f"{today_date}（{weekday_cn}）",
        "agent": agent,
        "overall_posture": overall_posture,
        "decision_item": decision_item,
        "macro_feed": macro_feed_str,
        "macro_data": macro_data,
        "fleet": patrol_results,
        "targets": patrol_results,
        "alerts": alerts,
        "is_steady": not has_abnormal_posture and not has_watchdog_warning,
    }
