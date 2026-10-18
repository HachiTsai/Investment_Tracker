# 台股 ETF 資料源規格與快取架構（TW ETF Architecture Reference）

本文件為 `tw-etf-fetcher` 技能之資料源、快取機制與 DCS 建模整合規格書（Single Source of Truth, SSOT）。

---

## 1. 資料源架構（多層備援與零成本官方端點）

| 資料層級 | 主要資料源 | 備援資料源 | 更新頻率 | 特點 |
| :--- | :--- | :--- | :--- | :--- |
| **全市場 ETF 清單** | 證交所 OpenAPI `t187ap47_L` (上市基金彙總) | FinMind `TaiwanStockInfo` | 每日開盤前 | 官方權威、涵蓋 272+ 檔代號、類型、投信公司與追蹤指數 |
| **ETF 完整成分股** | MoneyDJ ETF 持股明細 (`Basic0007B.xdjhtm`) | `yfinance.Ticker.funds_data` (前十大持股) | 每日盤後 | 100% 完整穿透持股、投資比例 (%) 與持有股數 |
| **即時行情與淨值** | `price-dividend-fetcher` (TWSE / Google Finance) | Yahoo Finance / TWSE MIS | 盤中即時 / 盤後收盤 | 支援市價、折溢價與淨值連動 |

---

## 2. 輸出格式規格

### 2.1 結構化 JSON 輸出（`--format json`）

```json
{
  "ticker": "00878",
  "name": "國泰永續高股息",
  "as_of_date": "2026-10-18",
  "source": "MoneyDJ",
  "total_count": 30,
  "total_weight_pct": 99.85,
  "constituents": [
    {
      "symbol": "2891.TW",
      "name": "中信金",
      "weight_pct": 10.16,
      "shares": 926187000
    },
    {
      "symbol": "2382.TW",
      "name": "廣達",
      "weight_pct": 8.63,
      "shares": 179841000
    }
  ]
}
```

### 2.2 Google Sheets `ETF_Constituents` 格式

依據 `architecture/情資管線與APP整合架構.md` 規範：

- 欄位：`etf_id | etf_name | constituent_ticker | constituent_name | weight_pct | shares | update_date`

---

## 3. DCS 建模工程卡片映射（Card Mapping）

當執行 `scaffold-model <ticker>` 時，系統自動建立以下四張卡片：

1. **標的卡片（`models/<ticker>/cards/ticker.yml`）**：
   - 記錄標的代號、全名、發行投信、追蹤指數與總費用率。
2. **成分股卡片庫（`models/<ticker>/cards/constituents.jsonl`）**：
   - 記錄全體成分股之個股代號、權重比例與持有股數。
3. **50 萬被動收入迴路卡片（`models/<ticker>/cards/loop_dividend_500k.yml`）**：
   - 納入個人整體股利目標收斂體系。
4. **高息陷阱互鎖卡片（`models/<ticker>/cards/interlock_yield_trap.yml`）**：
   - 配息持續性與成分股集中度風控互鎖。
