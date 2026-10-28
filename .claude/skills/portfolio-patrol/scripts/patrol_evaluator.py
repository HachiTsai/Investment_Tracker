"""投資組合評估與狀態互鎖計算模組 (Patrol Evaluator)。

負責宏觀數據整合、即時行情求值、BLS 狀態互鎖邏輯判斷與全標的巡檢執行。
"""

import datetime
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from patrol_cards import check_watchdog, discover_tickers, load_cards

DEFAULT_WORKERS = 8  # 抓價並行數；全標的 42 檔實測 8 條約 1 分鐘，16、32 條沒有更快也沒被限流
DIVIDEND_FETCH_TIMEOUT_SEC = 120  # 配息抓取實測單檔可超過 60 秒；原 15 秒逾時會把配息誤判為 0
DIVIDEND_FETCH_ATTEMPTS = 2  # 逾時或失敗重試一次
# 高息陷阱與互鎖門檻：單一來源為 references/interlock_rules.json（見架構文件 v5）
RULES = json.loads((Path(__file__).resolve().parents[1] / "references" / "interlock_rules.json").read_text(encoding="utf-8"))
_TRAP = RULES["yield_trap"]
_AGG = RULES["aggressive"]
_OVER = RULES["overvalued"]
_VEL = RULES["velocity"]


