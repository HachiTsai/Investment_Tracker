"""台股三市場（上市、上櫃、興櫃）近 5 個交易日熱門股前 5 名：抓資料與產生頁面。

熱門 = 區間累計成交金額排名（只計普通股與 ETF）。只用標準函式庫，唯讀公開資料
（證交所 MI_INDEX、櫃買中心 dailyQuotes、興櫃 emerging/latest 與逐檔 historical）。

  python3 hot5.py fetch [YYYY-MM-DD] [--out hot5.json]   不帶日期＝台北今天；今天證交所沒有資料（休市或尚未收盤）時 exit code 3
  python3 hot5.py render [hot5.json] [--out hot5.html]
"""
import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

NO_DATA = 3


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:
            err = e; time.sleep(1.5 * (i + 1))
    raise err
def n(s):
    s = str(s).replace(',', '').strip()
    try: return float(s)
    except: return None
ORD = re.compile(r'^(?!91)\d{4}$'); ETF = re.compile(r'^00\d{3,4}[A-Z]?$')
def ok(c): return bool(ORD.match(c) or ETF.match(c))
def twse(d):
    j = get(f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d:%Y%m%d}&type=ALLBUT0999&response=json")
    if j.get('stat') != 'OK': return None
    for t in j['tables']:
        if '每日收盤行情' in t.get('title', ''):
            return {r[0]: dict(name=r[1], sh=n(r[2]), amt=n(r[4]), close=n(r[8])) for r in t['data'] if ok(r[0])}
    return None
def tpex(d):
    j = get(f"https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date={urllib.parse.quote(d.strftime('%Y/%m/%d'))}&type=EW&response=json")
    if not j.get('tables') or not j['tables'][0]['data']: return None
    t = j['tables'][0]
    return {r[0]: dict(name=r[1], sh=n(r[8]), amt=n(r[9]), close=n(r[2])) for r in t['data'] if ok(r[0])}


def taipei_today():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=8)).date()


def rank(src, win, base):
    agg = {}
    for d in win:
        for c, r in (src[d] or {}).items():
            a = agg.setdefault(c, dict(name=r['name'], amt=0, sh=0)); a['amt'] += r['amt'] or 0; a['sh'] += r['sh'] or 0
    out = []
    for c, a in sorted(agg.items(), key=lambda kv: -kv[1]['amt'])[:5]:
        b = (src[base] or {}).get(c, {}).get('close'); l = (src[win[-1]] or {}).get(c, {}).get('close')
        chg = (l / b - 1) * 100 if b and l else None
        out.append(dict(code=c, name=a['name'], amt=a['amt'], lots=a['sh'] / 1000, base=b, last=l, chg=chg))
    return out


def fetch(today):
    """回傳 res；今天沒有證交所資料時回傳 None。"""
    days = []; tw = {}; d = today
    while len(days) < 6 and (today - d).days < 20:
        if d.weekday() < 5:
            x = twse(d)
            if x: days.append(d); tw[d] = x
            time.sleep(0.6)
        d -= dt.timedelta(days=1)
    days.sort()
    if not days or days[-1] != today:
        return None
    tp = {}
    for d in days:
        tp[d] = tpex(d); time.sleep(0.6)
    base, win = days[0], days[1:]
    res = {'days': [str(x) for x in days], 'twse': rank(tw, win, base), 'tpex': rank(tp, win, base)}
    # emerging
    lat = get("https://www.tpex.org.tw/www/zh-tw/emerging/latest?response=json")['tables'][0]['data']
    codes = [(r[0], r[1]) for r in lat if ok(r[0])]
    months = sorted({(d.year, d.month) for d in days})
    def hist(cn):
        c, nm = cn; rows = []
        for y, m in months:
            j = get(f"https://www.tpex.org.tw/www/zh-tw/emerging/historical?code={c}&date={y}%2F{m:02d}%2F01&response=json")
            for t in j.get('tables', []):
                rows += t['data']
        return c, nm, rows
    def roc(s):
        y, m, dd = s.split('/'); return dt.date(int(y) + 1911, int(m), int(dd))
    em = {}
    with ThreadPoolExecutor(6) as ex:
        for c, nm, rows in ex.map(hist, codes):
            per = {}
            for r in rows:
                try: dd = roc(r[0])
                except: continue
                if dd in days:
                    per[dd] = dict(sh=(n(r[1]) or 0) + (n(r[7]) or 0), amt=(n(r[2]) or 0) + (n(r[8]) or 0), avg=n(r[5]) if n(r[5]) else n(r[11]))
            em[c] = (nm, per)
    agg = []
    for c, (nm, per) in em.items():
        amt = sum(per[d]['amt'] for d in win if d in per); sh = sum(per[d]['sh'] for d in win if d in per)
        agg.append((amt, c, nm, sh, per))
    agg.sort(reverse=True); out = []
    for amt, c, nm, sh, per in agg[:5]:
        b = per.get(base, {}).get('avg'); l = next((per[d]['avg'] for d in reversed(win) if d in per and per[d]['avg']), None)
        out.append(dict(code=c, name=nm, amt=amt, lots=sh / 1000, base=b, last=l, chg=(l / b - 1) * 100 if b and l else None))
    res['emerging'] = out
    return res


