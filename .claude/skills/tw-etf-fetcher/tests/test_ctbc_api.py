"""中信投信請求層：節流、token 共用、防護攔截不重試。全部注入假的 opener 與時鐘，不連網。"""
import io
import json
import urllib.error

import pytest

import ctbc_api
import nav_composition as nc


@pytest.fixture(autouse=True)
def fresh_state():
    ctbc_api.reset()
    yield
    ctbc_api.reset()


class FakeClock:
    """假時鐘：sleep 會把時間往前推，模擬真的等待。"""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def opener_for(items):
    """依序回應：項目是 dict（JSON 回應）或例外（直接拋出）；最後一個項目會重複使用。記錄每次請求的網址。"""
    queue = list(items)
    calls = []

    def opener(req, timeout=40):
        calls.append(req.full_url)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return FakeResp(item)

    opener.calls = calls
    return opener


def ok(data):
    return {"ResultCode": 0, "ResultMsg": "", "Data": data}


def http403(url):
    return urllib.error.HTTPError(url, 403, "Forbidden", {}, io.BytesIO(b"<html>Incapsula</html>"))


def test_consecutive_requests_are_spaced_by_min_interval():
    clock = FakeClock()
    op = opener_for([ok({"a": 1}), ok({"b": 2})])
    ctbc_api.send("etf/ETFList", {}, "t", sleep=clock.sleep, clock=clock, opener=op)
    ctbc_api.send("etf/ETFList", {}, "t", sleep=clock.sleep, clock=clock, opener=op)
    assert clock.sleeps == [ctbc_api.MIN_INTERVAL]


def test_first_request_does_not_wait():
    clock = FakeClock()
    ctbc_api.send("etf/ETFList", {}, "t", sleep=clock.sleep, clock=clock, opener=opener_for([ok({})]))
    assert clock.sleeps == []


def test_no_wait_when_enough_time_has_passed():
    clock = FakeClock()
    op = opener_for([ok({}), ok({})])
    ctbc_api.send("x/y", {}, "t", sleep=clock.sleep, clock=clock, opener=op)
    clock.now += 10
    ctbc_api.send("x/y", {}, "t", sleep=clock.sleep, clock=clock, opener=op)
    assert clock.sleeps == []


def test_request_goes_to_host_with_token_query():
    clock = FakeClock()
    op = opener_for([ok([])])
    ctbc_api.send("product/GetNAV", {"FID": "E0014"}, "tok", host="https://h.example/API/",
                  sleep=clock.sleep, clock=clock, opener=op)
    assert op.calls == ["https://h.example/API/product/GetNAV?token=tok"]


def test_auth_token_is_fetched_once_per_host():
    clock = FakeClock()
    op = opener_for([ok({"token": "tok-1"})])
    first = ctbc_api.auth_token(sleep=clock.sleep, clock=clock, opener=op)
    second = ctbc_api.auth_token(sleep=clock.sleep, clock=clock, opener=op)
    assert (first, second) == ("tok-1", "tok-1")
    assert len(op.calls) == 1


def test_auth_failure_raises_and_is_not_cached():
    clock = FakeClock()
    op = opener_for([{"ResultCode": 5, "ResultMsg": "維護中"}])
    with pytest.raises(ctbc_api.CtbcError, match="維護中"):
        ctbc_api.auth_token(sleep=clock.sleep, clock=clock, opener=op)
    assert ctbc_api.cached_token() is None


def test_http_403_is_blocked_and_not_retried():
    clock = FakeClock()
    op = opener_for([http403("https://www.ctbcinvestments.com.tw/API/home/AuthToken")])
    with pytest.raises(ctbc_api.CtbcBlocked):
        ctbc_api.send("home/AuthToken", {}, "t", sleep=clock.sleep, clock=clock, opener=op)
    assert len(op.calls) == 1  # 只送一次，不在這裡重試


def test_result_code_error_forgets_cached_token():
    clock = FakeClock()
    ctbc_api.remember_token(ctbc_api.HOST, "old")
    op = opener_for([{"ResultCode": 1, "ResultMsg": "Token 無效或過期"}])
    ctbc_api.send("product/GetNAV", {}, "old", sleep=clock.sleep, clock=clock, opener=op)
    assert ctbc_api.cached_token() is None


