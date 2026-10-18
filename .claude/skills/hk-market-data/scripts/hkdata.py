#!/usr/bin/env python3
"""港股資料查詢（唯讀）。輸出 JSON 到 stdout；來源與口徑見 references/sources.md。

用法：
  hkdata.py announce 0939 1919 [--days 30] [--all]
  hkdata.py pdf <港交所PDF網址> [--grep 正規式]
  hkdata.py southbound [--days 10] [--crosscheck]
  hkdata.py ccass 0939 [--date 2026-10-13] [--compare-days 7]
  hkdata.py quote 0939 1919 [--range 1mo]
  hkdata.py sectors [--announce-days 8]
  hkdata.py macro
"""
import argparse, html, json, re, subprocess, sys, tempfile, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone

UA = {"User-Agent": "Mozilla/5.0"}
HKEXNEWS = "https://www1.hkexnews.hk"
CTBC = "https://www.ctbcinvestments.com.tw/API/"
KEYS = re.compile(r"RESULT|DIVIDEND|PROFIT WARNING|PROFIT ALERT|DISTRIBUTION|業績|股息|盈利", re.I)
SB_TYPES = {"006": "港股通合計", "002": "港股通（滬）", "004": "港股通（深）"}
# 00882 成分股產業分組：Claude 依主業歸類（官方未提供），持股變動時更新
SECTOR = {
    "銀行": "3988 1398 3328 1288 998 939 1658 3968 1988 6818",
    "保險與金融": "2328 1336 1339 2318 3360 267",
    "公用事業": "902 836 270 392 384 257 371",
    "地產與物管": "3311 1908 683 688 1109 2602 1209",
    "航運與港口": "1919 1199 144 152",
    "消費": "220 322 3998 1579 6690 1044 6186 1368 6110",
    "工業與能源": "148 1088 1766 390 914 3808",
}
SECTOR_OF = {c: s for s, cs in SECTOR.items() for c in cs.split()}


def http(url, data=None, headers=None, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
            return urllib.request.urlopen(req, timeout=40).read()
        except Exception:
            if i == tries - 1:
                raise


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm(code):
    """'939'、'0939'、'00939'、'939 HK' → '939'"""
    return str(int(re.sub(r"\D", "", str(code))))


# ---------- 港交所披露易 ----------
def parse_prefix(text):
    m = re.search(r'"stockId":(\d+)', text)
    return int(m[1]) if m else None


def parse_titles(payload, keep_all=False):
    r = json.loads(payload)
    rows = [] if r.get("result") in (None, "null") else json.loads(r["result"])
    out = []
    for x in rows:
        title = html.unescape(re.sub(r"\s+", " ", x["TITLE"])).strip()
        if keep_all or KEYS.search(title):
            out.append(dict(time=x["DATE_TIME"], title=title, url=HKEXNEWS + x["FILE_LINK"]))
    return out


def announce(code, days=30, keep_all=False, today=None):
    today = today or date.today()
    c = norm(code)
    sid = parse_prefix(http(f"{HKEXNEWS}/search/prefix.do?&callback=c&lang=EN&type=A&name={c.zfill(5)}&market=SEHK").decode())
    if sid is None:
        raise RuntimeError(f"港交所查不到代號 {c}")
    q = dict(sortDir=0, sortByOptions="DateTime", category=0, market="SEHK", stockId=sid, documentType=-1,
             fromDate=(today - timedelta(days=days)).strftime("%Y%m%d"), toDate=today.strftime("%Y%m%d"),
             title="", searchType=0, t1code=-2, t2Gcode=-2, t2code=-2, rowRange=100, lang="E")
    return parse_titles(http(f"{HKEXNEWS}/search/titleSearchServlet.do?" + urllib.parse.urlencode(q)), keep_all)


def pdf_text(url):
    if not url.startswith(HKEXNEWS + "/"):
        raise ValueError("只接受 www1.hkexnews.hk 的公告網址")
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(http(url)); f.flush()
        return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True, check=True).stdout


