# 快照頁規範

## 1. 來源與產物

| 項目 | 內容 |
| :--- | :--- |
| 互動版（來源） | Artifact `TU6Yi51nEe9s783qoDukSs`，用 Google Sheets 連接器讀寫 Our_Investment |
| 快照版（產物） | Artifact `SBn43iC1bBG2zf2bexgmxZ`，資料內嵌，沒有連接器 |
| 資料來源 | Our_Investment（試算表，ID 見 `DRIVE_IDS` 的 `OUR_INVESTMENT_SHEET_ID`），不是 Core |

## 2. 資料範圍（data.json）

| 鍵 | 試算表範圍 |
| :--- | :--- |
| `portfolio` | `Portfolio!A1:S50` |
| `tx` | `Transactions!A1:R200` |
| `journal` | `Stock_Journal!A1:E300` |
| `cash` | `資金餘額!A1:B8` |

值為 Sheets `get_values` 回傳的二維陣列，空儲存格保留原樣（`-` 或缺漏）。`portfolio`、`tx`、`journal` 含表頭列；`cash` 無表頭，依列序與 A 欄標籤讀值。`tx` 的 O–R 欄（現金流、資金來源、計入餘額、餘額（累計））由試算表公式產生，頁面的可投資餘額依此計算。

建置時會檢查表頭欄位（`portfolio` 的代號、總市值、未實現損益；`tx` 的現金流、資金來源、餘額（累計）等；`journal` 的類別、內容等）與資金餘額的 A 欄標籤位置（第 2、3、5、6、7 列）。對不上就不發布並回報，避免試算表改版後快照悄悄算錯。

## 3. 快照保留與移除

- **保留**：總覽（含可投資餘額與其中新資金）、持股、交易、里程圖，版面與樣式與互動版相同。
- **移除**：記帳分頁（記帳、新增標的、移除標的）、重新整理按鈕、連接器、所有寫入程式。
- **頁首**：顯示「快照時間（台北）」與「唯讀，由 Claude 定時更新」。

## 4. 隱私與邊界

- 快照含持股股數、成本與股利金額。Artifact 預設私有，分享由 Hachi 在頁面 Share 設定自行處理，不設公開連結。
- 快照只由 Claude 發布。嚴禁寫入、修改 Core；嚴禁把 Core 的資料放進快照。
- 抓不到資料就整次不發布並回報，不用舊值或預設值補。
