"""台股三市場（上市、上櫃、興櫃）近 5 個交易日熱門股：以累計成交金額排名，輸出 hot5.json。

用法：python3 hot5_fetch.py [YYYY-MM-DD]  不帶日期＝台北今天；json 寫到目前目錄。
今天證交所還沒有資料（休市或尚未收盤）時以 exit code 3 結束，不寫 hot5.json。
只讀證交所、櫃買中心公開資料，不碰 Investment_Tracker_Core。
"""
import json, re, time, sys, datetime as dt, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
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

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    today = dt.date.fromisoformat(argv[0]) if argv else (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=8)).date()
    days = []; tw = {}; d = today
    while len(days) < 6 and (today - d).days < 20:
        if d.weekday() < 5:
            x = twse(d)
            if x: days.append(d); tw[d] = x
            time.sleep(0.6)
        d -= dt.timedelta(days=1)
    days.sort(); print('days', days)
    if not days or days[-1] != today:
        print('NO_DATA_FOR_TODAY', today); return 3
    tp = {}
    for d in days:
        tp[d] = tpex(d); time.sleep(0.6)
        print(d, len(tw[d]), len(tp[d] or {}))
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
    print('emerging fetched', len(em))
    agg = []
    for c, (nm, per) in em.items():
        amt = sum(per[d]['amt'] for d in win if d in per); sh = sum(per[d]['sh'] for d in win if d in per)
        agg.append((amt, c, nm, sh, per))
    agg.sort(reverse=True); out = []
    for amt, c, nm, sh, per in agg[:5]:
        b = per.get(base, {}).get('avg'); l = next((per[d]['avg'] for d in reversed(win) if d in per and per[d]['avg']), None)
        out.append(dict(code=c, name=nm, amt=amt, lots=sh / 1000, base=b, last=l, chg=(l / b - 1) * 100 if b and l else None))
    res['emerging'] = out
    json.dump(res, open('hot5.json', 'w'), ensure_ascii=False, indent=1)
    for k in ('twse', 'tpex', 'emerging'):
        print(k)
        for r in res[k]: print(r)
    return 0


if __name__ == '__main__':
    sys.exit(main())
