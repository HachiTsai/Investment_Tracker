"""中信投信 ETF 每日淨值組成（面額、收益平準金、資本平準金）抓取與除息事件偵測。

來源：中信投信網站前端自己用的公開 API `product/GetNAV`（每日 INCOME_LEVEL 是收益平準金，RL_GAIN_LEVEL 是資本平準金，
單位為每受益權單位新台幣元）。只讀、只用標準函式庫；網站改版可能失效，所以每一步都檢查並在異常時明確失敗。

用法：
    python3 nav_composition.py 00882 --start 2024-06-14 --csv out.csv
    python3 nav_composition.py 00882 --events --verify 2026-07-16:0.55,2026-01-19:0.45
"""

import argparse
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

HOSTS = ["https://www.ctbcinvestments.com.tw/API/", "https://www.ctbcinvestments.com/API/"]
HEADERS = {"content-type": "application/json; charset=utf-8", "User-Agent": "Mozilla/5.0",
           "Referer": "https://www.ctbcinvestments.com.tw/"}
TOKEN_SEED = "www.ctbcinvestments.com"
FIDS = {"00882": "E0014"}  # 已知對照；其他中信投信 ETF 由 etf/ETFList 查出
MIN_DROP = 0.10  # 收益平準金單日降幅達此值才視為配息（日常費用扣除每天只有約 0.01）
SUM_TOL = 0.02  # 面額＋收益平準金＋資本平準金與淨值的容許誤差（各欄四捨五入到 0.01）
SOURCE = "中信投信 product/GetNAV（每日淨值組成）"


class NavError(RuntimeError):
    """抓取或解析失敗；訊息即原因，呼叫端直接印出。"""


