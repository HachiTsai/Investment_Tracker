#!/usr/bin/env python3
"""更新 00882 成分股股利明細頁。用法：python3 constituents_table.py <輸出html> [前一版頁面html] [輸出json] [--gate]
輸出 json 供排程寫入 Drive「00882_成分股股利資料庫」Sheet。"""
import json, re, sys, urllib.parse, urllib.request, os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "fundamental-analyzer", "scripts"))
from fin_trend import enrich, add_dividends, add_cashflow, add_valuation, rmb_hint, ttm_dividend, mid_note, valuation_position  # 單季 EPS、年增與訊號（與台股共用）
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tw-etf-fetcher", "scripts"))
import etf_page  # 頁面渲染與市場設定與台股 ETF 共用
import nav_composition  # 每日淨值組成（收益平準金、資本平準金），收益平準金分頁用
from fetchers import eastmoney  # 財報頁沿用 fundamental-analyzer 的東方財富資料層
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "price-dividend-fetcher", "scripts"))
import fetch as price_fetch  # 股價沿用 price-dividend-fetcher（Google Finance，Yahoo 備援）

POOL_START = date(2024, 6, 14)  # 收益平準金欄位有值的第一天（更早的紀錄是 0）
B = "https://www.ctbcinvestments.com.tw/API/"
HDR = {"content-type": "application/json; charset=utf-8", "User-Agent": "Mozilla/5.0", "Referer": "https://www.ctbcinvestments.com.tw/"}


def post(path, body, token="www.ctbcinvestments.com"):
    req = urllib.request.Request(B + path + "?" + urllib.parse.urlencode({"token": token}),
                                 data=json.dumps(body).encode(), headers=HDR, method="POST")
    r = json.load(urllib.request.urlopen(req, timeout=40))
    if r.get("ResultCode") != 0:
        raise RuntimeError(f"{path}: {r.get('ResultMsg')}")
    return r["Data"]


def load_prev(path: str) -> tuple:
    """讀上一版頁面的資料列，供沿用 p25 與 cmp 兩欄。回傳 (以代號為鍵的列, 錯誤訊息)，讀不到資料列時錯誤訊息不為空。"""
    if not os.path.exists(path):
        return {}, f"找不到上一版頁面：{path}"
    m = re.search(r"const D=(\[.*?\]);\n", open(path, encoding="utf-8").read(), flags=re.S)
    prev = {r["c"]: r for r in json.loads(m.group(1))} if m else {}
    if not prev:
        return prev, f"上一版頁面讀不到資料列：{path}"
    return prev, ""


def check_gate(
    rows: int,
    fails: list,
    has26: int,
    fin_fails: list,
    pool_rows: int = 1,
    min_rows: int = 45,
    max_fails: int = 5,
    min_has26: int = 20,
    max_fin_fails: int = 5,
    carry_error: str = "",
) -> tuple:
    """排程健康門檻檢核：rows 約 49（>=45）、fails 不超過 5（預設 0 更佳）、has26 >= 20、fin_fails <= 5。"""
    reasons = []
    if rows < min_rows:
        reasons.append(f"成分股檔數不足：{rows} < {min_rows}")
    if len(fails) > max_fails:
        reasons.append(f"缺股價或歷次分配檔數超標：{len(fails)} > {max_fails} ({fails})")
    if has26 < min_has26:
        reasons.append(f"2026分紅公告檔數不足：{has26} < {min_has26}")
    if len(fin_fails) > max_fin_fails:
        reasons.append(f"財報失敗檔數超標：{len(fin_fails)} > {max_fin_fails} ({fin_fails})")
    if pool_rows < 1:
        reasons.append("收益平準金每日資料抓取失敗，頁面會缺少「收益平準金」分頁")
    if carry_error:
        reasons.append(f"上一版頁面無法沿用：{carry_error}")
    return len(reasons) == 0, reasons


