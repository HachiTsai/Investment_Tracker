---
type: arch
title: APP讀取清單-Stock_AIStudio
domain: 資料系統
status: 生效
version: 1
created: 2026-10-22
updated: 2026-10-22
tags: [資料系統, ETF]
tickers: [00882]
related: ["[[情資管線與APP整合架構]]"]
---

## 摘要

Stock_AIStudio 以免登入 gviz CSV 讀取的 Drive 試算表，以及本機備援快照的盤點。ID 寫死在 APP 各 service 檔，本清單是 Investment_Tracker 端的對照；任何一端新增、更換或停用來源，兩邊要同步更新。

## 規則

1. **新增來源先登記**：APP 要讀新的 Sheet 前，先在本清單加一列（ID、分頁、讀取檔、寫入者、更新頻率），再改程式。
2. **以 ID 讀取**：改檔名不影響 APP，換 ID 或改分頁名、欄位名會直接壞，必須同步改 APP。
3. **公開邊界**：所列資料夾皆為知道連結者可檢視，內容不得含個人持股張數或真實成本。持股與交易兩份由排程依 Core 唯讀重建，屬例外，沿用既有授權，不擴大。
4. **沒有排程的來源要標示**：APP 讀到過期資料時會悄悄顯示舊值，過期風險須寫在「更新」欄。

## 讀取清單（2026-10-22 核對 Stock_AIStudio 原始碼）

| 來源 | Drive ID | 分頁 | APP 讀取檔 | 寫入者 | 更新 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 情報資料庫 | `1BF2xvF0cmyODdN0nXR8QHbOTC3ikqswvSwBboY1cGQo` | 第一分頁（訊號）、評分歷史 | `signalsFeedService.ts` | Claude 排程（風向日報等） | 平日日報 |
| 00882_成分股股利資料庫 | `1Jq599WzoQUDsooZDhJhyK8uaEMgDiLLCoZthWk2WXtw` | 成分股、摘要 | `constituentsFeedService.ts` | Claude 排程 | 每週五 |
| 全市場 ETF 成分股資料庫 | `1GIhbRyL-h96ACVjlSSW9YUFMiAItg_SP9Wi0o3WwG70` | ETF_Summary、ETF_Constituents | `constituentsFeedService.ts`（失敗退回 `allMarketEtfSnapshot`） | `tw-etf-fetcher` 的 `etf_fetcher.py sync-sheets`（手動） | 無排程，最後修改 2026-10-19 |
| 持股資料庫 | `1CWLwi1tsQoWaEYm0IOK9aH7NEkENgd71sbz6Y_lpRVI` | 第一分頁 | `portfolioFeedService.ts` | 排程依 Core 唯讀重建 | 依排程 |
| 交易明細資料庫 | `1yFr6OSW6LKWm5wdoc-QoJFXyUotYEd8_YEl_qR-24ks` | 第一分頁 | `portfolioFeedService.ts` | 排程依 Core 唯讀重建 | 依排程 |
| 波段觀察 | `1pyGzkgaspYMYdXOPYerkLsxOMwNwa2yOKuNDrOrrhtQ` | 第一分頁 | `swingFeedService.ts` | `price-dividend-fetcher` 的 `swing.py --scan` | 依排程 |

## 本機備援與非 Drive 來源

- `src/data/allMarketEtfSnapshot`：全市場 ETF 表讀取失敗時的備援。
- `src/data/etfHistorySnapshot.json`、`etfHoldersHistory.json`：ETF 價格、配息與受益人數快照，由 Stock_AIStudio 的 `refresh-etf-data` workflow 每日更新。
- `/api/etf-quotes`、`/api/market-quote`：APP 後端即時報價。

## 未被 APP 讀取的相關 Sheet

- 台股ETF成分股資料庫（`11LXjxIke0u_6-4XbGB4cX3o28It1ool2jBXUtMErIUI`，All_Market/Taiwan）：個股財報、股利與 ETF 持股，目前只供 Artifact 與分析，APP 尚未接。

## 待辦與觀察

- 全市場 ETF 表沒有排程，APP 讀到的是 2026-10-19 的資料；是否加排程待 Hachi 決定。
- 整合架構文件原寫 ETF_Constituents 為 4,353 筆，實際約 5,328 列，已以實際為準。
- 持股、交易、波段三份的實際排程名稱與頻率，下次核對時補上。

## 變更紀錄

### v1（2026-10-22）

- 變更：建立 APP 讀取清單。
- 原因：整合架構文件只登記 3 份來源，漏了持股、交易明細、波段觀察；Hachi 要求盤點並追蹤 APP 抓取的檔案。
