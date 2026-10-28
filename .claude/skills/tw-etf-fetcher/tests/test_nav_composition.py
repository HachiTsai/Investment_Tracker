"""nav_composition 離線測試：API 回應全換成固定資料。除息列取自 2024～2026 年中信投信 00882 的實際回應。"""

import csv
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import nav_composition as nc  # noqa: E402

# (日期, 淨值, 面額, 收益平準金, 資本平準金)：每次除息前後各一列，與官方配息 0.40/0.53/0.55/0.45/0.55 對照
REAL = [
    ("2024/07/15", "11.84", 15, 1.25, -4.41), ("2024/07/16", "11.24", 15, 0.85, -4.61),
    ("2025/01/16", "12.81", 15, 1.12, -3.31), ("2025/01/17", "12.34", 15, 0.59, -3.25),
    ("2025/07/15", "13.56", 15, 1.11, -2.55), ("2025/07/16", "13.00", 15, 0.56, -2.56),
    ("2026/01/16", "15.45", 15, 0.86, -0.41), ("2026/01/19", "15.01", 15, 0.41, -0.4),
    ("2026/07/15", "15.25", 15, 1.02, -0.77), ("2026/07/16", "14.78", 15, 0.47, -0.69),
    ("2026/10/27", "14.86", 15, 0.8, -0.94),
]
ACTUAL = {"2024-07-16": 0.40, "2025-01-17": 0.53, "2025-07-16": 0.55, "2026-01-19": 0.45, "2026-07-16": 0.55}


def raw(d, nav, base, inc, cap):
    return {"FID": "E0014", "NAV_DT": d, "NAV": nav, "BaseNAV": float(base), "LEVEL_AMT_YN": "Y",
            "INCOME_LEVEL": inc, "RL_GAIN_LEVEL": cap}


def real_rows():
    return [nc.parse_row(raw(*r)) for r in REAL]


class FakePost:
    """依序回放回應；回應是例外就丟出。記錄每次呼叫的 (host, path, token)。"""

    def __init__(self, script):
        self.script, self.calls = list(script), []

    def __call__(self, host, path, body, token, timeout=40):
        self.calls.append((host, path, token, body))
        r = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(r, Exception):
            raise r
        return r(path, body) if callable(r) else r


def ok(data):
    return {"ResultCode": 0, "ResultMsg": "", "Data": data}


TOKEN = ok({"token": "tok"})


def router(nav_rows, etf_list=None):
    def f(path, body):
        if path == "home/AuthToken":
            return TOKEN
        if path == "etf/ETFList":
            return ok({"Data": etf_list or []})
        start, end = body["StartDate"], body["EndDate"]
        return ok([x for x in nav_rows if start <= x["NAV_DT"].replace("/", "-") <= end])
    return f


def client(post, **kw):
    return nc.Client(post=post, sleep=lambda s: None, **kw)


def test_parse_row_converts_and_rejects_incomplete():
    r = nc.parse_row(raw("2026/10/27", "14.86", 15, 0.8, -0.94))
    assert r == dict(date="2026-10-27", nav=14.86, base=15.0, income=0.8, capital=-0.94)
    assert nc.parse_row(raw("2026/10/27", "14.86", 15, None, -0.94)) is None
    assert nc.parse_row(raw("bad", "14.86", 15, 0.8, -0.94)) is None
    assert nc.parse_row(raw("2026/10/27", "n/a", 15, 0.8, -0.94)) is None


def test_distribution_events_match_official_payouts():
    ev = nc.distribution_events(real_rows())
    assert [(e["ex_date"], e["paid"]) for e in ev] == sorted(ACTUAL.items())
    assert ev[3]["pre"] == 0.86 and ev[3]["post"] == 0.41 and ev[3]["ratio"] == 0.523
    assert nc.verify_events(ev, ACTUAL) == []


def test_distribution_events_ignore_daily_fee_noise():
    rows = [nc.parse_row(raw(f"2026/03/{d:02d}", "15.0", 15, 0.40 - 0.01 * (d % 2), -0.4)) for d in range(2, 10)]
    assert nc.distribution_events(rows) == []


def test_min_drop_can_catch_small_monthly_payouts():
    rows = [nc.parse_row(raw("2026/03/02", "15.0", 15, 0.30, -0.3)), nc.parse_row(raw("2026/03/03", "15.0", 15, 0.24, -0.3))]
    assert nc.distribution_events(rows) == []
    assert nc.distribution_events(rows, 0.05)[0]["paid"] == 0.06


def test_verify_events_reports_missing_and_mismatch_and_tolerates_shifted_date():
    ev = nc.distribution_events(real_rows())
    assert nc.verify_events(ev, {"2026-07-17": 0.55}) == []  # 假日讓淨值日期偏移 1 天
    assert "官方配息 0.6" in nc.verify_events(ev, {"2026-07-16": 0.6})[0]
    assert "偵測不到" in nc.verify_events(ev, {"2026-03-01": 0.5})[0]


def test_bad_sum_rows_flags_changed_meaning():
    assert nc.bad_sum_rows(real_rows()) == []  # 實際資料面額＋收益＋資本＝淨值
    broken = [nc.parse_row(raw("2026/10/27", "10.00", 15, 0.8, -0.94))]
    assert nc.bad_sum_rows(broken) == ["2026-10-27"]