def _fetch_both(fetch_script: Path, ticker: str) -> Optional[Dict[str, Any]]:
    """呼叫 price-dividend-fetcher 取得現價與近 12 個月配息；逾時或失敗重試一次，兩次皆失敗回 None。"""
    for _ in range(DIVIDEND_FETCH_ATTEMPTS):
        try:
            out = subprocess.run(
                [sys.executable, str(fetch_script), "both", ticker],
                capture_output=True,
                text=True,
                timeout=DIVIDEND_FETCH_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            continue
        if out.returncode == 0:
            try:
                return json.loads(out.stdout)
            except ValueError:
                continue
    return None


TAIPEI_TZ = datetime.timezone(datetime.timedelta(hours=8))  # 台灣無夏令時間，固定 +08:00


def previous_trading_day(day: datetime.date) -> datetime.date:
    """前一個交易日。以週一至週五近似；國定假日未納入，遇假日會使確認鏈中斷，屬保守方向。"""
    prev = day - datetime.timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= datetime.timedelta(days=1)
    return prev


def trap_confirmed(prev_state: Dict[str, Any], ticker: str, today: datetime.date) -> bool:
    """前一個交易日的同一標的也觸發高息陷阱條件，本次才確認（升級為陷阱警戒）。"""
    rec = prev_state.get(ticker) or {}
    return bool(rec.get("trap")) and rec.get("run_date") == previous_trading_day(today).isoformat()


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
    """抓取標的即時行情與配息（調用 fetch.py both，帶安全降級）。"""
    ticker_info = cards_data.get("ticker", {})
    calib = ticker_info.get("calibration", {})
    fail_safe = ticker_info.get("fail_safe", {})

    fallback_price = fail_safe.get("fallback_price", 15.20 if ticker == "00882" else 10.00)
    # 不寫死配息與稅率：卡片沒有 fallback_annual_dividend 時降級為 0（不輸出達成率）；稅率未設定時以毛額計（1.0）
    fallback_div = fail_safe.get("fallback_annual_dividend", 0.0)
    tax_retention = calib.get("tax_retention_rate", 1.0)

    price = fallback_price
    default_price = fallback_price
    annual_div = fallback_div
    source_notes = "基準校準值"
    is_live = False  # 現價是否取自即時行情；False 時輸出會標明「非即時」

    # 嘗試調用 price-dividend-fetcher（呼叫 both 以同時取得現價與近 12 個月 TTM 配息）
    fetch_script = repo_root / ".claude" / "skills" / "price-dividend-fetcher" / "scripts" / "fetch.py"
    if fetch_script.exists():
        try:
            res = _fetch_both(fetch_script, ticker)
            if res:
                p_info = res.get("price") if isinstance(res.get("price"), dict) else res
                if p_info and p_info.get("price"):
                    price = float(p_info["price"])
                    source_notes = f"live-fetcher ({p_info.get('source', 'web')})"
                    is_live = True
                d_info = res.get("dividends") or {}
                if "ttm_total" in d_info:
                    annual_div = float(d_info["ttm_total"] or 0.0)
        except Exception:
            pass

        # 降級階梯：若 both 失敗/逾時或未能取得現價，改以快速純價格模式 (price) 單獨獲取
        if price is None or price == default_price:
            try:
                out_p = subprocess.run(
                    [sys.executable, str(fetch_script), "price", ticker],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if out_p.returncode == 0:
                    res_p = json.loads(out_p.stdout)
                    item_p = res_p[0] if isinstance(res_p, list) and res_p else res_p
                    if isinstance(item_p, dict) and item_p.get("price"):
                        price = float(item_p["price"])
                        source_notes = f"live-price-fallback ({item_p.get('source', 'web')})"
                        is_live = True
            except Exception:
                pass

    if not is_live:
        # 抓不到即時價時，價格與殖利率都是卡片或預設基準值，必須讓讀者看得出來
        source_notes = "⚠️ 非即時：行情連線失敗，使用卡片或預設基準值"

    # 取得技術面波段輪廓（供成長型 ETF 姿態判定）
    swing_info = None
    pdf_dir = repo_root / ".claude" / "skills" / "price-dividend-fetcher" / "scripts"
    if pdf_dir.exists():
        if str(pdf_dir) not in sys.path:
            sys.path.insert(0, str(pdf_dir))
        try:
            import swing
            swing_info = swing.stock_profile(ticker)
        except Exception:
            pass

    scores: Dict[str, float] = {}  # 穿透評分取不到時留空，不補預設分

    coverage_ok = False  # 聚合失敗或覆蓋不足時為 False，評估端不判定評分類姿態

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
                coverage_ok = bool(agg.get("coverage_sufficient"))
        except Exception:
            pass

    # 南向資金僅適用於 00882 / 港陸相關標的，其餘標的為 0.0
    southbound = 1250.0 if ticker == "00882" else 0.0

    return {
        "price": price,
        "annual_dividend": annual_div,
        "tax_retention": tax_retention,
        "source_notes": source_notes,
        "price_is_live": is_live,
        "scores": scores,
        "coverage_ok": coverage_ok,
        "southbound_2d_net": southbound,
        "swing": swing_info,
    }


def fetch_stock_live_data(ticker: str, cards_data: Dict[str, Any], repo_root: Path) -> Dict[str, Any]:
    """個股卡片（category: STOCK）求值：現價與近 12 個月配息取自 price-dividend-fetcher，評分取自 fundamental-analyzer。"""
    info = cards_data.get("ticker", {})
    symbol = info.get("symbol") or ticker
    baseline = (info.get("dividend") or {}).get("annual_dps_baseline")
    live: Dict[str, Any] = {"price": 0.0, "annual_dividend": baseline or 0.0, "source_notes": "⚠️ 非即時：個股卡片基準值",
                            "price_is_live": False}

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
                live["price_is_live"] = True
            ttm = (res.get("dividends") or res).get("ttm_total")
            if ttm:
                live["annual_dividend"] = float(ttm)
        except Exception:
            pass

    scores: Dict[str, float] = {}  # 取不到評分時留空，不補預設分
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


_GROWTH_POSTURES = {
    "UPTREND": ("🔵 趨勢續抱", "收盤在 20、60 日線之上且 MACD 柱為正", "維持核心部位持有，定額常態累積", 5),
    "NEUTRAL": ("🔵 常態配置", "指標處於常態震盪區間", "維持例行性資產配置與定期定額", 5),
    "OVERHEATED": ("🟠 乖離防禦", "RSI≥70 或觸及布林上緣", "短線乖離過大，暫停單筆追高，維持既有定額", 4),
    "OVERSOLD_WATCH": ("🟢 回檔加碼", "RSI≤30 或觸及布林下緣，且未明顯跌離半年線", "長線成長標的回檔超跌，可評估額外加碼", 3),
    "DOWNTREND": ("⚪ 定額微笑", "收盤在 20、60 日線之下且 MACD 柱為負", "順勢方向偏弱，維持常態定期定額，不單筆大額接刀", 5),
}


def _stock_posture(swing: Optional[Dict[str, Any]]):
    """個股狀態：取波段分類；抓不到日線時標示資料不足。回傳 (key, label, name, action, priority)。"""
    if not swing or swing.get("state") not in _STOCK_POSTURES:
        return "NO_DATA", "⚪ 資料不足", "缺日線資料，暫不判定", "待下次巡檢取得日線後再評估", 5
    label, name, action, priority = _STOCK_POSTURES[swing["state"]]
    return f"SWING_{swing['state']}", label, name, action, priority


def _growth_posture(swing: Optional[Dict[str, Any]]):
    """資本成長型 ETF 狀態：映射長線配置姿態。回傳 (key, label, name, action, priority)。"""
    if not swing or swing.get("state") not in _GROWTH_POSTURES:
        return "NO_DATA", "⚪ 資料不足", "缺日線資料，暫不判定", "待下次巡檢取得日線後再評估", 5
    label, name, action, priority = _GROWTH_POSTURES[swing["state"]]
    return f"GROWTH_{swing['state']}", label, name, action, priority


def evaluate_ticker_posture(
    cards_data: Dict[str, Any],
    live_data: Dict[str, Any],
) -> Dict[str, Any]:
    """評估單一標的之戰術姿態（Interlock BLS）與目標達成率（零隱私外洩）。"""
    ticker_info = cards_data.get("ticker", {})
    title = ticker_info.get("title", cards_data.get("ticker_id", "Unknown"))
    currency = ticker_info.get("currency", "TWD")
    strategy_type = ticker_info.get("strategy_type")
    price = live_data["price"]
    annual_div = live_data.get("annual_dividend") or 0.0
    tax_retention = live_data.get("tax_retention", 1.0)
    scores = live_data.get("scores", {})
    southbound_flow = live_data.get("southbound_2d_net", 0.0)

    is_stock = ticker_info.get("category") == "STOCK"
    # 判斷是否為資本利得/成長型或無配息標的：
    # 1. 明確標示 strategy_type 為 CAPITAL_GROWTH
    # 2. 或非個股、非收息型／債券型且 annual_div <= 0（收息型配息為零代表配息資料未取得，見 NO_DIVIDEND_DATA）
    is_growth = (strategy_type == "CAPITAL_GROWTH") or (
        not is_stock and annual_div <= 0 and strategy_type not in ("DIVIDEND_INCOME", "BOND_DEFENSE")
    )
    swing = live_data.get("swing")

    # 優先級風控互鎖邏輯 (BLS)
    posture_key = "STEADY_REINVEST"
    posture_label = "🔵 穩健複利"
    posture_name = "穩健複利策略 (Steady Reinvest)"
    valve_action = "維持例行性半年配息再投入，按部就班累積雪球"
    priority = 5

    yield_rate = 0.0
    yield_pct = None

    if is_stock:
        # 個股：不套高息陷阱互鎖，改用波段狀態＋階段性含息報酬率
        posture_key, posture_label, posture_name, valve_action, priority = _stock_posture(swing)
        if annual_div > 0 and price > 0:
            yield_rate = annual_div / price
            yield_pct = round(yield_rate * 100.0, 2)
    elif is_growth:
        # 資本利得/成長型或無配息標的：改用成長型專屬配置狀態，不套用高息陷阱與殖利率過熱門檻
        posture_key, posture_label, posture_name, valve_action, priority = _growth_posture(swing)
        yield_rate = 0.0
        yield_pct = None
    elif price <= 0:
        posture_key = "NO_DATA"
        posture_label = "⚪ 資料不足"
        posture_name = "缺報價資料，暫不判定"
        valve_action = "待下次巡檢取得報價後再評估"
    elif annual_div <= 0 and strategy_type in ("DIVIDEND_INCOME", "BOND_DEFENSE"):
        # 收息型或債券型配息為零：配息資料未取得（逾時或來源失敗），標示無資料，不歸為成長型
        posture_key = "NO_DIVIDEND_DATA"
        posture_label = "⚪ 無資料"
        posture_name = "配息資料未取得，暫不判定 (No Dividend Data)"
        valve_action = "配息資料未取得，待下次巡檢取得配息後重新評估"
        priority = 4
    else:
        # 收息型 (DIVIDEND_INCOME) 與債券型 (BOND_DEFENSE) 且 annual_div > 0
        yield_rate = annual_div / price if price > 0 else 0.0
        yield_pct = round(yield_rate * 100.0, 2)
        net_score = scores.get("netScore", 50)
        div_score = scores.get("divScore", 50)

        if strategy_type == "BOND_DEFENSE":
            # 債券防禦型：脫離股票高股息絕對門檻，依債券合理息收區間判定
            if yield_rate >= 0.048:
                posture_key = "BOND_ACCUMULATE"
                posture_label = "🟢 積極佈建"
                posture_name = "債券高息防禦進攻 (Bond Yield Accumulate)"
                valve_action = "債券殖利率具防禦吸引力，可提高股息再投入或加碼配比"
                priority = 3
            elif yield_rate <= 0.035:
                posture_key = "BOND_OVERBOUGHT"
                posture_label = "🟡 防禦觀望"
                posture_name = "債券估值過熱 (Bond Overbought / Hold)"
                valve_action = "債券殖利率偏低，暫停單筆加碼，維持資產配置持有"
                priority = 4
            else:
                posture_key = "STEADY_REINVEST"
                posture_label = "🔵 穩健配置"
                posture_name = "債券常態防禦配置 (Bond Steady Defense)"
                valve_action = "維持例行性債券息收再投入，發揮投資組合防禦穩定器功能"
                priority = 5
        else:
            # 股票高股息收息型 (DIVIDEND_INCOME)
            # 評分類判定須有足夠的成分股財報覆蓋（門檻見 lookthrough_fundamentals.COVERAGE_MIN_PCT），覆蓋不足時不判定
            data_ok = bool(live_data.get("coverage_ok"))
            trap_cond = yield_rate >= _TRAP["yield_min"] and (net_score < _TRAP["net_score_below"] or div_score < _TRAP["div_score_below"])
            # 優先級 1：高息陷阱斷路 (net/div 評分破底)；未經次一交易日確認的首日觸發先列為觀察
            confirmed = live_data.get("trap_confirmed")  # None＝未啟用兩日確認，沿用單日判定
            if trap_cond and data_ok and confirmed is not False:
                posture_key = "TRAP_ALERT"
                posture_label = "🚨 陷阱警戒"
                posture_name = "高息陷阱斷路保護 (Yield Trap Trip)"
                valve_action = _TRAP["valve_action"]
                priority = 1
            # 優先級 2：流速過快斷路 (僅港陸標的)
            elif southbound_flow < _VEL["southbound_2d_net_below"]:
                posture_key = "VELOCITY_PAUSE"
                posture_label = "⏸️ 流速警戒"
                posture_name = "資金流速過快警報 (Velocity Trip)"
                valve_action = "暫緩大額市價單買進，等待資金流速放緩再行佈置"
                priority = 2
            # 陷阱條件首次成立（尚未經次一交易日確認）：列為觀察，不升級警報
            elif trap_cond and data_ok:
                posture_key = "TRAP_WATCH"
                posture_label = "🟠 陷阱觀察"
                posture_name = "高息陷阱條件首次成立，待次一交易日確認 (Trap Watch)"
                valve_action = "暫不升級為陷阱警戒；次一交易日仍觸發即列為陷阱警戒"
                priority = 4
            # 高息區間（≥ 8%）的判定依賴評分：覆蓋不足時不判定陷阱，也不落入預設穩健姿態
            elif yield_rate >= _TRAP["yield_min"] and not data_ok:
                posture_key = "DATA_INSUFFICIENT"
                posture_label = "⚪ 資料不足"
                posture_name = "成分股財報覆蓋不足，暫不判定 (Insufficient Coverage)"
                valve_action = "成分股財報覆蓋率不足，暫不判定高息陷阱，待資料恢復後重新評估"
                priority = 4
            # 優先級 3：積極進攻
            elif data_ok and yield_rate >= _AGG["yield_min"] and net_score >= _AGG["net_score_min"] and div_score >= _AGG["div_score_min"]:
                posture_key = "AGGRESSIVE_ACCUMULATE"
                posture_label = "🟢 積極進攻"
                posture_name = "積極增持配置 (Aggressive Accumulate)"
                valve_action = "股息 100% 立即再投入，若有閒置資金啟動額外加碼，最大化滾動張數"
                priority = 3
            # 優先級 4：過熱防禦
            elif yield_rate <= _OVER["yield_max"]:
                posture_key = "OVERVALUED_HOLD"
                posture_label = "🟡 防禦觀望"
                posture_name = "估值偏高觀望 (Overvalued / Hold)"
                valve_action = "停止加碼買進，維持既有部位持有，股息可部分保留現金儲備"
                priority = 4
            else:
                posture_key = "STEADY_REINVEST"
                posture_label = "🔵 穩健複利"
                posture_name = "穩健複利策略 (Steady Reinvest)"
                valve_action = "維持例行性半年配息再投入，按部就班累積雪球"
                priority = 5

    # 個股卡片：以「每一張（lot_shares）對 50 萬目標的貢獻度」取代持股達成率（不輸出個人持股）
    contribution_pct = None
    lot_shares = (ticker_info.get("contribution") or {}).get("lot_shares")
    fx_to_twd = 1.0 if currency == "TWD" else live_data.get("fx_to_twd")
    if ticker_info.get("category") == "STOCK" and lot_shares and annual_div and fx_to_twd:
        contribution_pct = round(lot_shares * annual_div * fx_to_twd * tax_retention / 500000.0 * 100.0, 2)

    # 50 萬被動股利目標達成率計算（僅收息型且卡片明確指定 base_shares 時才計算，不虛構假設張數）
    progress_pct = 0.0 if is_stock else None
    sp_title = "50萬被動股利目標"
    loops = cards_data.get("loops", [])
    if loops and not is_growth and not is_stock:
        first_loop = loops[0]
        params = first_loop.get("parameters", {})
        sp = params.get("setpoint_sp", 500000.0)
        snowball = first_loop.get("snowball_simulator", {})
        base_shares = snowball.get("base_shares")
        if base_shares and annual_div > 0 and sp > 0:
            pv = base_shares * annual_div * tax_retention
            progress_pct = round((pv / sp) * 100.0, 1)
        sp_title = first_loop.get("title", sp_title)

    resolved_strategy = strategy_type or ("STOCK" if is_stock else ("CAPITAL_GROWTH" if is_growth else "DIVIDEND_INCOME"))

    return {
        "ticker": cards_data.get("ticker_id"),
        "title": title,
        "currency": currency,
        "price": price,
        "annual_dividend": annual_div,
        "yield_rate": yield_rate,
        "yield_pct": yield_pct,
        "posture_key": posture_key,
        "posture_label": posture_label,
        "posture_name": posture_name,
        "priority": priority,
        "valve_action": valve_action,
        "goal_progress_pct": progress_pct,
        "goal_title": sp_title,
        "scores": scores,
        "category": ticker_info.get("category", "ETF"),
        "strategy_type": resolved_strategy,
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

    line = " ｜ ".join(parts) if parts else "宏觀指標正常運作中"
    if "基準快照" in json.dumps(macro, ensure_ascii=False):
        line += " ｜ ⚠️ 非即時：宏觀來源連線失敗，使用基準快照"
    return line


def run_portfolio_patrol(
    repo_root: Path,
    filter_tickers: Optional[List[str]] = None,
    custom_models_dir: Optional[Path] = None,
    mock_macro: Optional[Dict[str, Any]] = None,
    workers: int = DEFAULT_WORKERS,
    filter_tier: Optional[str] = "core",
    prev_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """執行投資組合全標的巡檢核心主程序。抓價階段以 workers 條執行緒並行，評估與警報維持原順序。
    prev_state 為前一個交易日的陷阱狀態（由排程傳入）；未提供時沿用單日判定。"""
    models_root = custom_models_dir if custom_models_dir else repo_root / "models"
    tickers = discover_tickers(models_root, filter_tickers, filter_tier=filter_tier)

    if (filter_tier or "core").lower() == "core" and len(tickers) > 60:
        print(f"⚠️ [Patrol Safeguard] 核心團隊標的數量達 {len(tickers)} 檔（超過安全防護門檻 60 檔），建議檢視標的並將次要標的調整為 pool。", file=sys.stderr)

    macro_data = mock_macro if mock_macro is not None else fetch_macro_telemetry(repo_root)

    patrol_results = []
    alerts = []
    has_abnormal_posture = False
    has_watchdog_warning = False

    def gather(ticker: str):
        cards = load_cards(models_root, ticker)
        watchdog = check_watchdog(cards)
        if cards.get("ticker", {}).get("category") == "STOCK":
            live_data = fetch_stock_live_data(ticker, cards, repo_root)
            ccy = cards["ticker"].get("currency", "TWD")
            fx_row = macro_data.get("fx", {}).get(f"{ccy}_TWD") or macro_data.get("fx", {}).get(f"{ccy}TWD") or {}
            live_data.setdefault("fx_to_twd", fx_row.get("rate") or fx_row.get("price"))
        else:
            live_data = fetch_ticker_live_data(ticker, cards, repo_root)
        return cards, watchdog, live_data

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        gathered = list(pool.map(gather, tickers))

    today_tpe = datetime.datetime.now(TAIPEI_TZ).date()
    trap_state: Dict[str, Any] = {}
    for ticker, (cards, watchdog, live_data) in zip(tickers, gathered):
        if prev_state is not None:
            live_data["trap_confirmed"] = trap_confirmed(prev_state, ticker, today_tpe)
        evaluation = evaluate_ticker_posture(cards, live_data)
        trap_state[ticker] = {
            "run_date": today_tpe.isoformat(),
            "trap": evaluation["posture_key"] in ("TRAP_ALERT", "TRAP_WATCH"),
        }

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
        "trap_state": trap_state,
    }
