---
type: arch
title: APP讀取清單-Stock_AIStudio
domain: 資料系統
status: 生效
version: 2
created: 2026-10-22
updated: 2026-10-24
tags: [資料系統, ETF]
tickers: [00882]
related: ["[[情資管線與APP整合架構]]"]
---

## 摘要

Stock_AIStudio 以免登入 gviz CSV 讀取的 Drive 試算表盤點與寫入規範（全系統試算表單一真實來源 SSOT）。ID 寫死在 APP 各 service 檔，本清單是 Investment_Tracker 端的對照與全域資料庫註冊表；任何一端新增、更換或停用來源，兩邊同步更新。

## 規則

1. **新增來源先登記**：APP 要讀新的 Sheet 前，先在本清單加一列（ID、分頁、讀取檔、寫入者、更新頻率），再改程式。
2. **以 ID 讀取**：改檔名不影響 APP，換 ID 或改分頁名、欄位名會直接壞，必須同步改 APP。
3. **公開邊界**：所列資料夾皆為知道連結者可檢視，內容不得含個人持股張數或真實成本。持股與交易兩份由排程依 Core 唯讀重建，屬例外，沿用既有授權，不擴大。
4. **排程對齊**：所有寫入 Sheet 之定時任務，必須在 `.claude/workflows/*.md` 具備標準工作流規格。
5. **不刪列防呆原則**：新資料列數少於舊資料時，把多出的舊列清成空字串，嚴禁直接刪列。
6. **文字型別強制鎖定**：代號（`ticker`, `code`, `etf_id`）與日期值強制加 `'` 前綴存成純文字，防 Google Sheets 自動轉型造成 APP 解析破版。
7. **波段觀察 A:X 欄位鐵律**：`波段觀察`（`1pyGzkgas...`）之 A 到 X 共 24 欄欄序由前端 APP 寫死讀取，**絕對禁止在 A 到 X 範圍增刪或調整欄位**；元數據（`lastUpdated`、`executor`）必須放置於獨立分頁或 A:X 以外儲存格。
8. **互鎖與強制補跑（`--force`）**：定時排程比對資料最新日期，相同則略過以防重複寫入；若遇資料修復需重新入庫，必須支援 `--force` 旗標以穿透互鎖。
9. **雙 Agent 代班邊界**：
   - 純資料表（全市場 ETF、波段觀察）支援 Antigravity 本機直寫代班。
   - 雙棲表（00882、台股 ETF）因與 Artifact 視覺頁強綁定，固定由 Claude 雲端排程統籌寫入，防數據脫節。

## 讀取清單（全系統試算表總表）

| 來源 | Drive ID | 分頁 | APP 讀取檔 | 寫入者與工作流 | 更新頻率 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 情報資料庫 | `1BF2xvF0cmyODdN0nXR8QHbOTC3ikqswvSwBboY1cGQo` | 第一分頁（訊號）、評分歷史 | `signalsFeedService.ts` | Claude 排程（風向日報等） | 平日日報 |
| 00882_成分股股利資料庫 | `1Jq599WzoQUDsooZDhJhyK8uaEMgDiLLCoZthWk2WXtw` | 成分股、摘要 | `constituentsFeedService.ts` | Claude 排程（`.claude/workflows/hk-00882-dividend.md`） | 每週五 17:00 |
| 全市場 ETF 成分股資料庫 | `1GIhbRyL-h96ACVjlSSW9YUFMiAItg_SP9Wi0o3WwG70` | ETF_Summary、ETF_Constituents | `constituentsFeedService.ts`（失敗退回 `allMarketEtfSnapshot`） | Claude 排程／本機代班（`.claude/workflows/market-etf-pool.md`） | 每週五 17:10 |
| 持股資料庫 | `1CWLwi1tsQoWaEYm0IOK9aH7NEkENgd71sbz6Y_lpRVI` | 第一分頁 | `portfolioFeedService.ts` | 排程依 Core 唯讀重建 | 依排程 |
| 交易明細資料庫 | `1yFr6OSW6LKWm5wdoc-QoJFXyUotYEd8_YEl_qR-24ks` | 第一分頁 | `portfolioFeedService.ts` | 排程依 Core 唯讀重建 | 依排程 |
| 波段觀察 | `1pyGzkgaspYMYdXOPYerkLsxOMwNwa2yOKuNDrOrrhtQ` | Untitled（A 到 X 共 24 欄） | `swingFeedService.ts` | Claude 排程／本機代班（`.claude/workflows/swing-patrol-sheets.md`） | 平日台北 17:00 |
| 台股ETF成分股資料庫 | `11LXjxIke0u_6-4XbGB4cX3o28It1ool2jBXUtMErIUI` | 個股、ETF持股、摘要 | 目前只供 Artifact 與分析（APP 預備） | Claude 排程（`.claude/workflows/tw-etf-pool.md`） | 每月月初 09:00 |
| 港股 ETF 成分股資料庫 | `1ND1gcxm-fvkx723V-X72QUuwrJvKobCz_etZpUzWrOI` | ETF_Summary、ETF_Constituents | 尚未接入 APP | 手動 GitHub Actions（`.claude/workflows/market-etf-pool.md` §5） | 手動 |
| 美股 ETF 成分股資料庫 | `1qfMn6hbPD4qFmlCAm0fC2zTfEtm9uVjdZYL4YDUrmY4` | ETF_Summary、ETF_Constituents | 尚未接入 APP | 手動 GitHub Actions（同上） | 手動 |
| 日股 ETF 成分股資料庫 | `1XtSRy14KdLMv75g9ShAL6jWpa9XmoUpiSY4Srvuycxc` | ETF_Summary、ETF_Constituents | 尚未接入 APP | 手動 GitHub Actions（同上） | 手動 |