# ---------- CCASS 持股（港交所 www3.hkexnews.hk） ----------
CCASS_URL = "https://www3.hkexnews.hk/sdw/search/searchsdw.aspx"
SOUTHBOUND_IDS = {"A00003": "港股通（滬）", "A00004": "港股通（深）"}


def parse_ccass(page):
    """CCASS 查詢結果頁 → (已發行股份總數 or None, [參與者 dict])"""
    cells = [html.unescape(c).strip() for c in re.findall(r'class="mobile-list-body">([^<]*)', page)]
    rows = []
    for i in range(0, len(cells) - 4, 5):
        pid, name, _addr, qty, pct = cells[i:i + 5]
        if not re.fullmatch(r"[A-Z]\d{5}", pid):
            continue
        rows.append(dict(id=pid, name=name, shares=int(qty.replace(",", "")), pct=float(pct.rstrip("%"))))
    return rows


def southbound_share(rows):
    sb = [r for r in rows if r["id"] in SOUTHBOUND_IDS]
    return dict(shares=sum(r["shares"] for r in sb), pct=round(sum(r["pct"] for r in sb), 2))


def ccass_rows(code, day):
    import http.cookiejar
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    op.addheaders = list(UA.items())
    t = op.open(CCASS_URL, timeout=40).read().decode()
    f = {k: html.unescape(v) for k, v in re.findall(r'name="(__[A-Z]+)" id="__[A-Z]+" value="([^"]*)"', t)}
    f.update(__EVENTTARGET="btnSearch", txtShareholdingDate=day.strftime("%Y/%m/%d"), txtStockCode=norm(code).zfill(5),
             txtStockName="", txtParticipantID="", txtParticipantName="", txtSelPartID="",
             sortBy="shareholding", sortDirection="desc", today=date.today().strftime("%Y%m%d"))
    rows = parse_ccass(op.open(CCASS_URL, urllib.parse.urlencode(f).encode(), timeout=60).read().decode())
    if not rows:
        raise RuntimeError(f"CCASS 查不到 {code} 在 {day} 的持股（可能非交易日或超過一年）")
    return rows


def ccass(code, day=None, compare_days=7, top=10):
    day = day or date.today() - timedelta(days=1)
    now = ccass_rows(code, day)
    res = dict(date=day.isoformat(), source="港交所 CCASS 持股紀錄", top=now[:top], southbound=southbound_share(now))
    if compare_days:
        d0 = day - timedelta(days=compare_days)
        prev = ccass_rows(code, d0)
        p, n = southbound_share(prev), res["southbound"]
        res["compare"] = dict(date=d0.isoformat(), southbound=p, pct_change=round(n["pct"] - p["pct"], 2),
                              shares_change=n["shares"] - p["shares"])
    return res


# ---------- 港股通（南向）資金 ----------
def parse_eastmoney(payload):
    r = json.loads(payload)
    if not r.get("success"):
        raise RuntimeError(f"東方財富：{r.get('message')}")
    return [dict(date=x["TRADE_DATE"][:10], net=round(x["NET_DEAL_AMT"], 2), buy=x["BUY_AMT"], sell=x["SELL_AMT"],
                 turnover=x["DEAL_AMT"], hsi=x.get("INDEX_CLOSE_PRICE"), hsi_chg_pct=x.get("INDEX_CHANGE_RATE"))
            for x in r["result"]["data"]]


def parse_hkex_daily(text):
    """港交所 data_tab_daily_*.js → {'date':…, 'net':…} 南向（滬＋深）買賣差，百萬港元"""
    d = json.loads(text[text.index("["):].rstrip().rstrip(";"))
    buy = sell = 0.0; day = None; seen = 0
    for m in d:
        if "Southbound" not in m["market"] or not m.get("tradingDay"):
            continue
        t = m["content"][0]["table"]
        cols = t["schema"][0]
        vals = [float(r["td"][0][0].replace(",", "")) for r in t["tr"]]
        v = dict(zip(cols, vals))
        buy += v["Buy Turnover"]; sell += v["Sell Turnover"]; day = m["date"]; seen += 1
    if not seen:
        return None
    return dict(date=day, buy=round(buy, 2), sell=round(sell, 2), net=round(buy - sell, 2))