def test_health_stale_and_empty_and_broken_columns():
    good = [nc.parse_row(raw("2026/10/27", "14.86", 15, 0.8, -0.94))]
    assert nc.health(good, date(2026, 10, 28)) == []
    assert "落後 15 天" in nc.health(good, date(2026, 11, 11))[0]
    assert "少於 2" in nc.health(good, date(2026, 10, 28), min_rows=2)[0]
    broken = [nc.parse_row(raw(f"2026/10/{d:02d}", "10.0", 15, 0.8, -0.94)) for d in range(1, 10)]
    assert "對不上淨值" in nc.health(broken, date(2026, 10, 10))[0]


def test_client_refreshes_token_when_expired():
    post = FakePost([TOKEN, {"ResultCode": 1, "ResultMsg": "Token 無效或過期"}, TOKEN, ok([{"x": 1}])])
    assert client(post).call("product/GetNAV", {}) == [{"x": 1}]
    assert [c[1] for c in post.calls] == ["home/AuthToken", "product/GetNAV", "home/AuthToken", "product/GetNAV"]


def test_client_retries_waf_html_and_rotates_host():
    post = FakePost([ValueError("Expecting value"), TOKEN, ok([1])])
    c = client(post)
    assert c.call("x/y", {}) == [1]
    hosts = [h for h, *_ in post.calls]
    assert hosts[0] != hosts[1]  # 第一次失敗後換下一個網域


def test_client_gives_up_after_retries_with_reason():
    post = FakePost([OSError("timeout")])
    with pytest.raises(nc.NavError, match="重試 3 次仍失敗.*timeout"):
        client(post, retries=3).call("x/y", {})
    assert [c[1] for c in post.calls].count("home/AuthToken") == 3  # 每次失敗都丟掉 token，下一圈重取


def test_client_token_failure_is_fatal_and_clear():
    post = FakePost([{"ResultCode": 5, "ResultMsg": "維護中"}])
    with pytest.raises(nc.NavError, match="取 token 失敗：維護中"):
        client(post).call("x/y", {})


def test_resolve_fid_known_and_lookup_and_unknown():
    c = client(FakePost([router([], [{"ETF_ID": "00934", "FID": "E0024"}])]))
    assert nc.resolve_fid(c, "00882") == "E0014"  # 已知對照不連網
    assert nc.resolve_fid(c, "00934") == "E0024"
    with pytest.raises(nc.NavError, match="沒有 99999"):
        nc.resolve_fid(c, "99999")


def test_fetch_nav_chunks_merges_and_sorts():
    rows = [raw(*r) for r in REAL]
    post = FakePost([router(rows)])
    got = nc.fetch_nav(client(post), "E0014", date(2024, 7, 1), date(2026, 10, 28), chunk_days=400)
    assert [r["date"] for r in got] == sorted(r["date"] for r in got) and len(got) == len(REAL)
    assert sum(1 for c in post.calls if c[1] == "product/GetNAV") == 3  # 850 天 / 400 天 → 3 段
    assert nc.fetch_nav(client(FakePost([router(rows)])), "E0014", date(2026, 10, 27), date(2026, 10, 27))[0]["income"] == 0.8


def test_fetch_nav_empty_and_bad_range_fail_clearly():
    with pytest.raises(nc.NavError, match="沒有淨值組成資料"):
        nc.fetch_nav(client(FakePost([router([])])), "E9999", date(2026, 1, 1), date(2026, 1, 31))
    with pytest.raises(nc.NavError, match="晚於"):
        nc.fetch_nav(client(FakePost([router([])])), "E0014", date(2026, 2, 1), date(2026, 1, 1))


def test_main_writes_csv_and_verifies(tmp_path, capsys):
    out = tmp_path / "n.csv"
    code = nc.main(["00882", "--start", "2024-07-01", "--end", "2026-10-28", "--csv", str(out), "--events",
                    "--verify", ",".join(f"{d}:{v}" for d, v in ACTUAL.items())],
                   client=client(FakePost([router([raw(*r) for r in REAL])])), today=date(2026, 10, 28))
    err = capsys.readouterr().err
    assert code == 0 and err == ""  # 官方對照一致、健康檢查通過
    with open(out, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["日期", "淨值", "面額", "收益平準金", "資本平準金"] and rows[-1][0] == "2026/10/27"


def test_main_json_output_and_exit_codes(capsys):
    good = [raw("2026/10/27", "14.86", 15, 0.8, -0.94)]
    code = nc.main(["00882", "--json"], client=client(FakePost([router(good)])), today=date(2026, 10, 28))
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["latest"] == dict(nav=14.86, income=0.8, capital=-0.94) and out["fid"] == "E0014"
    assert nc.main(["00882"], client=client(FakePost([router([])])), today=date(2026, 10, 28)) == 1
    assert "[Error]" in capsys.readouterr().err
    assert nc.main(["00882", "--min-drop", "0.05"], client=client(FakePost([router(good)])), today=date(2026, 11, 28)) == 1