## 試算表欄位 Schema 與寫入防呆契約

### 1. 00882_成分股股利資料庫 (`1Jq599WzoQUDsooZDhJhyK8uaEMgDiLLCoZthWk2WXtw`)

- **分頁「成分股」**：
  - 表頭（第 1 列）：`code,name,weightPct,qty,priceHkd,divTtmHkd,divLfyHkd,chgPct,yieldTtmPct,interim2026`
  - 防呆：`code` 加 `'` 前綴；`px` 為 null 填空字串。
- **分頁「摘要」**：
  - 範圍：A:C (`key,value,note`)。
  - key 依序：`asOf,holdingsAsOf,ttmUnitTwd,lfyUnitTwd,has26,fxHkdToTwd,nav,unitsOutstanding,rows,note,lastUpdated,executor`。
  - 防呆：B 欄每個值（含日期與數字）一律加 `'` 前綴。

### 2. 全市場 ETF 成分股資料庫 (`1GIhbRyL-h96ACVjlSSW9YUFMiAItg_SP9Wi0o3WwG70`)

- **分頁「ETF_Summary」**：
  - 表頭：`etf_id,etf_name,current_price,exchange,category,benchmark,constituent_count,top1_holding,top2_holding,top3_holding,weighted_roe,net_score,div_score,val_score,fric_score,last_model_update`
  - 防呆：自 A1 寫入；`etf_id` 加 `'` 前綴。
  - 元數據隔離：最後同步時間與執行者放置於 R1:S2（A:P 以外儲存格），保障 APP 讀取 A:P 零干擾。
  - 日期（2026-10-27 起）：models 卡片的 `last_model_update` 是建立日期；MoneyDJ 抓到的 ETF 寫入持股日期（MoneyDJ 資料日期）；抓不到的寫「無」，不再寫執行當天。同一欄目前混用兩種日期，拆成兩欄要等 APP 決定（欄位名與欄序固定不可改）。
- **分頁「ETF_Constituents」**：
  - 欄位以 CSV 表頭為準；超過 5,000 列時採分批寫入（每批不超過 1,500 列）。
  - 防呆：`constituent_ticker` 加 `'` 前綴。
  - 元數據隔離：最後同步時間與執行者放置於 I1:J2（A:G 以外儲存格），保障 APP 讀取 A:G 零干擾。
  - 連結防護：同步後自動清除全表超連結樣式，防範 Google Drive 將代號誤判為惡意/釣魚連結。

### 3. 波段觀察 (`1pyGzkgaspYMYdXOPYerkLsxOMwNwa2yOKuNDrOrrhtQ`)

- **分頁「Untitled」**：
  - 表頭 A 到 X 固定 24 欄：`代號,名稱,市場,來源,狀態,收盤,RSI14,20日線,60日線,量比,52週位置%,20日支撐,20日壓力,2xATR停損價,停損距離%,判定依據,更新日,費波那契位置30日,位置幅度%,長期,中期,短期,費波那契3段,三週期組合`。
  - 防呆：若標的 `state` 為 `ERROR`，僅將第 5 欄改「⚠️ 抓取失敗」、第 16 欄寫原因，其餘保留舊值。
  - 元數據隔離：`lastUpdated` 與 `executor` 放置於獨立元資料分頁或 A:X 以外儲存格（例如 Z1:AA2），嚴禁更動 A:X 欄寬與順序。

### 4. 台股ETF成分股資料庫 (`11LXjxIke0u_6-4XbGB4cX3o28It1ool2jBXUtMErIUI`)