def test_nav_http_post_shares_one_token_across_calls(monkeypatch):
    sent = []

    def fake_send(path, body, token, host=None, timeout=40, **kw):
        sent.append(path)
        return ok({"token": "shared"}) if path == "home/AuthToken" else ok([])

    monkeypatch.setattr(ctbc_api, "send", fake_send)
    first = nc._http_post(ctbc_api.HOST, "home/AuthToken", {}, nc.TOKEN_SEED)
    second = nc._http_post(ctbc_api.HOST, "home/AuthToken", {}, nc.TOKEN_SEED)
    assert first["Data"]["token"] == second["Data"]["token"] == "shared"
    assert sent == ["home/AuthToken"]  # 第二次直接共用，不再送出請求


def test_client_switches_host_once_then_stops_when_all_blocked():
    calls = []

    def post(host, path, body, token, timeout=40):
        calls.append((host, path))
        if path == "home/AuthToken":
            return ok({"token": "t"})
        raise ctbc_api.CtbcBlocked("防護攔截")

    client = nc.Client(post=post, sleep=lambda s: None, hosts=["https://a/", "https://b/"])
    with pytest.raises(nc.NavError, match="所有網域都被"):
        client.call("product/GetNAV", {})
    # 每個網域各試一次，不在同網域重試
    assert calls == [("https://a/", "home/AuthToken"), ("https://a/", "product/GetNAV"),
                     ("https://b/", "home/AuthToken"), ("https://b/", "product/GetNAV")]


def test_client_uses_second_host_when_first_blocked():
    calls = []

    def post(host, path, body, token, timeout=40):
        calls.append(host)
        if host == "https://a/":
            raise ctbc_api.CtbcBlocked("防護攔截")
        return ok({"token": "t"}) if path == "home/AuthToken" else ok([1])

    slept = []
    client = nc.Client(post=post, sleep=slept.append, hosts=["https://a/", "https://b/"])
    assert client.call("product/GetNAV", {}) == [1]
    assert calls == ["https://a/", "https://b/", "https://b/"]
    assert slept == []  # 換網域不退避等待
    assert client.call("product/GetNAV", {}) == [1]
    assert "https://a/" not in calls[3:]  # 被擋的網域本程序內不再使用


def test_call_falls_back_to_second_host_with_its_own_token():
    clock = FakeClock()
    tw, com = ctbc_api.HOSTS  # tw＝第一個網域（被擋），com＝備援

    def opener(req, timeout=40):
        opener.calls.append(req.full_url)
        if req.full_url.startswith(tw):
            raise http403(req.full_url)
        if "AuthToken" in req.full_url:
            return FakeResp(ok({"token": "com-tok"}))
        return FakeResp(ok({"x": 1}))

    opener.calls = []
    assert ctbc_api.HOST == ctbc_api.HOSTS[0] and ctbc_api.HOSTS[0].startswith("https://www.ctbcinvestments.com/")
    r = ctbc_api.call("etf/ETFHoldingWeight", {}, sleep=clock.sleep, clock=clock, opener=opener)
    assert r["Data"] == {"x": 1}
    assert opener.calls == [tw + "home/AuthToken?token=www.ctbcinvestments.com",
                            com + "home/AuthToken?token=www.ctbcinvestments.com",
                            com + "etf/ETFHoldingWeight?token=com-tok"]
    assert ctbc_api.is_blocked(tw) and not ctbc_api.is_blocked(com)
    assert ctbc_api.active_token(sleep=clock.sleep, clock=clock, opener=opener) == "com-tok"
    assert len(opener.calls) == 3  # 已封鎖的網域不再送，token 共用


def test_call_raises_blocked_when_every_host_blocked():
    clock = FakeClock()
    op = opener_for([http403("x")])
    with pytest.raises(ctbc_api.CtbcBlocked, match="所有網域"):
        ctbc_api.call("etf/ETFList", {}, sleep=clock.sleep, clock=clock, opener=op)
    assert len(op.calls) == len(ctbc_api.HOSTS)  # 每個網域只送一次
