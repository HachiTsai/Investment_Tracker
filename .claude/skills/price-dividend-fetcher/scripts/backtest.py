"""共用回測引擎：規則可插拔、成本模型、槓桿與逐倉清算、可做空、資金曲線與風險指標。只用標準函式庫，唯讀。

  python3 backtest.py NASDAQ:TQQQ --strategy trend --leverage 5          單一組合
  python3 backtest.py BINANCE:TQQQUSDT --strategy discipline --compare    幣安合約，比較 1／5／20 倍
  python3 backtest.py TPE:0050 --strategy oversold --range 10y

資料：股票走 swing.load_ohlcv（Yahoo，台股證交所補缺）；`BINANCE:<合約>` 走幣安 USDⓈ-M 合約公開 K 線與資金費率
（www.binance.com/fapi，不需帳號；api.binance.com、fapi.binance.com 在雲端沙盒回 HTTP 451，不採用）。

回測只代表過去，不代表未來；結果不是買賣指示。日線回測看不到盤中路徑，同一根 K 棒同時碰到停損與清算時一律先算清算（保守）。
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from swing import atr, bollinger, load_ohlcv, rsi, sma

# ---------------------------------------------------------------- 成本模型（單位：基點，1 bp = 0.01%）
# 數字是預設的保守假設，不是券商實際費率；可用 --fee-bps、--slip-bps 覆寫。
COSTS: Dict[str, Dict[str, float]] = {
    "TPE": dict(fee_bps=14.25, sell_tax_bps=30.0, slip_bps=5.0),     # 手續費 0.1425% 雙邊；證交稅 0.3%（ETF 0.1%，用 --sell-tax-bps 10）
    "US": dict(fee_bps=0.0, sell_tax_bps=0.0, slip_bps=5.0),         # 美股多數券商零佣金；SEC 規費極小不計
    "HKG": dict(fee_bps=3.0, sell_tax_bps=10.0, slip_bps=10.0),      # 佣金假設 0.03%；印花稅 0.1% 雙邊，簡化為買賣各 10 bp
    "TYO": dict(fee_bps=5.0, sell_tax_bps=0.0, slip_bps=5.0),
    "BINANCE": dict(fee_bps=5.0, sell_tax_bps=0.0, slip_bps=3.0),    # 合約吃單手續費約 0.05%；另計資金費率
}


def market_key(ticker: str) -> str:
    exch = ticker.split(":")[0] if ":" in ticker else "TPE"
    if exch in ("NASDAQ", "NYSE", "NYSEARCA", "NYSEAMERICAN"):
        return "US"
    return exch


# ---------------------------------------------------------------- 幣安合約資料層
BINANCE_FAPI = "https://www.binance.com/fapi/v1"
RANGE_DAYS = {"1y": 365, "2y": 730, "3y": 1095, "5y": 1826, "10y": 3652}


def _get_json(url: str):
    r = subprocess.run(["curl", "-sS", "-m", "40", "-w", "\n%{http_code}", url], capture_output=True, text=True, check=False)
    body, _, status = r.stdout.rpartition("\n")
    if r.returncode != 0 or status != "200":
        raise RuntimeError(f"幣安連線失敗 HTTP {status or r.returncode}（{url}）：{(body or r.stderr)[:120]}")
    return json.loads(body)


def parse_klines(rows: List[list]) -> List[Dict]:
    return [dict(ts=int(k[0]) // 1000, open=float(k[1]), high=float(k[2]), low=float(k[3]), close=float(k[4]),
                 volume=float(k[5]), adj=float(k[4])) for k in rows]


def load_binance(symbol: str, rng: str = "5y", interval: str = "1d", get=_get_json, now_ms: Optional[int] = None) -> List[Dict]:
    """幣安 USDⓈ-M 合約 K 線（分頁抓，每頁 1500 根）。最後一根若尚未收盤就丟掉。"""
    now_ms = now_ms or int(datetime.now(timezone.utc).timestamp() * 1000)
    start = now_ms - RANGE_DAYS.get(rng, 1826) * 86400_000
    out: List[list] = []
    while True:
        page = get(f"{BINANCE_FAPI}/klines?symbol={symbol}&interval={interval}&startTime={start}&limit=1500")
        if not page:
            break
        out += page
        if len(page) < 1500:
            break
        start = int(page[-1][0]) + 1
    if out and int(out[-1][6]) > now_ms:
        out = out[:-1]
    if not out:
        raise ValueError(f"幣安查無 K 線：{symbol}")
    return parse_klines(out)


def load_funding(symbol: str, start_ts: int, get=_get_json) -> Dict[int, float]:
    """資金費率歷史，彙總成「UTC 日（當日 00:00 秒數）→ 當日費率合計」。多單付正費率、空單收。"""
    out: Dict[int, float] = {}
    start = start_ts * 1000
    while True:
        page = get(f"{BINANCE_FAPI}/fundingRate?symbol={symbol}&startTime={start}&limit=1000")
        if not page:
            break
        for f in page:
            day = int(f["fundingTime"]) // 1000 // 86400 * 86400
            out[day] = out.get(day, 0.0) + float(f["fundingRate"])
        if len(page) < 1000:
            break
        start = int(page[-1]["fundingTime"]) + 1
    return out


def load_bars(ticker: str, rng: str = "5y") -> List[Dict]:
    if ticker.upper().startswith("BINANCE:"):
        return load_binance(ticker.split(":", 1)[1].upper(), rng)
    return load_ohlcv(ticker, rng)


# ---------------------------------------------------------------- 引擎
# 規則介面：
#   entry(i, ctx) -> "long" | "short" | None        第 i 根收盤時判斷，收盤價進場
#   exit(i, pos, ctx) -> Optional[str]             第 i 根收盤時判斷，回傳出場理由
#   stop(i, side, ctx) -> Optional[float]          進場當下的停損價（None 表示不設）
# ctx 是 prepare(bars) 算好的指標字典，另含 "close"。


def run(bars: List[Dict], entry: Callable, exit_: Callable, stop: Optional[Callable] = None, ctx: Optional[Dict] = None,
        leverage: float = 1.0, margin_pct: float = 100.0, capital: float = 10000.0, mm_rate: float = 0.005,
        costs: Optional[Dict[str, float]] = None, funding: Optional[Dict[int, float]] = None,
        cooldown_after_loss: int = 0, start: int = 1, drop_open: bool = False) -> Dict:
    """逐根 K 棒模擬。每筆用「目前權益 × margin_pct%」當逐倉保證金，名目 = 保證金 × 槓桿。

    - 清算：多單低點 ≤ 進場價 ×(1 − 1/槓桿 + 維持保證金率)；空單高點 ≥ 進場價 ×(1 + 1/槓桿 − 維持保證金率)，損失整筆保證金。
      槓桿 1 倍時不檢查清算（現貨）。
    - 停損：碰到停損價出場；跳空越過停損以開盤價成交，不假設剛好成交在停損價。
    - 成本：進出場各扣手續費＋滑價，賣出（多單出場、空單進場）另扣交易稅；資金費率按持有日累計。
    - drop_open：資料結束仍未出場的部位不列入（舊版超跌回測口徑）；否則以最後收盤價結算並標 "open"。
    """
    ctx = ctx if ctx is not None else {}
    ctx.setdefault("close", [b["close"] for b in bars])
    c = costs or dict(fee_bps=0.0, sell_tax_bps=0.0, slip_bps=0.0)
    side_cost = (c.get("fee_bps", 0) + c.get("slip_bps", 0)) / 1e4
    tax = c.get("sell_tax_bps", 0) / 1e4
    equity, peak, max_dd = capital, capital, 0.0
    curve: List[Dict] = [dict(ts=bars[start]["ts"] if bars else 0, equity=capital)] if bars else []
    trades: List[Dict] = []
    i, cool = start, 0
    while i < len(bars) - 1:
        if cool:
            cool -= 1; i += 1; continue
        side = entry(i, ctx)
        if side not in ("long", "short"):
            i += 1; continue
        sgn = 1 if side == "long" else -1
        e = bars[i]["close"]
        margin = equity * margin_pct / 100
        notional = margin * leverage
        sp = stop(i, side, ctx) if stop else None
        liq = None
        if leverage > 1:
            liq = e * (1 - 1 / leverage + mm_rate) if sgn > 0 else e * (1 + 1 / leverage - mm_rate)
        fund = 0.0
        j, px, why = i + 1, None, None
        while j < len(bars):
            b = bars[j]
            if funding:
                fund += funding.get(b["ts"] // 86400 * 86400, 0.0)
            if liq is not None and ((sgn > 0 and b["low"] <= liq) or (sgn < 0 and b["high"] >= liq)):
                why = "liquidated"; break
            if sp is not None and ((sgn > 0 and b["low"] <= sp) or (sgn < 0 and b["high"] >= sp)):
                px = min(sp, b["open"]) if sgn > 0 else max(sp, b["open"]); why = "stop"; break
            r = exit_(j, dict(side=side, entry_i=i, entry=e), ctx)
            if r:
                px, why = b["close"], r; break
            j += 1
        if why is None:
            if drop_open:
                break
            j, px, why = len(bars) - 1, bars[-1]["close"], "open"
        if why == "liquidated":
            pnl = -margin
            ret_px = (liq / e - 1) * sgn
        else:
            ret_px = (px / e - 1) * sgn
            cost = notional * side_cost * 2 + notional * tax
            pnl = max(notional * ret_px - cost - notional * fund * sgn, -margin) if leverage > 1 else notional * ret_px - cost - notional * fund * sgn
        equity += pnl
        trades.append(dict(entry_ts=bars[i]["ts"], exit_ts=bars[j]["ts"], side=side, entry=e, exit=px if px is not None else liq,
                           reason=why, bars=j - i, price_ret_pct=round(ret_px * 100, 2),
                           ret_on_margin_pct=round(pnl / margin * 100, 2) if margin else 0.0, pnl=round(pnl, 2)))
        curve.append(dict(ts=bars[j]["ts"], equity=round(equity, 2)))
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak > 0 else 1.0)
        if equity <= 0:
            break
        if pnl < 0 and cooldown_after_loss:
            cool = cooldown_after_loss
        i = j + 1
    return dict(trades=trades, curve=curve, final_equity=round(equity, 2), max_drawdown_pct=round(max_dd * 100, 1))


def metrics(res: Dict, capital: float, bars: List[Dict]) -> Dict:
    t = res["trades"]
    rets = [x["ret_on_margin_pct"] for x in t]
    streak = best = 0
    for x in t:
        streak = streak + 1 if x["pnl"] < 0 else 0
        best = max(best, streak)
    first, last = (bars[0].get("adj") or bars[0]["close"], bars[-1].get("adj") or bars[-1]["close"]) if bars else (None, None)
    hold = (last / first - 1) * 100 if bars else None  # 含息（還原價），策略本身用未還原收盤價、不含配息
    return dict(
        trades=len(t), win_rate_pct=round(sum(x["pnl"] > 0 for x in t) / len(t) * 100, 1) if t else None,
        liquidations=sum(x["reason"] == "liquidated" for x in t),
        stops=sum(x["reason"] == "stop" for x in t),
        avg_ret_on_margin_pct=round(sum(rets) / len(rets), 2) if rets else None,
        worst_ret_on_margin_pct=min(rets) if rets else None, best_ret_on_margin_pct=max(rets) if rets else None,
        longest_losing_streak=best, max_drawdown_pct=res["max_drawdown_pct"],
        final_equity=res["final_equity"], total_return_pct=round((res["final_equity"] / capital - 1) * 100, 2),
        buy_hold_price_return_pct=round(hold, 2) if hold is not None else None,
    )


# ---------------------------------------------------------------- 內建策略
def prepare(bars: List[Dict], trend_n: int = 50) -> Dict:
    closes = [b["close"] for b in bars]
    _, mid, _ = bollinger(closes, 20)
    return dict(close=closes, ma=sma(closes, trend_n), atr=atr(bars, 14), rsi=rsi(closes), bb_mid=mid, sma120=sma(closes, 120))


def _trend_side(i, ctx, slope=5):
    c, ma = ctx["close"], ctx["ma"]
    if i < slope or ma[i] is None or ma[i - slope] is None:
        return None
    if c[i] > ma[i] and ma[i] > ma[i - slope]:
        return "long"
    if c[i] < ma[i] and ma[i] < ma[i - slope]:
        return "short"
    return None


def atr_stop(mult: float):
    def f(i, side, ctx):
        a = ctx["atr"][i]
        if not a or mult <= 0:
            return None
        e = ctx["close"][i]
        return e - mult * a if side == "long" else e + mult * a
    return f


def strategy(name: str, sides: str = "long", hold: int = 5, stop_mult: float = 2.0):
    """回傳 (entry, exit, stop)。sides：long／short／both。"""
    allow = {"long": {"long"}, "short": {"short"}, "both": {"long", "short"}}[sides]
    if name in ("trend", "discipline"):
        def entry(i, ctx):
            s = _trend_side(i, ctx)
            return s if s in allow else None

        def exit_(j, pos, ctx):
            c, ma = ctx["close"][j], ctx["ma"][j]
            if ma is None:
                return None
            return "trend_break" if (pos["side"] == "long" and c < ma) or (pos["side"] == "short" and c > ma) else None
        return entry, exit_, atr_stop(stop_mult)
    if name == "bbmid":
        def entry(i, ctx):
            m = ctx["bb_mid"][i]
            return ("long" if "long" in allow else "short") if m and abs(ctx["close"][i] / m - 1) < 0.01 else None

        def exit_(j, pos, ctx):
            return "time" if j - pos["entry_i"] >= hold else None
        return entry, exit_, atr_stop(stop_mult)
    if name == "oversold":
        def entry(i, ctx):
            r, s = ctx["rsi"][i], ctx["sma120"][i]
            ok = r is not None and r <= 30 and ctx["atr"][i] and (s is None or ctx["close"][i] >= s * 0.9)
            return "long" if ok else None

        def exit_(j, pos, ctx):
            if (ctx["rsi"][j] or 0) >= 50:
                return "rsi50"
            return "time" if j - pos["entry_i"] >= hold else None
        return entry, exit_, atr_stop(stop_mult)
    raise ValueError(f"未知策略：{name}（trend、discipline、bbmid、oversold）")


# 交易紀律預設（2026-11-05 Hachi 檢討 TQQQ 20 倍清算後訂定）：槓桿 ≤ 5、單筆保證金 1%、逐倉、2×ATR 停損、順勢、虧損後冷卻 1 根。
DISCIPLINE = dict(max_leverage=5.0, margin_pct=1.0, stop_mult=2.0, cooldown_after_loss=1)


def backtest(ticker: str, strat: str = "trend", leverage: float = 1.0, margin_pct: float = 100.0, capital: float = 10000.0,
             sides: str = "long", rng: str = "5y", stop_mult: float = 2.0, hold: int = 5, trend_n: int = 50,
             fee_bps: Optional[float] = None, slip_bps: Optional[float] = None, sell_tax_bps: Optional[float] = None,
             bars: Optional[List[Dict]] = None, funding: Optional[Dict[int, float]] = None) -> Dict:
    warnings = []
    cooldown = 0
    if strat == "discipline":
        if leverage > DISCIPLINE["max_leverage"]:
            warnings.append(f"槓桿 {leverage:g} 倍超過紀律上限 {DISCIPLINE['max_leverage']:g} 倍")
        margin_pct, stop_mult, cooldown = DISCIPLINE["margin_pct"], DISCIPLINE["stop_mult"], DISCIPLINE["cooldown_after_loss"]
    mk = market_key(ticker)
    c = dict(COSTS.get(mk, COSTS["US"]))
    for k, v in (("fee_bps", fee_bps), ("slip_bps", slip_bps), ("sell_tax_bps", sell_tax_bps)):
        if v is not None:
            c[k] = v
    is_perp = mk == "BINANCE"
    if bars is None:
        bars = load_bars(ticker, rng)
        if is_perp and funding is None:
            try:
                funding = load_funding(ticker.split(":", 1)[1].upper(), bars[0]["ts"])
            except (RuntimeError, ValueError) as e:
                warnings.append(f"資金費率抓取失敗，未計入：{str(e)[:80]}")
    if leverage > 1 and not is_perp:
        warnings.append("股票市場以槓桿模擬（如融資或差價合約），清算規則套用逐倉合約口徑")
    ctx = prepare(bars, trend_n)
    e, x, s = strategy(strat, sides, hold, stop_mult)
    res = run(bars, e, x, s, ctx, leverage=leverage, margin_pct=margin_pct, capital=capital, costs=c,
              funding=funding if is_perp else None, cooldown_after_loss=cooldown, start=max(trend_n, 20))
    day = lambda ts: datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
    return dict(
        ticker=ticker, strategy=strat, sides=sides, leverage=leverage, margin_pct=margin_pct, capital=capital,
        period=f"{day(bars[0]['ts'])} ~ {day(bars[-1]['ts'])}", bars=len(bars), costs_bps=c,
        funding_included=bool(funding) and is_perp, **metrics(res, capital, bars),
        trades_detail=res["trades"], warnings=warnings,
        caveat="日線回測、歷史結果不代表未來；看不到盤中路徑，實際清算可能更早；不是買賣指示",
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="共用回測引擎（唯讀）")
    p.add_argument("ticker", help="例如 NASDAQ:TQQQ、TPE:0050、HKG:0005、BINANCE:TQQQUSDT")
    p.add_argument("--strategy", default="trend", choices=["trend", "discipline", "bbmid", "oversold"])
    p.add_argument("--side", default="long", choices=["long", "short", "both"])
    p.add_argument("--leverage", type=float, default=1.0)
    p.add_argument("--margin-pct", type=float, default=100.0, help="每筆保證金占目前權益 %%（discipline 固定 1）")
    p.add_argument("--capital", type=float, default=10000.0)
    p.add_argument("--range", default="5y", choices=list(RANGE_DAYS))
    p.add_argument("--stop-atr", type=float, default=2.0, help="停損 = 進場價 ∓ N×ATR，0 表示不設")
    p.add_argument("--hold", type=int, default=5, help="bbmid／oversold 最長持有根數")
    p.add_argument("--trend-n", type=int, default=50, help="趨勢均線天數")
    p.add_argument("--fee-bps", type=float); p.add_argument("--slip-bps", type=float); p.add_argument("--sell-tax-bps", type=float)
    p.add_argument("--compare", action="store_true", help="同策略比較 1／5／20 倍槓桿")
    p.add_argument("--trades", action="store_true", help="輸出每筆明細")
    a = p.parse_args(argv)
    common = dict(strat=a.strategy, margin_pct=a.margin_pct, capital=a.capital, sides=a.side, rng=a.range, stop_mult=a.stop_atr,
                  hold=a.hold, trend_n=a.trend_n, fee_bps=a.fee_bps, slip_bps=a.slip_bps, sell_tax_bps=a.sell_tax_bps)
    try:
        if a.compare:
            bars = load_bars(a.ticker, a.range)
            funding = None
            if market_key(a.ticker) == "BINANCE":
                try:
                    funding = load_funding(a.ticker.split(":", 1)[1].upper(), bars[0]["ts"])
                except (RuntimeError, ValueError):
                    funding = None
            out = {}
            for lev in (1, 5, 20):
                r = backtest(a.ticker, leverage=lev, bars=bars, funding=funding, **common)
                if not a.trades:
                    r.pop("trades_detail")
                out[f"{lev}x"] = r
        else:
            out = backtest(a.ticker, leverage=a.leverage, **common)
            if not a.trades:
                out.pop("trades_detail")
    except (RuntimeError, ValueError) as e:
        print(json.dumps(dict(ticker=a.ticker, error=str(e)), ensure_ascii=False))
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
