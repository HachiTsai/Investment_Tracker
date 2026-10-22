#!/usr/bin/env python3
"""更新 00882 成分股股利明細頁。用法：python3 constituents_table.py <輸出html> [前一版頁面html] [輸出json]
輸出 json 供排程寫入 Drive「00882_成分股股利資料庫」Sheet。"""
import json, re, sys, urllib.parse, urllib.request, os
from concurrent.futures import ThreadPoolExecutor
from datetime import date

OUT = sys.argv[1]
PREV = sys.argv[2] if len(sys.argv) > 2 else None
JSON_OUT = sys.argv[3] if len(sys.argv) > 3 else None
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fin_trend import enrich, add_dividends, add_cashflow, add_valuation, rmb_hint, ttm_dividend, mid_note  # 單季 EPS、年增與訊號
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "fundamental-analyzer", "scripts"))
from fetchers import eastmoney  # 財報頁沿用 fundamental-analyzer 的東方財富資料層
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "price-dividend-fetcher", "scripts"))
import fetch as price_fetch  # 股價沿用 price-dividend-fetcher（Google Finance，Yahoo 備援）
B = "https://www.ctbcinvestments.com.tw/API/"
HDR = {"content-type": "application/json; charset=utf-8", "User-Agent": "Mozilla/5.0", "Referer": "https://www.ctbcinvestments.com.tw/"}

def post(path, body, token="www.ctbcinvestments.com"):
    req = urllib.request.Request(B + path + "?" + urllib.parse.urlencode({"token": token}),
                                 data=json.dumps(body).encode(), headers=HDR, method="POST")
    r = json.load(urllib.request.urlopen(req, timeout=40))
    if r.get("ResultCode") != 0:
        raise RuntimeError(f"{path}: {r.get('ResultMsg')}")
    return r["Data"]

tok = post("home/AuthToken", {})["token"]
hold = post("etf/ETFHoldingWeight", {"FID": "E0014", "StartDate": date.today().isoformat()}, tok)
fa = hold["FundAssets"][0]
units = float(fa["基金在外流通單位數"].replace(",", ""))
nav = float(fa["基金每單位淨值"])
asof = fa["資料日期"]
stocks = [x for x in hold["FundAssetsDetail"][0]["Data"] if x["code_"].endswith(" HK")]
trace = [x for x in post("etf/ETFTraceData", {}, tok)["Data"] if x["ETF_ID"] == "00882"]
hk = float(next(x for x in trace if x["CurType"] == 1)["CUR_INDEX"].replace(",", ""))
tw = float(next(x for x in trace if x["CurType"] == 2)["CUR_INDEX"].replace(",", ""))
FX = tw / hk  # 每 1 港幣約幾台幣

def fetch_all(x):
    """單檔：股價取 Google Finance（price-dividend-fetcher），財報、現金流與歷次分配取東方財富。
    近 12 月股息＝除息日在最近一年內的現金股息合計，上財年股息＝上一個年報財年全年合計。"""
    c = x["code_"].split()[0]
    d = dict(c=c, n=x["name_"], q=int(float(x["qty_"].replace(",", ""))), w=float(x["weights_"]), px=None)
    try:
        d["px"] = float(price_fetch.get_price("HKG:" + c.zfill(4))["price"])
    except Exception:
        pass
    try:
        f = enrich(eastmoney.hk_detail(c))
    except Exception:
        f = {}
    try:
        f = add_cashflow(f, eastmoney.hk_cashflow(c))
    except Exception:
        pass  # 現金流抓不到時只缺自由現金流欄
    f = add_valuation(f)
    try:
        divs = eastmoney.hk_dividends(c)
    except Exception:
        divs = []  # 配息明細抓不到時仍保留財報本身
    return d, f, divs

with ThreadPoolExecutor(6) as ex:
    got = list(ex.map(fetch_all, stocks))