def southbound(days=10, crosscheck=False):
    out = {}
    start = (date.today() - timedelta(days=days)).isoformat()
    for t, name in SB_TYPES.items():
        q = urllib.parse.urlencode(dict(reportName="RPT_MUTUAL_DEAL_HISTORY",
            columns="TRADE_DATE,NET_DEAL_AMT,DEAL_AMT,BUY_AMT,SELL_AMT,INDEX_CLOSE_PRICE,INDEX_CHANGE_RATE",
            filter=f'(MUTUAL_TYPE="{t}")(TRADE_DATE>=\'{start}\')', sortColumns="TRADE_DATE", sortTypes=-1,
            pageSize=60, pageNumber=1))
        out[name] = parse_eastmoney(http("https://datacenter-web.eastmoney.com/api/data/v1/get?" + q))
    res = dict(unit="百萬港元", source="東方財富 RPT_MUTUAL_DEAL_HISTORY", fetched_at=now_utc(), daily=out,
               total_net=round(sum(x["net"] for x in out["港股通合計"]), 2))
    if crosscheck and out["港股通合計"]:
        x = out["港股通合計"][0]
        try:
            h = parse_hkex_daily(http(f"https://www.hkex.com.hk/eng/csm/DailyStat/data_tab_daily_{x['date'].replace('-', '')}e.js").decode())
            res["crosscheck"] = dict(hkex=h, consistent=h is not None and abs(h["net"] - x["net"]) < 1)
        except Exception as e:
            res["crosscheck"] = dict(error=str(e))
    return res


