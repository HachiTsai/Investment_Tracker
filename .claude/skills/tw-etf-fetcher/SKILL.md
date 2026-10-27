---
name: tw-etf-fetcher
description: 台股、港股、美股、日股 ETF 成分股資料管線與穿透分析工具。負責抓取各市場 ETF 的成分股與持股權重（完整或前幾大，標示 coverage）、執行投資組合穿透分析（Look-through）、產出頁面與資料池、寫入各市場的外圍試算表，並支援一鍵生成標的建模卡片。
---

# ETF 資料管線與成分股穿透分析技能（tw-etf-fetcher）

本技能為台股、港股、美股、日股 ETF 的資料管線，處理各市場 ETF 清單、底層成分股持股穿透、資產曝險分析與自動化標的建模卡片建構。

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
# 7.2 美股資料池（持股先查全市場表，表內沒有才用 Yahoo 前幾大，coverage 為 partial；必須用 --etfs 指定）
python3 .claude/skills/tw-etf-fetcher/scripts/etf_pool.py outdir --market us --etfs VOO
# 7.3 日股資料池（持股先查全市場表，表內沒有才用 Yahoo 前幾大，coverage 為 partial；代號為 4 碼，必須用 --etfs 指定）
python3 .claude/skills/tw-etf-fetcher/scripts/etf_pool.py outdir --market jp --etfs 1306,1489,1329
```

## 成分股股利與財報明細頁（`etf_table.py`、`etf_page.py`）

- **分層**：持股取 MoneyDJ（資料日期取頁面上的「資料日期」，不是抓取日）；股價 Google Finance（`price-dividend-fetcher`，Yahoo、證交所、櫃買備援）；財報與配息 FinMind（`fundamental-analyzer/scripts/fetchers/finmind_detail.py`，輸出格式同港股版，趨勢、配息率、估值位置共用 `fundamental-analyzer/scripts/fin_trend.py`）；頁面渲染 `scripts/etf_page.py`＋`references/constituents_template.html`，與 00882 港股頁共用同一份範本，市場差異（幣別、說明文字、金融業判斷、有無中期配息）放在 `etf_page.PROFILES`。
- **日期定義（2026-10-27）**：建立日期（模型卡片的 `last_model_update`）與持股日期（來源標示的資料日期，沒有就填「無」）分開。台股全市場表的日期欄只放建立日期（沒有模型卡片就填「無」），不放持股日期。備援持股與全市場表的持股沒有持股日期，不以抓取當天或檔案時間代替。
- **新增市場或 ETF**：台股 ETF 直接給代號；新市場在 `PROFILES` 加一份設定，再寫一個「持股＋單檔資料」模組，不必動範本。
- **資料池（`etf_pool.py`）**：不給 `--etfs` 時掃描 `models/*/cards/constituents.jsonl`，台股個股達 5 檔的 ETF 都納入；成分股跨 ETF 去重後各抓一次（17 檔 ETF 約 214 檔個股，約 70 秒），限流失敗的個股在執行緒池之後序列重試一輪。輸出的多頁以 `files` 發佈成同一個 Artifact（`index.html` 為入口，頁首下拉切換 ETF）；`pool.json` 的個股與持股兩張表供寫入 Drive 的 All_Market/Taiwan 公開試算表（僅市場公開資料，不含個人持股）。
- **市場介面（`scripts/etf_market.py`）**：每個市場是一份 `Market`，提供代號解析（`parse_code`）、ETF 持股（`holdings`）、個股資料（`stock`）與產業別（`industry`）；台股是 `etf_table.TW`，港股是 `etf_hk.HK`（持股來自中信投信 ETFHoldingWeight，目前只支援 00882，coverage 為 full），美股是 `etf_us.US`（持股先查 Drive 全市場表，由 `etf_drive.py` 只讀取得；表內沒有才用 Yahoo Finance 前幾大，coverage 為 partial），日股是 `etf_jp.JP`（持股同樣先查全市場表，表內沒有才用 Yahoo 前幾大，coverage 為 partial，財報來自 EDINET）；`etf_table`、`etf_pool` 的函式都接受 `market` 參數，`etf_pool --market hk|us|jp` 切換市場。`Market.accept_coverage` 決定採用哪些官方持股：台股與港股只採用 full，美股與日股採用 full 與 partial；不採用時退回 models 卡片備援，連卡片也沒有就停止、不寫檔。持股的 `coverage`（`full`／`partial`／`fallback`）寫進 `pool.json` 的摘要，頁面的持股來源也會標出「前幾大持股」；日股若只有前幾大持股，同樣靠這個欄位標示。
- **安全防線（所有入口共用）**：輸出一律是純代號，不帶 `.TW`、`.TWO`、`.US`、`.JP` 等國別後綴（這類文字上傳 Drive 會被標成危險檔案）；`etf_pool` 寫檔前掃描，出現就整批中止、不寫任何檔案；寫入試算表前過 `guard_sheet_id`，`Investment_Tracker_Core` 一律拒絕；頁面內嵌的 JSON 經 `json_for_script` 跳脫 `< > &`。
- **台幣換算（`scripts/etf_fx.py`）**：港股、美股、日股在抓價前先取一次外幣對新台幣匯率（Google Finance 外匯報價頁，與股價同一來源）；抓不到就印出 `[FX]`、退出碼 1、不寫任何檔案，不沿用舊匯率。匯率與報價時間寫進 `pool.json` 的 `fx`（`currency`、`rate`、`asOf`、`source`），頁面與索引頁也會註明；個股視窗多兩張卡「股價（約新台幣）」與「近 12 月股息（約新台幣）」。外幣市場的每檔多 `pxTwd`、`ttmDivTwd`，`schema_version` 維持 1（新增的都是可選欄位）。匯率只供比較，不是實際成交或入帳金額。台股不抓匯率，輸出與改動前位元組相同（離線比對）。
- **韌性**：FinMind 請求過 `finmind_detail.get`（快取 6 小時、限流退避重試、可用環境變數 `FINMIND_TOKEN` 提高上限）；單檔任何一步失敗只讓該欄空白，並記在輸出摘要的 `errors`、`no_fin`、`no_price`。約 40 秒（50 檔、6 執行緒）。
- **健康門檻與限流**：每個市場的 `Market` 帶 `limits`（並行 6 檔、補抓 1 次、補抓前等 3 秒、整段抓取總時間上限 900 秒）與 `gate`。資料池門檻：ETF 數量 ≥ 15、缺價與缺財報合計 ≤ 10、異常 ETF 0 檔；全市場試算表門檻：ETF_Summary ≥ 200 列、ETF_Constituents ≥ 10000 列。`etf_pool --gate` 與 `etf_fetcher sync-sheets --gate` 共用 `etf_market.gate_reasons` 判定，未達門檻退出碼 1。超過總時間上限就中止、印出 `[Time Limit]`、不寫任何檔案，退出碼 1；單次 HTTP 請求的逾時仍由各抓取模組設定。港股門檻：ETF 數量 ≥ 1、缺價與缺財報合計 ≤ 10、每檔持股檔數 ≥ 45；異常 ETF 不擋（港股個股的歷史價、現金流缺漏很常見，只讓該欄空白）。美股門檻：ETF 數量 ≥ 1、缺價與缺財報合計 ≤ 10、每檔持股檔數 ≥ 1；異常 ETF 不擋（美股的財報缺漏同樣只讓該欄空白）。日股門檻：ETF 數量 ≥ 1、缺價與缺財報合計 ≤ 10、異常 ETF 最多 1 檔、每檔持股檔數 ≥ 1；財報缺漏同樣只讓該欄空白。
- **口徑**：殖利率＝近 12 月股息（最近幾次定期分配，季配取 4 次、半年配取 2 次、年配取 1 次，不含特別股息的判斷以類別為準）÷ Google Finance 股價；PE＝股價 ÷ 近四季 EPS，PB 取 FinMind 當日 PBR；配發率＝近 12 月股息 ÷ 近四季 EPS；已付股息＝該年付款的每股現金股利 × 參與股數（近似）。持股以外部位（現金、期貨）不在表內，權重加權殖利率視為 0。
- **已知限制**：季配公司的「當期配息率」留白（只算年配與半年配）；純配股不列入股息；上櫃財報覆蓋以 FinMind 為準，缺值標「無資料」不推估；MOPS、Goodinfo 擋爬蟲不採用；主動式 ETF 持股每日變動，頁首標示持股日期。港股頁頭條是每單位台幣年股利（毛額）＝Σ 持股數 × 近 12 月股息 × 匯率 ÷ 在外流通單位數，單位數與每單位淨值來自中信投信的基金資料，口徑與 hk-market-data 的 00882 頁相同；匯率來源與股利資料來源不同，數字會略有差異，與該頁的對帳仍待 CTBC 恢復後補跑。持股來源沒有單位數時（例如 CTBC 回 403，改用 models 備援卡片），頭條退回成分股殖利率的權重加權平均。美股頁：持股只有 Yahoo 前幾大（通常約 10 檔），coverage 為 partial，頁面與 pool.json 標示；財報只取 10-K 年度數字（20-F 外國發行人不在範圍，財報欄留空）；PE 與配發率以最近一份年報的 EPS 計，不是近四季；股利只有除息日與金額，沒有付款日與類別，「當年度已配發」與「當期配息率」留白；金融股沒有產業分類，現金流與負債規則不排除銀行與保險；股價、股利與財報都是美元，比率不換算；頁面另附台幣參考值（見上方「台幣換算」）。持股不完整時，整體本益比卡片寫成「占基金 X%」（前幾大持股合計），不寫成「權重 100%」；完整持股的頁面文字不變。日股頁：持股只有 Yahoo 前幾大（實測 3 檔 ETF 各約 10 檔，合計占基金約 24%～48%），coverage 為 partial，頁面與 pool.json 標示；財報來自 EDINET 有價證券報告書（合併報表，近五年經營指標摘要），IFRS、日本會計準則與美國會計準則（如野村）的標籤各自對照，取第一個有值的；負債比只有最近兩年（合併資產負債表）；每股盈餘在分割前後不可比，分割前的年度留空（淨利不受影響）；PB 用期末流通股數（發行股數扣掉自己株式），美國會計準則的股東權益含非控制權益；銀行、保險、證券（業種別標籤 BNK、INS、SEC）的現金流覆蓋與負債比留空；自由現金流＝營業現金流 − 有形固定資產取得（各公司標籤不同，取到哪個用哪個，Toyota 不含出租設備與無形資產）；配發率以最近年報的 EPS 計，不是近四季；股利只有除息日與金額（Yahoo），上財年以日曆年合計計，3 月決算公司的期中與期末配息不完全對應財年；股價、股利與財報都是日圓，比率不換算；頁面另附台幣參考值（見上方「台幣換算」）；股價先 Google Finance，失敗改 Yahoo。EDINET 的日期清單與報告書快取在 `~/.cache/investment_tracker`，容器重開即清空；實機測試時快取已熱，未量測冷啟動時間。公司在財報期末之後才分割時，EPS 與股數仍是分割前的口徑，PE、PB 可能失真，本次實機未見此情形。

---

## 3. 市場與模組對照

本技能名稱沿用 `tw-etf-fetcher`，實際涵蓋台、港、美、日四個市場；腳本是平的，以檔名分工。改某個市場時先看下表。

| 市場 | 持股來源 | 市場介面（`Market`） | 專屬模組 | 財報與配息 |
| :--- | :--- | :--- | :--- | :--- |
| 台股 | MoneyDJ（全市場 ETF 清單來自證交所） | `etf_table.TW` | `etf_holdings_scraper.py`（完整持股）、`etf_list_scraper.py`（ETF 清單） | `fundamental-analyzer` 的 FinMind |
| 港股 | 中信投信 ETFHoldingWeight（目前只有 00882） | `etf_hk.HK` | `etf_hk.py` | 東方財富 |
| 美股 | Drive 全市場表，沒有才用 Yahoo 前幾大 | `etf_us.US` | `etf_us.py`、`etf_drive.py` | SEC EDGAR |
| 日股 | Drive 全市場表，沒有才用 Yahoo 前幾大 | `etf_jp.JP` | `etf_jp.py`、`etf_drive.py` | EDINET |

四個市場共用的模組（新增或修改市場行為時不必重複實作）：

| 模組 | 負責 |
| :--- | :--- |
| `etf_market.py` | `Market` 介面、健康門檻與限流、純代號與國別後綴掃描、`guard_sheet_id`（拒絕 Core） |
| `etf_pool.py`、`etf_table.py` | 資料池與單檔頁的流程（`--market` 切換市場） |
| `etf_page.py` | 頁面渲染與各市場的頁面設定（`PROFILES`） |
| `etf_fx.py` | 外幣對新台幣匯率（港、美、日） |
| `etf_sheets_sync.py`、`etf_sheets_io.py` | 寫入各市場的外圍試算表與本機 CSV |
| `etf_lookthrough.py`、`etf_model_scaffolder.py` | 穿透曝險分析、一鍵生成標的建模卡片 |
| `etf_fetcher.py` | 命令列入口（`list`、`holdings`、`lookthrough`、`scaffold-model`、`set-tier`、`sync-sheets`） |

---

## 4. 架構與防護規則

1. **唯讀資料庫鐵律**：本技能僅作為資料擷取與運算工廠，嚴禁對 `Investment_Tracker_Core` 進行任何寫入。
2. **客觀專業用語**：所有終端報告與註解維持客觀金融分析用語，嚴禁使用浮誇詞彙。
3. **離線單元測試保證**：全套單元測試內建 Mock 機制，確保在無外網環境下維持 100% 綠燈。