rows = [g[0] for g in got]
fin_raw = [(g[0]["c"], g[1], g[2]) for g in got]
_hint = rmb_hint([d for _, _, d in fin_raw])
fin = {c: (add_dividends(f, d, date.today(), _hint) if f else f) for c, f, d in fin_raw}
fin_fails = [c for c, v in fin.items() if not v]
_divs = {c: d for c, _, d in fin_raw}
for r in rows:
    d, f = _divs.get(r["c"]) or [], fin.get(r["c"]) or {}
    if not d or not r["px"]:
        r["fail"] = True  # 缺股價或歷次分配就算不出殖利率，仍列入財報頁
        continue
    r["ttm"] = round(ttm_dividend(d, date.today()), 4)
    r["lfy"] = f.get("fy_hkd") or 0.0
    r["y"] = round(r["ttm"] / r["px"] * 100, 2)
    r["i26"] = mid_note(f, date.today().year)
fails = [r["c"] for r in rows if r.get("fail")]
ok = [r for r in rows if not r.get("fail")]

prev = {}
if PREV and os.path.exists(PREV):
    m = re.search(r"const D=(\[.*?\]);\n", open(PREV, encoding="utf-8").read(), flags=re.S)
    if m:
        prev = {r["c"]: r for r in json.loads(m.group(1))}
for r in ok:
    r["chg"] = round((r["ttm"] / r["lfy"] - 1) * 100, 1) if r["lfy"] else 0
    r["p25"] = prev.get(r["c"], {}).get("p25", ""); r["cmp"] = prev.get(r["c"], {}).get("cmp", "")
    r["ttm"] = r["ttm"]; r["lfy"] = r["lfy"]

up = sum(1 for r in ok if r["ttm"] - r["lfy"] > 0.005); dn = sum(1 for r in ok if r["ttm"] - r["lfy"] < -0.005)
base = sum(r["q"] * r["lfy"] for r in ok); net = sum(r["q"] * (r["ttm"] - r["lfy"]) for r in ok)
ttm_unit = sum(r["q"] * r["ttm"] for r in ok) * FX / units
lfy_unit = sum(r["q"] * r["lfy"] for r in ok) * FX / units
has26 = sum(1 for r in ok if r["i26"].startswith(("派息", "股息")))
top = max(ok, key=lambda r: r["w"])
rows_out = [dict(c=r["c"], n=r["n"], w=r["w"], q=r["q"], px=r["px"], ttm=r["ttm"], lfy=r["lfy"], chg=r["chg"], y=r["y"],
                 i26=r["i26"], p25=r["p25"], cmp=r["cmp"]) for r in ok]
tpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "references", "constituents_template.html"), encoding="utf-8").read()
page = (tpl.replace("__DATA__", json.dumps(rows_out, ensure_ascii=False))
        .replace("__MISS__", json.dumps([dict(c=r["c"], n=r["n"], w=r["w"], px=r["px"]) for r in rows if r.get("fail")], ensure_ascii=False))
        .replace("__FIN__", json.dumps({c: v for c, v in fin.items() if v}, ensure_ascii=False))
        .replace("__ASOF__", f"{date.today().isoformat()}（持股 {asof}）")
        .replace("__N__", str(len(ok))).replace("__TOP__", f'{top["n"]} {top["w"]}%')
        .replace("__UNIT__", f"{lfy_unit:.2f}～{ttm_unit:.2f}"))
open(OUT, "w", encoding="utf-8").write(page)
print(json.dumps(dict(rows=len(ok), fails=fails, fin_fails=fin_fails, fx=round(FX, 4), nav=nav, units=units, ttm_unit=round(ttm_unit, 3), lfy_unit=round(lfy_unit, 3), has26=has26, chg=round(net / base * 100, 1))))
if JSON_OUT:
    json.dump(dict(asof=date.today().isoformat(), holdings_asof=asof, fx=round(FX, 4), nav=nav, units=units,
                   ttm_unit=round(ttm_unit, 3), lfy_unit=round(lfy_unit, 3), has26=has26, rows=rows_out, fails=fails),
              open(JSON_OUT, "w", encoding="utf-8"), ensure_ascii=False)
