---
name: tw-etf-fetcher
description: 台股 ETF 專用資料管線與穿透分析工具。負責抓取全市場 ETF 股號清單、解析各 ETF 完整成分股與持股權重、執行投資組合穿透分析（Look-through），並支援一鍵生成標的建模卡片。
---

# 台股 ETF 資料管線與成分股穿透分析技能（tw-etf-fetcher）

本技能為台股 ETF 專用資料管線，專門處理全市場 ETF 清單、底層成分股持股穿透、資產曝險分析與自動化標的建模卡片建構。

---

## 1. 核心功能

1. **全市場 ETF 清單盤點**：連線台灣證券交易所（TWSE）官方端點，獲取全市場 270+ 檔 ETF 清單（支援依高股息、市值型、債券型過濾）。
2. **完整成分股穿透抓取**：精準解析指定 ETF 之 100% 完整底層個股代號、名稱、投資權重（%）與持有股數。
3. **投資組合實質穿透分析（Look-through）**：輸入個人多檔 ETF 持股張數，自動折算加權背後實質持有各個股之總金額與投資組合總佔比，偵測隱形集中度風險。
4. **標的建模卡片一鍵建置（Scaffold Model）**：自動將抓取的 ETF 與成分股資料轉換為 `models/<ticker>/cards/` 標準卡片，無縫納入 `portfolio-patrol` 日常巡檢體系。
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

# 4. 為指定 ETF 一鍵建置標的建模卡片（預設為 pool 資料池，可指定 --tier core 納入核心團隊）
python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py scaffold-model 00922
python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py scaffold-model 00922 --tier core

# 4.1 調整標的分級（core: 核心團隊，參與每日巡檢 / pool: 資料池，僅供穿透分析）
python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py set-tier 00922 core
python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py set-tier 00922 pool