def fetch_pool(etf: str = "00882", today: date = None) -> dict:
    """00882 的每日收益平準金與資本平準金（中信投信 product/GetNAV）。失敗只印警告並回空，不擋整頁。"""
    today = today or date.today()
    try:
        client = nav_composition.Client()
        rows = nav_composition.fetch_nav(client, nav_composition.resolve_fid(client, etf), POOL_START, today)
        bad = nav_composition.health(rows, today)
        if bad:
            raise nav_composition.NavError("；".join(bad))
    except Exception as e:  # 網路、防護頁、欄位改版都不該讓股利明細頁停更
        print(f"[Warn] 收益平準金資料不可用：{e}", file=sys.stderr)
        return {}
    return dict(rows=[[r["date"], r["nav"], r["income"], r["capital"]] for r in rows], events=nav_composition.distribution_events(rows))


def main(argv=None):
    if argv is None:
        argv = sys.argv
    gate_mode = "--gate" in argv
    pos_args = [a for a in argv[1:] if not a.startswith("--")]
    if not pos_args:
        print("用法：python3 constituents_table.py <輸出html> [前一版頁面html] [輸出json] [--gate]", file=sys.stderr)
        return 1
    OUT = pos_args[0]
    PREV = pos_args[1] if len(pos_args) > 1 else None
    JSON_OUT = pos_args[2] if len(pos_args) > 2 else None

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
        try:
            ch = price_fetch.get_yahoo("HKG", c, "5y")["chart"]["result"][0]
            closes = [(datetime.fromtimestamp(t + ch["meta"].get("gmtoffset", 0), timezone.utc).date().isoformat(), v)
                      for t, v in zip(ch["timestamp"], ch["indicators"]["quote"][0]["close"]) if v is not None]
            if f and divs:
                f = dict(f, **valuation_position(closes, divs, date.today()))
        except Exception:
            pass  # 歷史價抓不到時只缺估值位置欄
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

    prev, carry_error = load_prev(PREV) if PREV else ({}, "")
    carry_missing = [r["c"] for r in ok if r["c"] not in prev]
    if carry_error:
        print(f"❌ [Carry Failed] {carry_error}，p25 與 cmp 會全部留白", file=sys.stderr)
    elif carry_missing:
        print(f"⚠️ [Carry] 上一版沒有這些檔的 p25 與 cmp，留白：{carry_missing}", file=sys.stderr)
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
    pool = fetch_pool()
    # 頁首不放資料日期，與台股頁一致（空白時 etf_page 也略去付款日的說明，2026-10-27）
    page = etf_page.render("hk", "00882", 49, rows_out, [dict(c=r["c"], n=r["n"], w=r["w"], px=r["px"]) for r in rows if r.get("fail")],
                           {c: v for c, v in fin.items() if v}, "", len(ok),
                           f'{top["n"]} {top["w"]}%', f"{lfy_unit:.2f}～{ttm_unit:.2f}", pool=pool)
    open(OUT, "w", encoding="utf-8").write(page)
    print(json.dumps(dict(rows=len(ok), fails=fails, fin_fails=fin_fails, fx=round(FX, 4), nav=nav, units=units, ttm_unit=round(ttm_unit, 3), lfy_unit=round(lfy_unit, 3), has26=has26, chg=round(net / base * 100, 1), pool_rows=len(pool.get("rows", [])))))
    ok_gate, reasons = check_gate(len(ok), fails, has26, fin_fails, len(pool.get("rows", [])), carry_error=carry_error)
    if JSON_OUT:
        json.dump(dict(asof=date.today().isoformat(), holdings_asof=asof, fx=round(FX, 4), nav=nav, units=units,
                       ttm_unit=round(ttm_unit, 3), lfy_unit=round(lfy_unit, 3), has26=has26, rows=rows_out, fails=fails,
                       gate=dict(ok=ok_gate, reasons=reasons)),
                  open(JSON_OUT, "w", encoding="utf-8"), ensure_ascii=False)
    if gate_mode and not ok_gate:
        print(f"❌ [Gate Failed] {'; '.join(reasons)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
