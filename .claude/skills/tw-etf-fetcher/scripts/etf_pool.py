#!/usr/bin/env python3
"""台股 ETF 成分股資料池：多檔 ETF 的成分股去重後各抓一次，產出每檔 ETF 一頁與一個索引頁（同一個 Artifact 的多頁）。

用法：python3 etf_pool.py <輸出資料夾> [--etfs 0050,0056,...] [--models-dir models]
不給 --etfs 時，掃描 models/*/cards/constituents.jsonl，成分股有 5 檔以上台股個股的 ETF 都納入。
輸出：index.html、<代號>.html（每檔 ETF）、pool.json（個股與持股兩張表，供寫入 Drive Sheet）、summary 印在標準輸出。
"""
import argparse
import html
import json
import os
import re
import sys
import time
from datetime import date
from typing import Any, Dict, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import etf_holdings_scraper  # noqa: E402
import etf_table  # noqa: E402

TW_CODE = re.compile(r"\d{4}\.(TW|TWO)")


def discover(models_dir: str, min_stocks: int = 5) -> List[str]:
    out = []
    for name in sorted(os.listdir(models_dir)):
        path = os.path.join(models_dir, name, "cards", "constituents.jsonl")
        if not os.path.exists(path):
            continue
        rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
        if sum(1 for r in rows if TW_CODE.fullmatch(r.get("ticker", ""))) >= min_stocks:
            out.append(name)
    return out


def holdings_for(etf: str, models_dir: str) -> Dict[str, Any]:
    """MoneyDJ 即時持股；抓不到就退回 repo 內 models 的持股卡片（標示來源與較舊的日期）。"""
    try:
        h = etf_holdings_scraper.fetch_etf_holdings(etf)
        if h.get("constituents") and h.get("source") == "MoneyDJ":
            return h
    except Exception:  # noqa: BLE001
        pass
    path = os.path.join(models_dir, etf, "cards", "constituents.jsonl")
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    cons = [dict(symbol=r["ticker"], name=r["name"], weight_pct=r["weight_pct"], shares=r.get("shares")) for r in rows]
    return dict(ticker=etf, as_of_date=date.fromtimestamp(os.path.getmtime(path)).isoformat(), source="models 持股卡片（備援）",
                total_count=len(cons), total_weight_pct=round(sum(c["weight_pct"] for c in cons), 2), constituents=cons)


def nav_html(etfs: List[str], current: str) -> str:
    opts = "".join(f'<option value="{e}.html"{" selected" if e == current else ""}>{e}</option>' for e in etfs)
    return ('<p class="mut"><label for="etfsel">切換 ETF　</label><select id="etfsel" onchange="location.href=this.value">'
            f'<option value="index.html">全部 ETF</option>{opts}</select></p>')


