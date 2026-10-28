#!/usr/bin/env python3
"""00882 成分股股利資料庫的寫入契約（盤點 F9）。

寫入內容由本腳本產生，雲端 session 用 Google Sheets MCP 寫入，寫完由本腳本逐格比對讀回結果。
用法：
  python3 sheet_contract.py build <table.json> <payload.json>      先過 gate 與 Core 拒絕，再產生寫入內容
  python3 sheet_contract.py verify <payload.json> <readback.json>  讀回與寫入內容不符時退出 1
"""
import argparse
import json
import os
import sys
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tw-etf-fetcher", "scripts"))
import etf_market  # noqa: E402  Core 拒絕與寫入防線，與台股 ETF 寫入共用

SHEET_ID = "1Jq599WzoQUDsooZDhJhyK8uaEMgDiLLCoZthWk2WXtw"  # 00882_成分股股利資料庫，寫死不接受參數
TAB_CONSTITUENTS = "成分股"
TAB_SUMMARY = "摘要"
HEADER_CONSTITUENTS = ["code", "name", "weightPct", "qty", "priceHkd", "divTtmHkd", "divLfyHkd", "chgPct", "yieldTtmPct", "interim2026"]
SUMMARY_KEYS = ["asOf", "holdingsAsOf", "ttmUnitTwd", "lfyUnitTwd", "has26", "fxHkdToTwd", "nav", "unitsOutstanding", "rows", "note", "lastUpdated", "executor"]
NOTE = "推估，不是官方配息；未扣管理費與預扣稅"
EXECUTOR = "Claude 雲端排程"
LAST_ROW = 100  # 成分股分頁寫到第 100 列；列數變少時多出的舊列清成空字串，嚴禁刪列


class ContractError(RuntimeError):
    """寫入內容產生不了（gate 未通過或表格式不符），不得寫入。"""


def normalize_date(raw):
    """日期統一成 YYYY-MM-DD，接受 2026/10/22 與 2026-10-22。"""
    return datetime.strptime(str(raw).strip().replace("/", "-"), "%Y-%m-%d").date().isoformat()


def _num(value):
    """數字欄保持數字；None 寫成空字串；浮點數去掉計算雜訊。"""
    if value is None:
        return ""
    if isinstance(value, int):
        return value
    return round(float(value), 6)


def _constituent_row(row):
    """依序對應表頭 code 到 interim2026；code 加 ' 前綴存成文字，px 為 null 寫空字串。"""
    return [
        "'" + str(row["c"]),
        str(row["n"]),
        _num(row["w"]),
        _num(row["q"]),
        _num(row["px"]),
        _num(row["ttm"]),
        _num(row["lfy"]),
        _num(row["chg"]),
        _num(row["y"]),
        str(row["i26"]),
    ]


def _summary_rows(table):
    """摘要 A:C 為 key,value,note；B 欄每個值加 ' 前綴存成文字，C 欄留空。"""
    asof = normalize_date(table["asof"])
    values = dict(
        asOf=asof,
        holdingsAsOf=normalize_date(table["holdings_asof"]),
        ttmUnitTwd=table["ttm_unit"],
        lfyUnitTwd=table["lfy_unit"],
        has26=table["has26"],
        fxHkdToTwd=table["fx"],
        nav=table["nav"],
        unitsOutstanding=int(round(table["units"])),
        rows=len(table["rows"]),
        note=NOTE,
        lastUpdated=asof,
        executor=EXECUTOR,
    )
    return [["key", "value", "note"]] + [[key, "'" + str(values[key]), ""] for key in SUMMARY_KEYS]


def build_payload(table):
    """依 table.json 產生寫入內容；gate 未通過、列數超過分頁上限或目標是 Core 都拒絕。"""
    gate = table.get("gate")
    if gate is None:
        raise ContractError("table.json 沒有 gate 欄位，請用目前版本的 constituents_table.py 重新產生")
    if not gate.get("ok"):
        raise ContractError("gate 未通過，不寫入：" + "；".join(gate.get("reasons", [])))
    if len(table["rows"]) + 1 > LAST_ROW:
        raise ContractError(f"成分股 {len(table['rows'])} 檔超過分頁上限（第 {LAST_ROW} 列）")
    etf_market.guard_sheet_id(SHEET_ID)
    constituents = [HEADER_CONSTITUENTS] + [_constituent_row(row) for row in table["rows"]]
    constituents += [[""] * len(HEADER_CONSTITUENTS) for _ in range(LAST_ROW - len(constituents))]
    summary = _summary_rows(table)
    return dict(
        spreadsheetId=SHEET_ID,
        writes=[
            dict(range=f"{TAB_CONSTITUENTS}!A1:J{LAST_ROW}", values=constituents),
            dict(range=f"{TAB_SUMMARY}!A1:C{len(summary)}", values=summary),
        ],
    )


