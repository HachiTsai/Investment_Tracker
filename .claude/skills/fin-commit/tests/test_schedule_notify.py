import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import schedule_notify as sn  # noqa: E402


class FakeAPI:
    def __init__(self, open_issues=None):
        self.open = open_issues or []
        self.calls = []

    def __call__(self, method, url, token, body=None):
        self.calls.append((method, url.split("/repos/o/r")[-1], body))
        if method == "GET":
            return self.open
        if method == "POST" and url.endswith("/issues"):
            return {"number": 7}
        return {}


def test_failure_excerpt_prefers_key_lines():
    log = "\n".join(["noise"] * 50 + ["❌ [Gate Failed] 超標：12 > 10", "more noise"])
    assert "Gate Failed" in sn.failure_excerpt(log)
    assert sn.failure_excerpt("a\nb\nc") == "a\nb\nc"
    assert len(sn.failure_excerpt("x" * 10000)) <= 3000


def test_notify_fail_opens_issue_then_comments_on_repeat():
    api = FakeAPI()
    msg = sn.notify_fail("o/r", "t", "swing-patrol.yml", "http://run", "schedule", "❌ 原因", req=api)
    assert "已開 Issue #7" in msg
    method, path, body = api.calls[-1]
    assert (method, path) == ("POST", "/issues")
    assert body["title"] == "排程失敗：swing-patrol.yml" and body["labels"] == ["schedule-failure"] and "已執行但失敗" in body["body"]
    api2 = FakeAPI([{"number": 3, "title": "排程失敗：swing-patrol.yml"}, {"number": 4, "title": "排程失敗：market-etf.yml"}])
    assert "追加留言" in sn.notify_fail("o/r", "t", "swing-patrol.yml", "http://run", "schedule", "x", req=api2)
    assert api2.calls[-1][1] == "/issues/3/comments"


def test_notify_resolve_closes_only_matching_issue():
    api = FakeAPI([{"number": 3, "title": "排程失敗：swing-patrol.yml"}])
    assert "已關閉 Issue #3" in sn.notify_resolve("o/r", "t", "swing-patrol.yml", "http://run", req=api)
    assert api.calls[-1][0] == "PATCH" and api.calls[-1][2]["state"] == "closed"
    assert "沒有" in sn.notify_resolve("o/r", "t", "market-etf.yml", "http://run", req=FakeAPI([{"number": 3, "title": "排程失敗：swing-patrol.yml"}]))


def test_main_does_not_fail_when_notify_errors(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setattr(sn, "notify_fail", lambda *a, **k: (_ for _ in ()).throw(OSError("net")))
    assert sn.main(["fail", "--workflow", "x.yml", "--log", str(tmp_path / "none.log")]) == 0
    monkeypatch.delenv("GITHUB_TOKEN")
    assert sn.main(["resolve", "--workflow", "x.yml"]) == 2