CSS = """<!doctype html><html lang=zh-Hant><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>台股五日熱門股</title><style>
:root{--bg:#fafaf8;--fg:#1d1d1b;--mu:#6b6b66;--ln:#e3e2dd;--up:#c0392b;--dn:#1e8449;--card:#fff}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#161615;--fg:#ecebe6;--mu:#9a9993;--ln:#2e2e2b;--up:#ff6b5b;--dn:#4cc97a;--card:#1f1f1d}}
:root[data-theme=dark]{--bg:#161615;--fg:#ecebe6;--mu:#9a9993;--ln:#2e2e2b;--up:#ff6b5b;--dn:#4cc97a;--card:#1f1f1d}
body{background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,"Noto Sans TC",sans-serif;margin:0;padding:24px 16px}main{max-width:820px;margin:auto}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px}.s,.m{color:var(--mu);font-size:13px}
.w{overflow-x:auto;background:var(--card);border:1px solid var(--ln);border-radius:8px}table{border-collapse:collapse;width:100%;min-width:520px}
th,td{padding:8px 10px;border-bottom:1px solid var(--ln);text-align:left;white-space:nowrap}th{font-size:12px;color:var(--mu);font-weight:500}.n{text-align:right;font-variant-numeric:tabular-nums}.up{color:var(--up)}.dn{color:var(--dn)}
</style></head><body><main><h1>台股三市場：近 5 個交易日熱門股前 5 名</h1>
"""


def render(r):
    days = r['days']
    md = lambda s: f"{int(s[5:7])}/{int(s[8:10])}"
    base, win = days[0], days[1:]
    last = md(win[-1]); rng = f"{md(win[0])}–{last}"; basemd = md(base)

    def rows(L):
        o = ''
        for i, x in enumerate(L, 1):
            c = x['chg']
            if c is None:
                cls, cs = '', '—'
            else:
                cls, cs = ('up' if c > 0 else 'dn' if c < 0 else ''), f"{c:+.2f}%"
            lastpx = f"{x['last']:,.2f}" if x['last'] is not None else '—'
            o += (f"<tr><td>{i}</td><td><b>{x['code']}</b> {x['name']}</td><td class=n>{x['amt']/1e8:,.2f}</td>"
                  f"<td class=n>{x['lots']:,.0f}</td><td class=n>{lastpx}</td><td class=\"n {cls}\">{cs}</td></tr>")
        return o

    def sec(t, k, px, src):
        return (f"<section><h2>{t}</h2><div class=w><table><thead><tr><th>#</th><th>股票</th><th>5日成交金額<br>(億元)</th>"
                f"<th>5日成交量<br>(張)</th><th>{last} {px}</th><th>區間漲跌</th></tr></thead><tbody>{rows(r[k])}</tbody></table></div>"
                f"<p class=s>{src}；區間 {rng}，基準日 {basemd}</p></section>")

    head = CSS + (f"<p class=m>區間：{'、'.join(md(d) for d in win)}（{basemd} 為漲跌基準日）。三個市場皆算到 {last}，區間相同。<br>\n"
                  f"「熱門」定義：區間 <b>累計成交金額</b> 排名（只計普通股與 ETF，不含權證、債券、ETN、存託憑證）。"
                  f"區間漲跌 = {last} 價格 ÷ {basemd} 基準日價格 − 1（紅漲綠跌），未還原除權息。"
                  f"興櫃無收盤價，以日成交均價計算（一般與鉅額交易合計）。</p>")
    return (head + sec('上市（證交所）', 'twse', '收盤價', '來源：證交所 MI_INDEX 每日收盤行情')
            + sec('上櫃（櫃買中心）', 'tpex', '收盤價', '來源：櫃買中心 上櫃每日收盤行情')
            + sec('興櫃（櫃買中心）', 'emerging', '成交均價', '來源：櫃買中心 興櫃 emerging/latest 加逐檔 emerging/historical')
            + f"<p class=s>資料於 {days[-1]} 收盤後自證交所、櫃買中心官網抓取。純資料整理，不構成買賣建議。</p></main></body></html>")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    pf = sub.add_parser('fetch'); pf.add_argument('date', nargs='?'); pf.add_argument('--out', default='hot5.json')
    pr = sub.add_parser('render'); pr.add_argument('json', nargs='?', default='hot5.json'); pr.add_argument('--out', default='hot5.html')
    a = ap.parse_args(argv)
    if a.cmd == 'fetch':
        today = dt.date.fromisoformat(a.date) if a.date else taipei_today()
        res = fetch(today)
        if res is None:
            print(f'NO_DATA_FOR_TODAY {today}'); return NO_DATA
        json.dump(res, open(a.out, 'w'), ensure_ascii=False, indent=1)
        print(f"days {res['days']}"); return 0
    html = render(json.load(open(a.json)))
    open(a.out, 'w').write(html); print(f'wrote {a.out} ({len(html)} bytes)'); return 0


if __name__ == '__main__':
    sys.exit(main())
