"""外幣對新台幣匯率（etf_fx）離線測試：頁面片段與網路錯誤都用假資料，不連網。"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import etf_fx  # noqa: E402

TS = 1793034600  # 2026-10-26 17:10 UTC，HKD-TWD 報價頁上的時間戳
# 片段取自 2026-10-26 的 Google Finance HKD-TWD 頁面（報價陣列的排列相同）
HKD_PAGE = (
    'AF_initDataCallback({key: \'ds:8\', data:[[[[null,null,"HKD-TWD","HKD / TWD",4.155168,0,0,null,'
    '["/g/11bvvzwj0l",null,"HKD / TWD",3,null,[4.152888,-0.00228,-0.05487142,4,4,3],null,4.155168,null,null,null,'
    f'[{TS}],null,0]]]]}});'
)


def test_parse_rate_reads_price_and_quote_time():
    got = etf_fx.parse_rate(HKD_PAGE, "HKD")
    assert got == dict(currency="HKD", rate=4.155168, source="Google Finance",
                       as_of=datetime.fromtimestamp(TS, timezone.utc).isoformat(timespec="seconds"))


def test_page_for_another_pair_does_not_match():
    with pytest.raises(ValueError, match="找不到匯率"):
        etf_fx.parse_rate(HKD_PAGE, "USD")


def test_missing_quote_is_a_value_error():
    with pytest.raises(ValueError, match="找不到匯率"):
        etf_fx.parse_rate("<html>no quote</html>", "HKD")


def test_implausible_rate_is_rejected():
    with pytest.raises(ValueError, match="超出合理範圍"):
        etf_fx.parse_rate(HKD_PAGE.replace("4.155168", "0"), "HKD")


def test_bad_currency_code_is_refused_before_building_a_url():
    with pytest.raises(ValueError, match="幣別代碼不合法"):
        etf_fx.parse_rate(HKD_PAGE, "HK/D")


def test_twd_is_identity_and_never_touches_the_network():
    def boom(url):
        raise AssertionError("台幣不應連網")

    assert etf_fx.fetch_rate("TWD", get=boom) == dict(currency="TWD", rate=1.0, as_of=None, source="本位幣")


def test_network_errors_are_retried_then_become_runtime_error():
    calls = []

    def down(url):
        calls.append(url)
        raise OSError("timeout")

    with pytest.raises(RuntimeError, match="匯率抓取失敗"):
        etf_fx.fetch_rate("HKD", get=down, retries=2, wait=0)
    assert calls == ["https://www.google.com/finance/quote/HKD-TWD?hl=en"] * 3


def test_one_network_error_recovers_on_retry():
    responses = [OSError("connection reset"), HKD_PAGE]

    def flaky(url):
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    assert etf_fx.fetch_rate("HKD", get=flaky, retries=1, wait=0)["rate"] == 4.155168


def test_page_format_errors_are_not_retried():
    calls = []

    def bad_page(url):
        calls.append(url)
        return "<html></html>"

    with pytest.raises(ValueError):
        etf_fx.fetch_rate("HKD", get=bad_page, retries=2, wait=0)
    assert len(calls) == 1
