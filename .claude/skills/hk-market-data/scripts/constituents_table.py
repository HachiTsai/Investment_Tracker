#!/usr/bin/env python3
"""更新 00882 成分股股利明細頁。用法：python3 constituents_table.py <輸出html> [前一版頁面html] [輸出json]
輸出 json 供排程寫入 Drive「00882_成分股股利資料庫」Sheet。"""
import json, re, html, subprocess, sys, urllib.parse, urllib.request, os, tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date

OUT = sys.argv[1]
PREV = sys.argv[2] if len(sys.argv) > 2 else None
JSON_OUT = sys.argv[3] if len(sys.argv) > 3 else None
import glob
CH = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"))[-1]
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

def render(url):
    for _ in range(2):
        r = subprocess.run([CH, "--headless=new", "--no-sandbox", "--disable-gpu", f"--proxy-server={os.environ.get('HTTPS_PROXY','')}",
                            "--virtual-time-budget=15000", "--dump-dom", url], capture_output=True, text=True, timeout=120)
        if len(r.stdout) > 50000:
            t = re.sub(r"<script.*?</script>|<style.*?</style>", "", r.stdout, flags=re.S)
            t = re.sub(r"<[^>]+>", "|", t); t = re.sub(r"\|[\s|]*\|", "|", html.unescape(t))
            return re.sub(r"\s+", " ", t)
    return ""

def one(x):
    c = x["code_"].split()[0]; n = c.zfill(5)
    t = render(f"https://www.futunn.com/stock/{n}-HK")
    g = lambda lab: (re.search(r"([\d.,]+%?|--)\s*\|\s*" + lab, t) or [None, None])[1]
    px = re.search(r"\(%s\)\s*\|[^|]*\|\s*([\d.]+)" % n, t)
    d = dict(c=c, n=x["name_"], q=int(float(x["qty_"].replace(",", ""))), w=float(x["weights_"]),
             px=float(px.group(1)) if px else None)
    try:
        d.update(ttm=float(g("股息TTM")), lfy=float(g("股息LFY")), y=float(g("股息率TTM").strip("%")))
    except (TypeError, ValueError):
        d["fail"] = True
        return d
    e = render(f"https://www.futunn.com/stock/{n}-HK/earnings")
    i = e.find("财务报表"); seg = e[i:i + 1500] if i >= 0 else ""
    hit = [h for h in seg.split("|") if re.search("中期|派息|股息", h)]
    AMT = re.compile(r"(?:派息|股息)(?:每\d*股)?(?:人民币|港币|港元)?\s*\d+(?:\.\d+)?(?![\d%年月])\s*(?:港元|港仙|仙|元|港币|人民币)?")
    found = None
    for h in sorted(hit, key=lambda h: "中期" not in h):
        m = AMT.search(h.replace("比率", "@"))
        if m and "年度" not in h[:m.start()][-4:]:
            found = m.group(0); break
    if found:
        d["i26"] = found
    elif any("中期" in h for h in hit):
        d["i26"] = "已公告，金額未標"
    else:
        d["i26"] = "董事會審議/未找到"
    return d

with ThreadPoolExecutor(6) as ex:
    rows = list(ex.map(one, stocks))
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
        .replace("__ASOF__", f"{date.today().isoformat()}（持股 {asof}）")
        .replace("__N__", str(len(ok))).replace("__TOP__", f'{top["n"]} {top["w"]}%')
        .replace("__HAS26__", str(has26)).replace("__CHG__", f"{net / base * 100:+.1f}%")
        .replace("__UPDN__", f"{up} 檔增、{dn} 檔減、{len(ok) - up - dn} 檔持平")
        .replace("__UNIT__", f"{lfy_unit:.2f}～{ttm_unit:.2f}"))
open(OUT, "w", encoding="utf-8").write(page)
print(json.dumps(dict(rows=len(ok), fails=fails, fx=round(FX, 4), nav=nav, units=units, ttm_unit=round(ttm_unit, 3), lfy_unit=round(lfy_unit, 3), has26=has26, chg=round(net / base * 100, 1))))
if JSON_OUT:
    json.dump(dict(asof=date.today().isoformat(), holdings_asof=asof, fx=round(FX, 4), nav=nav, units=units,
                   ttm_unit=round(ttm_unit, 3), lfy_unit=round(lfy_unit, 3), has26=has26, rows=rows_out, fails=fails),
              open(JSON_OUT, "w", encoding="utf-8"), ensure_ascii=False)
