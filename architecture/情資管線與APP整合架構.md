---
type: arch
title: 情資管線與APP整合架構
domain: 資料系統
status: 生效
version: 1
created: 2026-10-18
updated: 2026-10-22
tags: [資料系統, ETF, 港股]
tickers: [00882]
related: ["[[00882_股利目標模型]]"]
---

## 摘要

本架構規範確立本專案（Investment_Tracker）與前端投資應用程式（Stock_AIStudio）之間的系統整合邊界與非同步資料匯流排契約。Investment_Tracker 作為 AI 研報分析、市場監控與情資提煉之資料工廠；Stock_AIStudio 則作為使用者視覺化互動的前端消費端。雙方透過 Google Drive 原生試算表實現解耦，在保障個人隱私安全的同時維持單一真實來源（SSOT）。

## 規則

1. **單向資料流向（Unidirectional Flow）**：
   - 資料流由後端資料工廠流向前端消費端：`Investment_Tracker`（爬蟲、筆記、訊號提煉） ➔ Google Drive 雲端資料匯流排 ➔ `Stock_AIStudio`（免登入 gviz CSV 讀取渲染）。
   - 前端 APP 永遠作為唯讀消費者，不反向寫入情資庫，亦不依賴即時爬蟲腳本。

2. **核心試算表權責契約（Permission & Ownership Matrix）**：
   - APP 實際讀取的全部 Sheet 與備援來源見 [[APP讀取清單-Stock_AIStudio]]（以該清單為準）。
   - **【情報資料庫】**（Drive ID `1BF2xvF0cmyODdN0nXR8QHbOTC3ikqswvSwBboY1cGQo`）：
     - **擁有者與寫入者**：由 Claude 雲端任務與 Antigravity 負責維護。負責寫入 `Untitled` 訊號列（`sig-YYYY-MM-DD-XX`）並依規則刷新 `評分歷史` 分頁。
     - **消費者**：Stock_AIStudio 的「客觀趨勢情報中心」（`src/services/signalsFeedService.ts`）以 gviz CSV 免登入讀取。
   - **【00882_成分股股利資料庫】**（Drive ID `1Jq599WzoQUDsooZDhJhyK8uaEMgDiLLCoZthWk2WXtw`）：
     - **擁有者與寫入者**：由 AI 檢索港交所披露易公告後回填 00882 專屬成分股派息紀錄（如 `interim2026` 欄位）。
     - **消費者**：Stock_AIStudio 用於 00882 成分股加權股利預估與透視。
   - **【全市場_ETF成分股資料庫】**（Drive ID `1GIhbRyL-h96ACVjlSSW9YUFMiAItg_SP9Wi0o3WwG70`，在 `Project_財商工程/All_Market`）：
     - **擁有者與寫入者**：由 `tw-etf-fetcher` 技能（`etf_sheets_sync.py`）維護，包含 `ETF_Summary`（27 檔跨市場 ETF 摘要）與 `ETF_Constituents`（約 5,328 列全底層持股明細（2026-10-22 核對））。
     - **消費者**：Stock_AIStudio 前端應用程式，提供免登入 gviz CSV 讀取。
   - **【Investment_Tracker_Core】**（Drive ID `1QBEgUi-kTOuLgj2yGHmP-0g_ug-Sl_M21SN0g93b6xI`）：
     - **擁有者**：Hachi 與 Stock_AIStudio 前端記帳核心。
     - **AI 權限**：**⛔ 絕對禁止寫入或變更結構**。AI 僅能只讀查詢，加工試算一律於外部檔案進行。

3. **訊號格式穩定性保證（Schema Stability Contract）**：
   - 寫入「情報資料庫」之訊號必須嚴格符合 `references/intel-sheet.md` 規範（固定 17 欄位，包含 `id`, `dimension`, `direction`, `weight`, `hardFacts`, `extractedMetrics` 等）。
   - 任何欄位或列結構變更，必須同步更新 `Stock_AIStudio` 的型別定義（`src/types/portfolio.ts`），嚴禁單邊引進破壞性變更。

4. **公開性與隱私隔離（Public/Private Isolation）**：
   - 「情報資料庫」與「成分股資料庫」所在資料夾已設為公開檢視，內容視同全網公開。**嚴禁寫入任何個人持股張數、真實成本金額或券商帳號**。
   - 涉及個人資產的機密數據僅留存於 `Investment_Tracker_Core` 與本機端，不得外溢至公開情資 Sheet。

## 理由

1. **職責分離與輕量化架構**：前端 Web/行動 APP（Stock_AIStudio）無需打包龐大的 Python 爬蟲與金融量化依賴，大幅提升載入效能並避免 API 金鑰暴露於前端客戶端。
2. **非同步自動化解耦**：Claude 雲端定時排程與本機 Antigravity 可在盤後或除息季獨立運作，提煉硬事實並更新 Sheet，使用者打開 APP 即可享有最新運算成果，無需等待即時爬蟲。
3. **最高人機協作透明度**：以 Google Sheets 作為中間資料匯流排，使用者可直接開啟試算表檢視 AI 提煉之原始事實，必要時能直接在試算表中修正，確保 AI 與人類決策隨時同步。

## 適用範圍與例外

- **適用範圍**：本專案所有標的（00882 及未來新增標的）之港交所公告檢索、研究與趨勢筆記提煉、情報入庫，以及對接 Stock_AIStudio 之一切資料流程。
- **例外情況**：若遇 Google Drive 服務中斷或 gviz API 異常，`portfolio-patrol` 仍可於本地端產出獨立 JSON / Markdown 簡報，保障巡檢不受外部雲端中斷影響。

## 變更紀錄

### v1（2026-10-18）

- 變更：建立財商架構筆記，正式明訂 Investment_Tracker 與 Stock_AIStudio 之間的整合契約與資料匯流排權限。
- 原因：落實防孤兒架構，消弭跨專案與跨 Agent 記憶斷層，確保後台 AI 提煉與前端 APP 讀取維持單一真實來源。

### 更新（2026-10-22）

- 變更：權責表補連結至 APP 讀取清單，ETF_Constituents 筆數改為實際約 5,328 列。
- 原因：原表漏登持股、交易明細、波段觀察三份來源。