# ---------- 報價（Yahoo Finance） ----------
def parse_yahoo(payload):
    r = json.loads(payload)["chart"]
    if r.get("error"):
        raise RuntimeError(f"Yahoo：{r['error']}")
    res = r["result"][0]; m = res["meta"]
    closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
    first = closes[0] if closes else None
    return dict(symbol=m["symbol"], currency=m.get("currency"), price=m.get("regularMarketPrice"),
                prev_close=closes[-2] if len(closes) >= 2 else m.get("chartPreviousClose"),
                as_of=datetime.fromtimestamp(m["regularMarketTime"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                range_change_pct=round((m["regularMarketPrice"] / first - 1) * 100, 2) if first else None,
                high_52w=m.get("fiftyTwoWeekHigh"), low_52w=m.get("fiftyTwoWeekLow"))


def quote(code, rng="1mo"):
    sym = norm(code).zfill(4) + ".HK"
    return parse_yahoo(http(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"))


# ---------- 00882 產業漲跌 ----------
def ctbc(path, body, token="www.ctbcinvestments.com"):
    r = json.loads(http(CTBC + path + "?" + urllib.parse.urlencode({"token": token}), json.dumps(body).encode(),
                        {"content-type": "application/json; charset=utf-8", "Referer": "https://www.ctbcinvestments.com.tw/"}))
    if r.get("ResultCode") != 0:
        raise RuntimeError(f"中信投信 {path}：{r.get('ResultMsg')}")
    return r["Data"]


def holdings(tok, d):
    h = ctbc("etf/ETFHoldingWeight", {"FID": "E0014", "StartDate": d.isoformat()}, tok)
    rows = [x for x in h["FundAssetsDetail"][0]["Data"] if x["code_"].endswith(" HK")]
    return h["FundAssets"][0]["資料日期"], {norm(x["code_"]): x for x in rows}


def sector_returns(now, prev, base):
    """now/prev/base：{代號: {'weights_','price_','name_'}}；回傳各產業加權漲跌（小數）"""
    out, stocks = [], []
    for s in SECTOR:
        w_all = w1 = b1 = wy = by = 0.0
        for c, x in now.items():
            if SECTOR_OF.get(c) != s:
                continue
            w, p = float(x["weights_"]), float(x["price_"])
            w_all += w
            r1 = p / float(prev[c]["price_"]) - 1 if c in prev else None
            ry = p / float(base[c]["price_"]) - 1 if c in base else None
            if r1 is not None: w1 += w * r1; b1 += w
            if ry is not None: wy += w * ry; by += w
            stocks.append(dict(code=c, name=x["name_"], sector=s, weight=w, price=p, r1w=r1, rytd=ry))
        out.append(dict(sector=s, weight=round(w_all, 2), r1w=w1 / b1 if b1 else None, rytd=wy / by if by else None))
    return out, stocks, [c for c in now if c not in SECTOR_OF]


def sectors(announce_days=0):
    today = date.today()
    tok = ctbc("home/AuthToken", {})["token"]
    asof, now = holdings(tok, today)
    _, prev = holdings(tok, today - timedelta(days=7))
    _, base = holdings(tok, date(today.year - 1, 12, 31))
    sec, stocks, unmapped = sector_returns(now, prev, base)
    res = dict(asof=asof, source="中信投信 ETFHoldingWeight", sectors=sec, stocks=stocks, unmapped=unmapped)
    if announce_days:
        ann = []
        for c in now:
            try:
                ann += [dict(code=c, **a) for a in announce(c, announce_days)]
            except Exception as e:
                ann.append(dict(code=c, error=str(e)))
        res["hkex"] = sorted(ann, key=lambda a: datetime.strptime(a["time"], "%d/%m/%Y %H:%M") if "time" in a else datetime.min, reverse=True)
    return res


# ---------- 宏觀經濟與前饋指標 ----------
def parse_lpr(payload):
    r = json.loads(payload)
    if not r.get("success") or not r.get("result"):
        raise RuntimeError(f"東方財富 LPR：{r.get('message')}")
    d = r["result"]["data"][0]
    return dict(date=d["TRADE_DATE"][:10], lpr_1y=float(d["LPR1Y"]), lpr_5y=float(d["LPR5Y"]))


def parse_chinabond(html_text):
    tables = re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, re.S)
    for t in tables:
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", t, re.S)]
        if len(cells) >= 10 and cells[0] == "中债国债收益率曲线":
            return dict(date=cells[1], yield_10y=float(cells[8]), yield_30y=float(cells[9]))
    return None


def parse_sse_index(html_text, pattern_name):
    """從上航所 HTML 萃取指數數值與漲跌"""
    m = re.search(pattern_name + r".*?<td[^>]*>([0-9.]+)</td>\s*<td[^>]*>([0-9.]+)</td>\s*<td[^>]*>([+-]?[0-9.]+)</td>", html_text, re.S)
    if m:
        return dict(prev=float(m.group(1)), current=float(m.group(2)), change=float(m.group(3)))
    m2 = re.search(pattern_name + r".*?<td[^>]*>([0-9.]+)</td>\s*<td[^>]*>([+-]?[0-9.]+)</td>", html_text, re.S)
    if m2:
        return dict(current=float(m2.group(1)), change=float(m2.group(2)))
    return None


def macro():
    res = dict(fetched_at=now_utc(), indicators={})

    # 1. 貨幣與基準利率 (LPR)
    try:
        url_lpr = "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPTA_WEB_RATE&columns=ALL&sortColumns=TRADE_DATE&sortTypes=-1&token=894050c76af8597a853f5b408b759f5d&pageNumber=1&pageSize=1"
        res["indicators"]["lpr"] = parse_lpr(http(url_lpr).decode())
    except Exception as e:
        res["indicators"]["lpr"] = dict(error=str(e))

    # 2. 中國國債殖利率 (中債10年/30年)
    try:
        end_d = date.today().isoformat()
        start_d = (date.today() - timedelta(days=14)).isoformat()
        url_cb = f"https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/historyQuery?startDate={start_d}&endDate={end_d}&gjqx=0&qxId=ycqx&locale=cn_ZH"
        cb = parse_chinabond(http(url_cb).decode("utf-8", errors="ignore"))
        res["indicators"]["china_treasury_yield"] = cb or dict(error="查無國債收益率資料")
    except Exception as e:
        res["indicators"]["china_treasury_yield"] = dict(error=str(e))

    # 3. 外匯摩擦 (USD/CNH 離岸人民幣, HKD/TWD 港幣兌台幣)
    try:
        fx = {}
        for sym, name in [("USDCNH=X", "USD_CNH"), ("HKDTWD=X", "HKD_TWD")]:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=1d"
            y = json.loads(http(url).decode())["chart"]["result"][0]["meta"]
            fx[name] = dict(rate=y["regularMarketPrice"], symbol=sym)
        res["indicators"]["fx"] = fx
    except Exception as e:
        res["indicators"]["fx"] = dict(error=str(e))

    # 4. 航運與沿海煤炭運價指數 (SCFI, CBOFI)
    try:
        shipping = {}
        url_scfi = "https://www.sse.net.cn/index/singleIndex?indexType=scfi"
        scfi_html = http(url_scfi).decode("utf-8", errors="ignore")
        scfi_data = parse_sse_index(scfi_html, "综合指数 Comprehensive Index")
        if scfi_data:
            shipping["scfi"] = scfi_data

        url_coal = "https://www.sse.net.cn/index/singleIndex?indexType=cbofi"
        coal_html = http(url_coal).decode("utf-8", errors="ignore")
        coal_data = parse_sse_index(coal_html, "综合指数")
        if coal_data:
            shipping["coastal_coal_freight"] = coal_data
        res["indicators"]["shipping_freight"] = shipping
    except Exception as e:
        res["indicators"]["shipping_freight"] = dict(error=str(e))

    return res


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("announce"); a.add_argument("codes", nargs="+"); a.add_argument("--days", type=int, default=30); a.add_argument("--all", action="store_true")
    b = sp.add_parser("pdf"); b.add_argument("url"); b.add_argument("--grep")
    c = sp.add_parser("southbound"); c.add_argument("--days", type=int, default=10); c.add_argument("--crosscheck", action="store_true")
    f = sp.add_parser("ccass"); f.add_argument("codes", nargs="+"); f.add_argument("--date"); f.add_argument("--compare-days", type=int, default=7); f.add_argument("--top", type=int, default=10)
    d = sp.add_parser("quote"); d.add_argument("codes", nargs="+"); d.add_argument("--range", default="1mo")
    e = sp.add_parser("sectors"); e.add_argument("--announce-days", type=int, default=0)
    sp.add_parser("macro")
    o = p.parse_args(argv)
    rc = 0
    if o.cmd == "ccass":
        res = {}
        day = date.fromisoformat(o.date) if o.date else None
        for code in o.codes:
            try:
                res[norm(code)] = ccass(code, day, o.compare_days, o.top)
            except Exception as ex:
                res[norm(code)] = dict(error=str(ex)); rc = 1
        print(json.dumps(dict(fetched_at=now_utc(), results=res), ensure_ascii=False, indent=1))
        return rc
    if o.cmd in ("announce", "quote"):
        res = {}
        for code in o.codes:
            try:
                res[norm(code)] = announce(code, o.days, o.all) if o.cmd == "announce" else quote(code, o.range)
            except Exception as ex:
                res[norm(code)] = dict(error=str(ex)); rc = 1
        res = dict(fetched_at=now_utc(), results=res)
    elif o.cmd == "pdf":
        t = pdf_text(o.url)
        if o.grep:
            rx = re.compile(o.grep, re.I)
            t = "\n".join(f"{i}: {l.strip()}" for i, l in enumerate(t.splitlines(), 1) if rx.search(l))
        print(t); return 0
    elif o.cmd == "southbound":
        res = southbound(o.days, o.crosscheck)
    elif o.cmd == "macro":
        res = macro()
    else:
        res = sectors(o.announce_days)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return rc


if __name__ == "__main__":
    sys.exit(main())

