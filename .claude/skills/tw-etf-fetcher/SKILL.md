---
name: tw-etf-fetcher
description: 台股 ETF 專用資料管線與穿透分析工具。負責抓取全市場 ETF 股號清單、解析各 ETF 完整成分股與持股權重、執行投資組合穿透分析（Look-through），並支援一鍵生成 DCS 建模卡片。
---

# 台股 ETF 資料管線與成分股穿透分析技能（tw-etf-fetcher）

本技能為台股 ETF 專用資料管線，專門處理全市場 ETF 清單、底層成分股持股穿透、資產曝險分析與自動化 DCS 建模卡片建構。

---

## 1. 核心功能

1. **全市場 ETF 清單盤點**：連線台灣證券交易所（TWSE）官方端點，獲取全市場 270+ 檔 ETF 清單（支援依高股息、市值型、債券型過濾）。
2. **完整成分股穿透抓取**：精準解析指定 ETF 之 100% 完整底層個股代號、名稱、投資權重（%）與持有股數。
3. **投資組合實質穿透分析（Look-through）**：輸入個人多檔 ETF 持股張數，自動折算加權背後實質持有各個股之總金額與投資組合總佔比，偵測隱形集中度風險。
4. **DCS 建模卡片一鍵建置（Scaffold Model）**：自動將抓取的 ETF 與成分股資料轉換為 `models/<ticker>/cards/` 標準卡片，無縫納入 `portfolio-patrol` 日常巡檢體系。
5. **Google Sheets 雲端同步管線（Sync Sheets）**：將全市場 27 檔 ETF 的 4,300+ 筆成分股與摘要自動匯出為標準 CSV，並同步上傳至「全市場_ETF成分股資料庫」Google Sheets，供前端 `Stock_AIStudio` 免登入 gviz 讀取。

---

## 2. 常用指令

```bash
# 1. 查詢全市場 ETF（支援關鍵字或類型過濾）
python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py list --filter 高息
python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py list --limit 20

# 2. 抓取指定 ETF 之完整成分股與權重
python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py holdings 00878
python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py holdings 00878 00919 0056 --json

# 3. 投資組合穿透分析（計算個人實質持有個股總曝險）
# 例如持有 10 張 00878 與 5 張 00919
python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py lookthrough --portfolio "00878:10,00919:5"

# 4. 為指定 ETF 一鍵建置 DCS 建模卡片（自動放入 models/<ticker>/cards/）
python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py scaffold-model 00878

# 5. 一鍵同步全市場 ETF 成分股與摘要至 Google Sheets 雲端匯流排
python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py sync-sheets
# 6. 產生 ETF 成分股「股利與財報明細」頁（持股、財報、配息、估值一頁看完）
python3 .claude/skills/tw-etf-fetcher/scripts/etf_table.py 00985A out.html [table.json]
```

## 成分股股利與財報明細頁（`etf_table.py`、`etf_page.py`）

- **分層**：持股取 MoneyDJ（資料日期取頁面上的「資料日期」，不是抓取日）；股價 Google Finance（`price-dividend-fetcher`，Yahoo、證交所、櫃買備援）；財報與配息 FinMind（`fundamental-analyzer/scripts/fetchers/finmind_detail.py`，輸出格式同港股版，趨勢、配息率、估值位置共用 `fundamental-analyzer/scripts/fin_trend.py`）；頁面渲染 `scripts/etf_page.py`＋`references/constituents_template.html`，與 00882 港股頁共用同一份範本，市場差異（幣別、說明文字、金融業判斷、有無中期配息）放在 `etf_page.PROFILES`。
- **新增市場或 ETF**：台股 ETF 直接給代號；新市場在 `PROFILES` 加一份設定，再寫一個「持股＋單檔資料」模組，不必動範本。
- **韌性**：FinMind 請求過 `finmind_detail.get`（快取 6 小時、限流退避重試、可用環境變數 `FINMIND_TOKEN` 提高上限）；單檔任何一步失敗只讓該欄空白，並記在輸出摘要的 `errors`、`no_fin`、`no_price`。約 40 秒（50 檔、6 執行緒）。
- **口徑**：殖利率＝近 12 月股息（最近幾次定期分配，季配取 4 次、半年配取 2 次、年配取 1 次，不含特別股息的判斷以類別為準）÷ Google Finance 股價；PE＝股價 ÷ 近四季 EPS，PB 取 FinMind 當日 PBR；配發率＝近 12 月股息 ÷ 近四季 EPS；已付股息＝該年付款的每股現金股利 × 參與股數（近似）。持股以外部位（現金、期貨）不在表內，權重加權殖利率視為 0。
- **已知限制**：季配公司的「當期配息率」留白（只算年配與半年配）；純配股不列入股息；上櫃財報覆蓋以 FinMind 為準，缺值標「無資料」不推估；MOPS、Goodinfo 擋爬蟲不採用；主動式 ETF 持股每日變動，頁首標示持股日期。

---

## 3. 架構與防護規則

1. **唯讀資料庫鐵律**：本技能僅作為資料擷取與運算工廠，嚴禁對 `Investment_Tracker_Core` 進行任何寫入。
2. **客觀專業用語**：所有終端報告與註解維持客觀金融分析用語，嚴禁使用浮誇詞彙。
3. **離線單元測試保證**：全套單元測試內建 Mock 機制，確保在無外網環境下維持 100% 綠燈。