# 5. 一鍵同步全市場 ETF 成分股與摘要至 Google Sheets 雲端匯流排
python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py sync-sheets
# 6. 產生 ETF 成分股「股利與財報明細」頁（持股、財報、配息、估值一頁看完）
python3 .claude/skills/tw-etf-fetcher/scripts/etf_table.py 00985A out.html [table.json]
# 7. 多檔台股 ETF 資料池：成分股去重只抓一次，輸出 index.html＋每檔 ETF 一頁＋pool.json
python3 .claude/skills/tw-etf-fetcher/scripts/etf_pool.py outdir [--etfs 0050,0056] [--models-dir models]
# 7.1 港股資料池（目前只支援 00882，必須用 --etfs 指定；持股來自中信投信）
python3 .claude/skills/tw-etf-fetcher/scripts/etf_pool.py outdir --market hk --etfs 00882
# 7.2 美股資料池（持股為 Yahoo 前幾大持股，coverage 為 partial；必須用 --etfs 指定）
python3 .claude/skills/tw-etf-fetcher/scripts/etf_pool.py outdir --market us --etfs VOO
```

## 成分股股利與財報明細頁（`etf_table.py`、`etf_page.py`）

- **分層**：持股取 MoneyDJ（資料日期取頁面上的「資料日期」，不是抓取日）；股價 Google Finance（`price-dividend-fetcher`，Yahoo、證交所、櫃買備援）；財報與配息 FinMind（`fundamental-analyzer/scripts/fetchers/finmind_detail.py`，輸出格式同港股版，趨勢、配息率、估值位置共用 `fundamental-analyzer/scripts/fin_trend.py`）；頁面渲染 `scripts/etf_page.py`＋`references/constituents_template.html`，與 00882 港股頁共用同一份範本，市場差異（幣別、說明文字、金融業判斷、有無中期配息）放在 `etf_page.PROFILES`。
- **新增市場或 ETF**：台股 ETF 直接給代號；新市場在 `PROFILES` 加一份設定，再寫一個「持股＋單檔資料」模組，不必動範本。
- **資料池（`etf_pool.py`）**：不給 `--etfs` 時掃描 `models/*/cards/constituents.jsonl`，台股個股達 5 檔的 ETF 都納入；成分股跨 ETF 去重後各抓一次（17 檔 ETF 約 214 檔個股，約 70 秒），限流失敗的個股在執行緒池之後序列重試一輪。輸出的多頁以 `files` 發佈成同一個 Artifact（`index.html` 為入口，頁首下拉切換 ETF）；`pool.json` 的個股與持股兩張表供寫入 Drive 的 All_Market/Taiwan 公開試算表（僅市場公開資料，不含個人持股）。
- **市場介面（`scripts/etf_market.py`）**：每個市場是一份 `Market`，提供代號解析（`parse_code`）、ETF 持股（`holdings`）、個股資料（`stock`）與產業別（`industry`）；台股是 `etf_table.TW`，港股是 `etf_hk.HK`（持股來自中信投信 ETFHoldingWeight，目前只支援 00882，coverage 為 full），美股是 `etf_us.US`（持股為 Yahoo Finance 前幾大持股，coverage 為 partial）；`etf_table`、`etf_pool` 的函式都接受 `market` 參數，`etf_pool --market hk|us` 切換市場。`Market.accept_coverage` 決定採用哪些官方持股：台股與港股只採用 full，美股採用 full 與 partial；不採用時退回 models 卡片備援，連卡片也沒有就停止、不寫檔。持股的 `coverage`（`full`／`partial`／`fallback`）寫進 `pool.json` 的摘要，頁面的持股來源也會標出「前幾大持股」；日股若只有前幾大持股，同樣靠這個欄位標示。
- **安全防線（所有入口共用）**：輸出一律是純代號，不帶 `.TW`、`.TWO`、`.US`、`.JP` 等國別後綴（這類文字上傳 Drive 會被標成危險檔案）；`etf_pool` 寫檔前掃描，出現就整批中止、不寫任何檔案；寫入試算表前過 `guard_sheet_id`，`Investment_Tracker_Core` 一律拒絕；頁面內嵌的 JSON 經 `json_for_script` 跳脫 `< > &`。
- **韌性**：FinMind 請求過 `finmind_detail.get`（快取 6 小時、限流退避重試、可用環境變數 `FINMIND_TOKEN` 提高上限）；單檔任何一步失敗只讓該欄空白，並記在輸出摘要的 `errors`、`no_fin`、`no_price`。約 40 秒（50 檔、6 執行緒）。
- **健康門檻與限流**：每個市場的 `Market` 帶 `limits`（並行 6 檔、補抓 1 次、補抓前等 3 秒、整段抓取總時間上限 900 秒）與 `gate`。資料池門檻：ETF 數量 ≥ 15、缺價與缺財報合計 ≤ 10、異常 ETF 0 檔；全市場試算表門檻：ETF_Summary ≥ 200 列、ETF_Constituents ≥ 10000 列。`etf_pool --gate` 與 `etf_fetcher sync-sheets --gate` 共用 `etf_market.gate_reasons` 判定，未達門檻退出碼 1。超過總時間上限就中止、印出 `[Time Limit]`、不寫任何檔案，退出碼 1；單次 HTTP 請求的逾時仍由各抓取模組設定。港股門檻：ETF 數量 ≥ 1、缺價與缺財報合計 ≤ 10、每檔持股檔數 ≥ 45；異常 ETF 不擋（港股個股的歷史價、現金流缺漏很常見，只讓該欄空白）。美股門檻：ETF 數量 ≥ 1、缺價與缺財報合計 ≤ 10、每檔持股檔數 ≥ 1；異常 ETF 不擋（美股的財報缺漏同樣只讓該欄空白）。
- **口徑**：殖利率＝近 12 月股息（最近幾次定期分配，季配取 4 次、半年配取 2 次、年配取 1 次，不含特別股息的判斷以類別為準）÷ Google Finance 股價；PE＝股價 ÷ 近四季 EPS，PB 取 FinMind 當日 PBR；配發率＝近 12 月股息 ÷ 近四季 EPS；已付股息＝該年付款的每股現金股利 × 參與股數（近似）。持股以外部位（現金、期貨）不在表內，權重加權殖利率視為 0。
- **已知限制**：季配公司的「當期配息率」留白（只算年配與半年配）；純配股不列入股息；上櫃財報覆蓋以 FinMind 為準，缺值標「無資料」不推估；MOPS、Goodinfo 擋爬蟲不採用；主動式 ETF 持股每日變動，頁首標示持股日期。港股頁頭條是成分股殖利率的權重加權平均（比率不需換算），不是每單位台幣股利；每單位台幣股利待 PR 6 的公開匯率來源併入，所以與 00882 既有頁的頭條數字不同。美股頁：持股只有 Yahoo 前幾大（通常約 10 檔），coverage 為 partial，頁面與 pool.json 標示；財報只取 10-K 年度數字（20-F 外國發行人不在範圍，財報欄留空）；PE 與配發率以最近一份年報的 EPS 計，不是近四季；股利只有除息日與金額，沒有付款日與類別，「當年度已配發」與「當期配息率」留白；金融股沒有產業分類，現金流與負債規則不排除銀行與保險；股價、股利與財報都是美元，頁面不換算新台幣（待 PR 6）。持股不完整時，整體本益比卡片寫成「占基金 X%」（前幾大持股合計），不寫成「權重 100%」；完整持股的頁面文字不變。

---

## 3. 架構與防護規則

1. **唯讀資料庫鐵律**：本技能僅作為資料擷取與運算工廠，嚴禁對 `Investment_Tracker_Core` 進行任何寫入。
2. **客觀專業用語**：所有終端報告與註解維持客觀金融分析用語，嚴禁使用浮誇詞彙。
3. **離線單元測試保證**：全套單元測試內建 Mock 機制，確保在無外網環境下維持 100% 綠燈。