def _http_post(host: str, path: str, body: Dict[str, Any], token: str, timeout: int = 40) -> Any:
    req = urllib.request.Request(host + path + "?" + urllib.parse.urlencode({"token": token}),
                                 data=json.dumps(body).encode(), headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class Client:
    """帶 token 的 API 客戶端：token 失效就重取，網路或網頁防護的非 JSON 回應就退避重試並換下一個網域。"""

    def __init__(self, post: Callable[..., Any] = _http_post, sleep: Callable[[float], None] = time.sleep,
                 hosts: Optional[List[str]] = None, retries: int = 4, backoff: float = 2.0):
        self.post, self.sleep, self.retries, self.backoff = post, sleep, retries, backoff
        self.hosts = hosts or HOSTS
        self.token: Optional[str] = None

    def _refresh(self, host: str) -> str:
        r = self.post(host, "home/AuthToken", {}, TOKEN_SEED)
        if r.get("ResultCode") != 0 or not (r.get("Data") or {}).get("token"):
            raise NavError(f"取 token 失敗：{r.get('ResultMsg')}")
        self.token = r["Data"]["token"]
        return self.token

    def call(self, path: str, body: Dict[str, Any]) -> Any:
        last = "未嘗試"
        for attempt in range(self.retries):
            host = self.hosts[attempt % len(self.hosts)]
            try:
                r = self.post(host, path, body, self.token or self._refresh(host))
                if r.get("ResultCode") == 0:
                    return r["Data"]
                last = f"{path}: {r.get('ResultMsg')}"
                self.token = None  # 多半是 token 過期，下一圈重取
            except NavError:
                raise
            except Exception as e:  # 逾時、連線錯誤、網頁防護的 HTML（JSON 解析失敗）都走這裡
                last = f"{path}: {type(e).__name__}: {e}"
                self.token = None
            if attempt < self.retries - 1:
                self.sleep(self.backoff * (2 ** attempt))
        raise NavError(f"重試 {self.retries} 次仍失敗（{last}）")


def resolve_fid(client: Client, etf: str) -> str:
    """ETF 代號 → 中信投信基金代碼；已知表沒有就查 etf/ETFList（涵蓋中信投信全部 ETF）。"""
    etf = etf.strip().upper()
    if etf in FIDS:
        return FIDS[etf]
    data = client.call("etf/ETFList", {"IsWithETF": "Y"})
    for x in (data or {}).get("Data", []):
        if str(x.get("ETF_ID", "")).upper() == etf and x.get("FID"):
            return x["FID"]
    raise NavError(f"中信投信 ETF 清單沒有 {etf}（只涵蓋中信投信發行的 ETF）")


def _f(v: Any) -> Optional[float]:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_row(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """API 一列 → 標準列（日期轉 ISO、數字轉 float）；缺日期或任一組成欄位就回 None。"""
    nav, base, inc, cap = (_f(raw.get(k)) for k in ("NAV", "BaseNAV", "INCOME_LEVEL", "RL_GAIN_LEVEL"))
    try:
        d = datetime.strptime(str(raw.get("NAV_DT")), "%Y/%m/%d").date().isoformat()
    except ValueError:
        return None
    if None in (nav, base, inc, cap):
        return None
    return dict(date=d, nav=nav, base=base, income=inc, capital=cap)


def fetch_nav(client: Client, fid: str, start: date, end: date, chunk_days: int = 365) -> List[Dict[str, Any]]:
    """分段抓 [start, end] 的每日淨值組成，依日期排序、去重；沒有任何資料就拋例外。"""
    if start > end:
        raise NavError(f"起日 {start} 晚於迄日 {end}")
    rows: Dict[str, Dict[str, Any]] = {}
    cur = start
    while cur <= end:
        stop = min(cur + timedelta(days=chunk_days - 1), end)
        data = client.call("product/GetNAV", {"FundType": "ETF", "FID": fid, "StartDate": cur.isoformat(),
                                              "EndDate": stop.isoformat()})
        for raw in data or []:
            row = parse_row(raw)
            if row:
                rows[row["date"]] = row
        cur = stop + timedelta(days=1)
    if not rows:
        raise NavError(f"{fid} 在 {start}～{end} 沒有淨值組成資料（代碼錯誤、區間無交易日，或該基金不揭露）")
    return [rows[d] for d in sorted(rows)]


def bad_sum_rows(rows: List[Dict[str, Any]], tol: float = SUM_TOL) -> List[str]:
    """面額＋收益平準金＋資本平準金對不上淨值的日期（欄位含義變了或資料壞掉的訊號）。"""
    return [r["date"] for r in rows if abs(r["base"] + r["income"] + r["capital"] - r["nav"]) > tol]


def distribution_events(rows: List[Dict[str, Any]], min_drop: float = MIN_DROP) -> List[Dict[str, Any]]:
    """收益平準金單日降幅 ≥ min_drop 視為除息：降幅就是該次每單位配息。ratio 是配息占除息前收益平準金的比例。"""
    out = []
    for a, b in zip(rows, rows[1:]):
        paid = round(a["income"] - b["income"], 2)
        if paid >= min_drop:
            out.append(dict(ex_date=b["date"], pre_date=a["date"], pre=a["income"], post=b["income"], paid=paid,
                            ratio=round(paid / a["income"], 3) if a["income"] else None))
    return out


def verify_events(events: List[Dict[str, Any]], actual: Dict[str, float], tol: float = 0.005) -> List[str]:
    """對照官方每單位配息（日期是除息日，容許前後各 4 天，因為假日會讓淨值日期偏移）；回傳不一致的說明。"""
    problems = []
    for d, amt in sorted(actual.items()):
        target = date.fromisoformat(d)
        hit = [e for e in events if abs((date.fromisoformat(e["ex_date"]) - target).days) <= 4]
        if not hit:
            problems.append(f"{d}：官方配息 {amt}，但淨值組成偵測不到除息")
        elif abs(hit[0]["paid"] - amt) > tol:
            problems.append(f"{d}：官方配息 {amt}，淨值組成降幅 {hit[0]['paid']}")
    return problems


def health(rows: List[Dict[str, Any]], today: date, max_stale_days: int = 10, min_rows: int = 1) -> List[str]:
    """資料健康檢查；回傳不通過的原因，空清單代表通過。"""
    reasons = []
    if len(rows) < min_rows:
        reasons.append(f"資料只有 {len(rows)} 列，少於 {min_rows}")
    if rows:
        stale = (today - date.fromisoformat(rows[-1]["date"])).days
        if stale > max_stale_days:
            reasons.append(f"最新資料 {rows[-1]['date']} 已落後 {stale} 天")
        bad = bad_sum_rows(rows)
        if bad and len(bad) / len(rows) > 0.05:
            reasons.append(f"{len(bad)} 列的面額＋收益＋資本對不上淨值（例如 {bad[0]}），欄位含義可能改了")
    return reasons


def write_csv(rows: List[Dict[str, Any]], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["日期", "淨值", "面額", "收益平準金", "資本平準金"])
        for r in rows:
            w.writerow([r["date"].replace("-", "/"), r["nav"], r["base"], r["income"], r["capital"]])


def _parse_actual(text: str) -> Dict[str, float]:
    out = {}
    for part in filter(None, (p.strip() for p in text.split(","))):
        d, _, v = part.partition(":")
        date.fromisoformat(d)
        out[d] = float(v)
    return out


def main(argv: Optional[List[str]] = None, client: Optional[Client] = None, today: Optional[date] = None) -> int:
    ap = argparse.ArgumentParser(description="中信投信 ETF 每日淨值組成（收益平準金、資本平準金）")
    ap.add_argument("etf", help="ETF 代號，例如 00882（中信投信發行的 ETF）")
    ap.add_argument("--start", help="起日 YYYY-MM-DD，預設一年前")
    ap.add_argument("--end", help="迄日 YYYY-MM-DD，預設今天")
    ap.add_argument("--csv", help="輸出每日表的 CSV 路徑")
    ap.add_argument("--min-drop", type=float, default=MIN_DROP,
                    help=f"收益平準金單日降幅達此值視為除息，預設 {MIN_DROP}；月配 ETF 每次配息較小，可調低（例如 0.05）")
    ap.add_argument("--events", action="store_true", help="列出偵測到的除息事件")
    ap.add_argument("--verify", help="官方配息對照，格式 YYYY-MM-DD:金額,…；不一致退出碼 1")
    ap.add_argument("--json", action="store_true", help="以 JSON 輸出摘要")
    a = ap.parse_args(argv)
    today = today or date.today()
    client = client or Client()
    try:
        fid = resolve_fid(client, a.etf)
        end = date.fromisoformat(a.end) if a.end else today
        start = date.fromisoformat(a.start) if a.start else end - timedelta(days=365)
        rows = fetch_nav(client, fid, start, end)
    except NavError as e:
        print(f"[Error] {e}", file=sys.stderr)
        return 1
    events = distribution_events(rows, a.min_drop)
    reasons = health(rows, today)
    problems = verify_events(events, _parse_actual(a.verify)) if a.verify else []
    if a.csv:
        write_csv(rows, a.csv)
    last = rows[-1]
    summary = dict(etf=a.etf, fid=fid, source=SOURCE, rows=len(rows), first=rows[0]["date"], last=last["date"],
                   latest=dict(nav=last["nav"], income=last["income"], capital=last["capital"]), events=events,
                   health=reasons, verify=problems)
    if a.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"{a.etf}（{fid}）{rows[0]['date']}～{last['date']}，{len(rows)} 列；最新 淨值 {last['nav']}、"
              f"收益平準金 {last['income']}、資本平準金 {last['capital']}（來源：{SOURCE}）")
        if a.events or a.verify:
            for e in events:
                print(f"  除息 {e['ex_date']}：收益平準金 {e['pre']} → {e['post']}，配息 {e['paid']}（占除息前 {e['ratio']}）")
    for msg in reasons + problems:
        print(f"[Warn] {msg}", file=sys.stderr)
    return 1 if reasons or problems else 0


if __name__ == "__main__":
    sys.exit(main())
