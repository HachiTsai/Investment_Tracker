# 快照頁規範

## 1. 來源與產物

| 項目 | 內容 |
| :--- | :--- |
| 互動版（來源） | Artifact `TU6Yi51nEe9s783qoDukSs`，用 Google Sheets 連接器讀寫 Our_Investment |
| 快照版（產物） | Artifact `SBn43iC1bBG2zf2bexgmxZ`，資料內嵌，沒有連接器 |
| 資料來源 | Our_Investment（試算表 ID `1uIWpKYkHljK6fy-P3ddkmMRqm0hN2X-oI-aCga8Kko0`），不是 Core |

## 2. 資料範圍（data.json）

| 鍵 | 試算表範圍 |
| :--- | :--- |
| `portfolio` | `Portfolio!A1:S50` |
| `tx` | `Transactions!A1:N200` |
| `journal` | `Stock_Journal!A1:E300` |

值為 Sheets `get_values` 回傳的二維陣列，含表頭列，空儲存格保留原樣（`-` 或缺漏）。

## 3. 快照保留與移除

- **保留**：總覽、持股、交易、里程圖，版面與樣式與互動版相同。
- **移除**：記帳分頁（記帳、新增標的、移除標的）、重新整理按鈕、連接器、所有寫入程式。
- **頁首**：顯示「快照時間（台北）」與「唯讀，由 Claude 定時更新」。

## 4. 隱私與邊界

- 快照含持股股數、成本與股利金額。Artifact 預設私有，分享由 Hachi 在頁面 Share 設定自行處理，不設公開連結。
- 快照只由 Claude 發布。嚴禁寫入、修改 Core；嚴禁把 Core 的資料放進快照。
- 抓不到資料就整次不發布並回報，不用舊值或預設值補。