def as_page(fragment: str) -> str:
    """範本是片段（title、meta、style 在最前）；額外頁面不會被平台包外殼，所以自己拆成 head 與 body。"""
    i = fragment.index("</style>") + len("</style>")
    return ('<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            + fragment[:i] + "</head><body>" + fragment[i:] + "</body></html>")


def index_page(summaries: List[Dict[str, Any]], asof: str, n_stocks: int) -> str:
    rows = "".join(
        f'<tr><td><a href="{s["etf"]}.html">{s["etf"]}</a></td><td class="n">{s["holdings"]}</td><td class="n">{s["rows"]}</td>'
        f'<td class="n">{s["weighted_yield_pct"]:.2f}</td><td>{html.escape(s["holdings_asof"])}</td>'
        f'<td>{html.escape(s["source"])}</td><td class="n">{len(s["no_fin"])}</td></tr>' for s in summaries)
    return f"""<title>台股 ETF 成分股明細</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>
:root{{--bg:#f6f7f5;--fg:#1d2420;--mut:#5d6862;--line:#d9ded9;--acc:#1f6b57;--head:#eceee9}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#161a18;--fg:#e6ebe7;--mut:#9aa6a0;--line:#2c3430;--acc:#6fcfb0;--head:#202622;color-scheme:dark}}}}
:root[data-theme="dark"]{{--bg:#161a18;--fg:#e6ebe7;--mut:#9aa6a0;--line:#2c3430;--acc:#6fcfb0;--head:#202622;color-scheme:dark}}
body{{background:var(--bg);color:var(--fg);font:14px/1.6 system-ui,"Noto Sans TC",sans-serif;padding-block:24px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}}
main{{max-width:960px;margin:0 auto}} h1{{font-size:1.5rem;margin:0 0 4px;text-wrap:balance}} .mut{{color:var(--mut)}}
.wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:8px;margin-top:16px}}
table{{border-collapse:collapse;width:100%;min-width:560px}} th,td{{padding:8px 12px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}
th{{background:var(--head)}} .n{{text-align:right;font-variant-numeric:tabular-nums}} a{{color:var(--acc);font-weight:600}}
</style>
<main><h1>台股 ETF 成分股明細</h1>
<p class="mut">資料日期 {asof}。{len(summaries)} 檔 ETF，成分股去重後 {n_stocks} 檔個股，每檔只抓一次、各 ETF 共用。點 ETF 代號進入財報與股利明細頁，頁首可切換。</p>
<div class="wrap"><table><thead><tr><th>ETF</th><th class="n">持股檔數</th><th class="n">有股價</th><th class="n">加權殖利率%</th><th>持股日期</th><th>持股來源</th><th class="n">缺財報</th></tr></thead><tbody>{rows}</tbody></table></div>
<ul class="mut"><li>加權殖利率是成分股近 12 月殖利率依持股權重加權（毛額，未含 ETF 費用與稅，持股以外部位視為 0），是推估，不是 ETF 的配息率。</li>
<li>財報與配息來自 FinMind，股價 Google Finance；非官方彙整，缺值標示「無資料」不推估。</li></ul></main>
"""


def check_gate(
    etf_count: int,
    no_price: List[str],
    no_fin: List[str],
    bad: Dict[str, int],
    min_etfs: int = 15,
    max_missing: int = 10,
    max_errors: int = 0,
) -> Tuple[bool, List[str]]:
    """排程健康門檻檢核：etfs 約 17 檔（>=15）、缺價與財報合計不超過 10 檔、無異常 ETF。"""
    reasons = []
    if etf_count < min_etfs:
        reasons.append(f"ETF 數量不足：{etf_count} < {min_etfs}")
    total_missing = len(no_price) + len(no_fin)
    if total_missing > max_missing:
        reasons.append(f"缺價格與財報檔數超標：{total_missing} > {max_missing}")
    if len(bad) > max_errors:
        reasons.append(f"存在異常 ETF：{bad}")
    return len(reasons) == 0, reasons


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("outdir")
    ap.add_argument("--etfs", default="")
    ap.add_argument("--models-dir", default="models")
    ap.add_argument("--gate", action="store_true", help="啟用排程健康檢查門檻判定，未達門檻回傳退出碼 1")
    a = ap.parse_args(argv[1:])
    t0 = time.time()
    etfs = [e.strip().upper() for e in a.etfs.split(",") if e.strip()] or discover(a.models_dir)
    today = date.today()
    holds = {e: holdings_for(e, a.models_dir) for e in etfs}
    codes: Dict[str, str] = {}
    for h in holds.values():
        codes.update({c["symbol"].split(".")[0]: c["name"] for c in etf_table.tw_stocks(h)})
    pool = etf_table.build_pool(codes, today)
    os.makedirs(a.outdir, exist_ok=True)
    summaries, bad = [], {}
    for e in etfs:
        r = etf_table.build_page(e, holds[e], pool, today, nav=nav_html(etfs, e))
        open(os.path.join(a.outdir, f"{e}.html"), "w", encoding="utf-8").write(as_page(r["page"]))
        summaries.append(dict(r["summary"], holdings_asof=holds[e]["as_of_date"], source=holds[e]["source"]))
        if r["summary"]["errors"]:
            bad[e] = len(r["summary"]["errors"])
    open(os.path.join(a.outdir, "index.html"), "w", encoding="utf-8").write(index_page(summaries, today.isoformat(), len(pool)))
    stocks = [dict(code=c, name=g["n"], px=g["px"], ttmDiv=g["ttm"], yieldPct=g.get("y"), pe=g["f"].get("pe"), pb=g["f"].get("pb"),
                   roe=g["f"].get("roe"), payoutPct=g["f"].get("payout"), fcfCover=g["f"].get("fcf_cover"), debtPct=g["f"].get("debt"),
                   period=g["f"].get("kind"), industry=g["f"].get("org")) for c, g in pool.items()]
    holdings = [dict(etf=e, code=c["symbol"].split(".")[0], weightPct=c["weight_pct"], shares=c.get("shares"))
                for e in etfs for c in etf_table.tw_stocks(holds[e])]
    json.dump(dict(asof=today.isoformat(), stocks=stocks, holdings=holdings, summaries=summaries), open(os.path.join(a.outdir, "pool.json"), "w", encoding="utf-8"), ensure_ascii=False)
    no_price = sorted({c for s in summaries for c in s["no_price"]})
    no_fin = sorted({c for s in summaries for c in s["no_fin"]})
    print(json.dumps(dict(etfs=len(etfs), stocks=len(pool), seconds=round(time.time() - t0), no_price=no_price,
                          no_fin=no_fin, etfs_with_errors=bad), ensure_ascii=False))
    if a.gate:
        ok, reasons = check_gate(len(etfs), no_price, no_fin, bad)
        if not ok:
            print(f"❌ [Gate Failed] {'; '.join(reasons)}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