def _to_float(text):
    try:
        return float(text)
    except ValueError:
        return None


def _decimals(number):
    return max(0, -Decimal(repr(float(number))).as_tuple().exponent)


def _cell_matches(expected, actual):
    """expected 是寫入內容的一格，actual 是讀回的字串（缺格視為空字串）。
    整數必須完全相同；浮點數容許寫入值小數位數的半個最小單位（Sheet 回傳的是格式化後的字串）。"""
    actual = "" if actual is None else str(actual)
    if expected is None or expected == "":
        return actual == ""
    if isinstance(expected, int):
        return _to_float(actual) == expected
    if isinstance(expected, float):
        got = _to_float(actual)
        return got is not None and abs(got - expected) <= 0.5 * 10 ** -_decimals(expected) + 1e-12
    text = expected[1:] if expected.startswith("'") else expected
    return actual == text


def _norm_range(text):
    """get_values 回傳的範圍可能帶單引號（'成分股'!A1:J100），比對前去掉。"""
    return str(text).replace("'", "")


def verify(payload, readback):
    """逐格比對讀回與寫入內容；回傳不符的格子說明，空清單代表吻合。"""
    grids = {_norm_range(item["range"]): item.get("values", []) for item in readback}
    problems = []
    for write in payload["writes"]:
        tab = write["range"].split("!")[0]
        grid = grids.get(_norm_range(write["range"]))
        if grid is None:
            problems.append(f"{write['range']}：讀回結果沒有這個範圍")
            continue
        for i, row in enumerate(write["values"]):
            read_row = grid[i] if i < len(grid) else []
            for j, expected in enumerate(row):
                actual = read_row[j] if j < len(read_row) else ""
                if not _cell_matches(expected, actual):
                    problems.append(f"{tab}!{chr(ord('A') + j)}{i + 1}：寫入 {expected!r}，讀回 {actual!r}")
    return problems


def _build_cli(table_path, payload_path):
    with open(table_path, encoding="utf-8") as f:
        table = json.load(f)
    try:
        payload = build_payload(table)
    except (ContractError, KeyError, ValueError, etf_market.CoreWriteRefused) as e:
        print(f"❌ [Contract] {e}", file=sys.stderr)
        return 1
    with open(payload_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    summary_items = len(payload["writes"][1]["values"]) - 1
    print(f"✅ 寫入內容已產生：{payload_path}（成分股 {len(table['rows'])} 檔，分頁寫到第 {LAST_ROW} 列；摘要 {summary_items} 項）")
    return 0


def _verify_cli(payload_path, readback_path):
    with open(payload_path, encoding="utf-8") as f:
        payload = json.load(f)
    with open(readback_path, encoding="utf-8") as f:
        readback = json.load(f)
    if isinstance(readback, dict):
        readback = [readback]
    problems = verify(payload, readback)
    for line in problems[:30]:
        print(f"❌ {line}", file=sys.stderr)
    if problems:
        print(f"❌ [Verify Failed] 共 {len(problems)} 格與寫入內容不符", file=sys.stderr)
        return 1
    print("✅ [Verify OK] 讀回與寫入內容逐格吻合")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="00882 成分股股利資料庫寫入契約：build 產生寫入內容，verify 逐格校驗讀回")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_build = sub.add_parser("build", help="table.json 產生 payload.json")
    p_build.add_argument("table")
    p_build.add_argument("payload")
    p_verify = sub.add_parser("verify", help="比對 payload.json 與 readback.json")
    p_verify.add_argument("payload")
    p_verify.add_argument("readback")
    args = parser.parse_args(argv)
    if args.cmd == "build":
        return _build_cli(args.table, args.payload)
    return _verify_cli(args.payload, args.readback)


if __name__ == "__main__":
    sys.exit(main())
