"""讀目前目錄的 hot5.json（hot5_fetch.py 產出），輸出 hot5.html。用法：python3 hot5_report.py"""
import json


def render(r):
    days = r['days']
    md = lambda s: f"{int(s[5:7])}/{int(s[8:10])}"
    base, win = days[0], days[1:]
    last = md(win[-1]); rng = f"{md(win[0])}–{last}"; basemd = md(base)
    def rows(L):
        o = ''
        for i, x in enumerate(L, 1):
            c = x['chg']; cls = 'up' if c > 0 else 'dn' if c < 0 else ''
            o += f"<tr><td>{i}</td><td><b>{x['code']}</b> {x['name']}</td><td class=n>{x['amt']/1e8:,.2f}</td><td class=n>{x['lots']:,.0f}</td><td class=n>{x['last']:,.2f}</td><td class=\"n {cls}\">{c:+.2f}%</td></tr>"
        return o
    def sec(t, k, px, src):
        return f"<section><h2>{t}</h2><div class=w><table><thead><tr><th>#</th><th>股票</th><th>5日成交金額<br>(億元)</th><th>5日成交量<br>(張)</th><th>{last} {px}</th><th>區間漲跌</th></tr></thead><tbody>{rows(r[k])}</tbody></table></div><p class=s>{src}；區間 {rng}，基準日 {basemd}</p></section>"
    css = """<!doctype html><html lang=zh-Hant><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>台股五日熱門股</title><style>
    :root{--bg:#fafaf8;--fg:#1d1d1b;--mu:#6b6b66;--ln:#e3e2dd;--up:#c0392b;--dn:#1e8449;--card:#fff}
    @media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#161615;--fg:#ecebe6;--mu:#9a9993;--ln:#2e2e2b;--up:#ff6b5b;--dn:#4cc97a;--card:#1f1f1d}}
    :root[data-theme=dark]{--bg:#161615;--fg:#ecebe6;--mu:#9a9993;--ln:#2e2e2b;--up:#ff6b5b;--dn:#4cc97a;--card:#1f1f1d}
    body{background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,"Noto Sans TC",sans-serif;margin:0;padding:24px 16px}main{max-width:820px;margin:auto}
    h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px}.s,.m{color:var(--mu);font-size:13px}
    .w{overflow-x:auto;background:var(--card);border:1px solid var(--ln);border-radius:8px}table{border-collapse:collapse;width:100%;min-width:520px}
    th,td{padding:8px 10px;border-bottom:1px solid var(--ln);text-align:left;white-space:nowrap}th{font-size:12px;color:var(--mu);font-weight:500}.n{text-align:right;font-variant-numeric:tabular-nums}.up{color:var(--up)}.dn{color:var(--dn)}
    </style></head><body><main><h1>台股三市場：近 5 個交易日熱門股前 5 名</h1>
    """
    css += f"<p class=m>區間：{'、'.join(md(d) for d in win)}（{basemd} 為漲跌基準日）。三個市場皆算到 {last}，區間相同。<br>\n「熱門」定義：區間 <b>累計成交金額</b> 排名（只計普通股與 ETF，不含權證、債券、ETN、存託憑證）。區間漲跌 = {last} 價格 ÷ {basemd} 基準日價格 − 1（紅漲綠跌），未還原除權息。興櫃無收盤價，以日成交均價計算（一般與鉅額交易合計）。</p>"
    h = css + sec('上市（證交所）', 'twse', '收盤價', '來源：證交所 MI_INDEX 每日收盤行情') + sec('上櫃（櫃買中心）', 'tpex', '收盤價', '來源：櫃買中心 上櫃每日收盤行情') + sec('興櫃（櫃買中心）', 'emerging', '成交均價', '來源：櫃買中心 興櫃 emerging/latest 加逐檔 emerging/historical') + f"<p class=s>資料於 {days[-1]} 收盤後自證交所、櫃買中心官網抓取。純資料整理，不構成買賣建議。</p></main></body></html>"
    return h


if __name__ == '__main__':
    with open('hot5.json', encoding='utf-8') as f:
        html = render(json.load(f))
    with open('hot5.html', 'w', encoding='utf-8') as f:
        f.write(html)