- **分頁「個股」**：`code,name,industry,priceTwd,divTtmTwd,yieldTtmPct,pe,pb,roePct,payoutPct,fcfCover,debtPct,period`。
- **分頁「ETF持股」**：`etf,code,weightPct,shares`。
- **分頁「摘要」**：A:C 為 `key,value,note`（`asOf`, `etfs`, `stocks`, `note`, `lastUpdated`, `executor`；B 欄一律加 `'` 前綴）。

### 5. 外幣市場 ETF 成分股資料庫（港股、美股、日股）

- 三份 Sheet 與台股全市場表的 ETF_Summary、ETF_Constituents 欄名同序；ETF_Summary 比台股多兩欄：`coverage`（完整、前幾大、備援）與 `holdings_asof`（持股日期），持股完整度與日期都寫進 Sheet。
- ETF_Summary 表頭：`etf_id,etf_name,current_price,exchange,category,benchmark,constituent_count,top1_holding,top2_holding,top3_holding,weighted_roe,net_score,div_score,val_score,fric_score,last_model_update,coverage,holdings_asof`。
- ETF_Constituents 表頭：`etf_id,etf_name,constituent_ticker,constituent_name,weight_pct,shares,update_date`。
- 拿不到的欄位寫 `-`（外幣市場沒有 ETF 現價、ROE 與評分），不估值補；持股日期拿不到寫「無」；代號一律純代號，寫入前掃描國別後綴。
- 寫入者：`etf_sheets_sync.py --market HK|US|JP`，只用 GCP_SA_KEY；同步元資訊：ETF_Summary 在 T1:U2（A:R 以外），ETF_Constituents 在 I1:J2（A:G 以外）。
- 日期：`last_model_update` 是建立日期（模型卡片的 last_model_update）；`holdings_asof` 是持股日期，來源沒有標示就寫「無」；ETF_Constituents 的 `update_date` 也是持股日期。備援與全市場表的持股沒有持股日期。
- **更新（2026-10-27）**：台股全市場表的日期欄照 Hachi 決定，只放建立日期。`ETF_Summary.last_model_update` 與 `ETF_Constituents.update_date` 都是模型卡片的 `last_model_update`，沒有模型卡片的 ETF 寫「無」。原本同一欄對有卡片的 ETF 放建立日期、對候選 ETF 放 MoneyDJ 持股日期，同一欄兩種意義；改後台股表不再有持股日期。外幣市場的 `holdings_asof` 規則不變，舊寫入結果不回溯改寫。排程的補跑互鎖以 `ETF_Summary` 最新 `last_model_update` 判斷（見 `.claude/workflows/market-etf-pool.md` 補跑支援）；此欄改後不再隨每次同步更新，若互鎖仍依它判斷會與實際同步脫節，待 Hachi 確認是否改以 `最後同步時間` 判斷。
- APP 尚未讀取。欄位若要改，先改這份文件，再改寫入器。

## 本機備援與非 Drive 來源

- `src/data/allMarketEtfSnapshot`：全市場 ETF 表讀取失敗時的備援。
- `src/data/etfHistorySnapshot.json`、`etfHoldersHistory.json`：ETF 價格、配息與受益人數快照，由 Stock_AIStudio 的 `refresh-etf-data` workflow 每日更新。
- `/api/etf-quotes`、`/api/market-quote`：APP 後端即時報價。

## 理由

- 事實：試算表 ID 與 Schema 先前分散於多處筆記與對話中，且全市場 ETF 與台股 ETF 缺乏明確的工作流與防呆契約，導致維護困難。
- 判斷：將本清單升級為全系統唯一的試算表註冊表（SSOT），明確規範各欄位順序、文字型別強制鎖定、不刪列原則與互鎖機制，能杜絕因 Google Sheets 自動轉型或格式微調導致的前端 APP 破版故障。

## 適用範圍與例外

- 適用：Stock_AIStudio APP 讀取之所有 Google Drive 試算表，以及對應之定時排程。
- 例外：
  1. `Investment_Tracker_Core` 為內部專用資料庫，嚴禁寫入，亦不在公開 APP 讀取清單之列。
  2. 暫時性或實驗性之回測 CSV 不得上傳至本清單所列之公開試算表。

## 變更紀錄

### v2（2026-10-24）

- 變更：將本文件擴充為全系統試算表單一真實來源（SSOT 註冊表），收斂 4 大核心試算表 Schema、固定欄位契約、防覆蓋隔離原則與雙 Agent 代班規範。
- 原因：與 Claude 雲端對齊排程即程式碼標準，防止重複維護多份 registry 並確保前端 APP 欄位契約 100% 穩定。

### v1（2026-10-22）

- 變更：建立 APP 讀取清單。
- 原因：整合架構文件只登記 3 份來源，漏了持股、交易明細、波段觀察；Hachi 要求盤點並追蹤 APP 抓取的檔案。
