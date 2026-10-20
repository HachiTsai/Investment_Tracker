"""個股卡片建立模組 (Stock Card Scaffolder)。

為單一個股建立 models/<代號>/cards/ticker.yml（category: STOCK），
與 ETF 卡片同構，讓 portfolio-patrol 可一併巡檢。價格與近 12 個月配息不寫死，巡檢時現場抓取。
"""

import datetime
from pathlib import Path
from typing import Optional


def _q(value: Optional[str]) -> str:
    """YAML 字串；None 輸出 null。"""
    return "null" if value is None else '"' + str(value).replace('"', "'") + '"'


def scaffold_stock_card(
    code: str,
    symbol: str,
    yf_symbol: str,
    title: str,
    repo_root: Path,
    sector: str = "",
    nature_tag: str = "",
    currency: str = "TWD",
    exchange: str = "TWSE",
    related_etfs: Optional[list] = None,
    dividend_currency: Optional[str] = None,
    frequency: str = "",
    last_dps: Optional[float] = None,
    last_ex_date: Optional[str] = None,
    last_source: Optional[str] = None,
    lot_shares: int = 1000,
    models_dir: Optional[Path] = None,
) -> Path:
    """建立 models/<code>/cards/ticker.yml；已存在時不覆蓋，避免蓋掉人工補充的論點欄位。"""
    cards_dir = (models_dir or repo_root / "models") / code / "cards"
    target = cards_dir / "ticker.yml"
    if target.exists():
        raise FileExistsError(f"{target} 已存在，請直接編輯")
    cards_dir.mkdir(parents=True, exist_ok=True)

    etfs = ", ".join(f'"{e}"' for e in (related_etfs or []))
    last_dps_str = "null" if last_dps is None else str(last_dps)
    text = f"""id: card:ticker:{code}
type: ticker
schema_version: 1.1.0
ticker: "{code}"
symbol: "{symbol}"            # price-dividend-fetcher 格式（交易所:代號）
yf_symbol: "{yf_symbol}"      # fundamental-analyzer / Yahoo 格式
title: {_q(title)}
currency: {currency}
exchange: {exchange}
category: STOCK
sector: {_q(sector)}
nature_tag: {_q(nature_tag)}
related_etfs: [{etfs}]
last_model_update: "{datetime.date.today().isoformat()}"

# 股利輪廓：近 12 個月配息由 price-dividend-fetcher 現場抓取；annual_dps_baseline 僅在抓不到時降級使用
dividend:
  currency: {_q(dividend_currency or currency)}
  frequency: {_q(frequency)}
  annual_dps_baseline: null
  last_declared:
    dps: {last_dps_str}
    ex_date: {_q(last_ex_date)}
    source: {_q(last_source)}

# 對年股利 50 萬目標的貢獻：以每 lot_shares 股為單位，不記個人持股；稅後留存率未查證前留 null（視為 1.0）
contribution:
  lot_shares: {lot_shares}
  tax_retention_rate: null

# 觀點欄位（人工維護；事實須附出處，推論明確標示為觀點）
thesis:
  summary: null
  risks: null
  tracking: []

fail_safe:
  max_stale_days: 5
"""
    target.write_text(text, encoding="utf-8")
    return target
