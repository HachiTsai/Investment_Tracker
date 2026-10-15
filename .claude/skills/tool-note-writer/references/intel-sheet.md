# 情報資料庫 Sheet 規格

把研究與趨勢筆記裡的硬數據，歸納成 Stock_AIStudio APP「客觀趨勢情報中心」讀取的訊號列。APP 只讀，這份 Sheet 由 Claude 維護。

## 位置

- 試算表「情報資料庫」：Drive ID `1BF2xvF0cmyODdN0nXR8QHbOTC3ikqswvSwBboY1cGQo`，在 `Project_財商工程/情報與趨勢`（`1OkXyIl0huNSeYEOU1lDM0sfYNxG1gFpq`）。
- 該資料夾是公開連結，APP 免登入以 gviz CSV 讀取。**Sheet 與資料夾內任何檔案都視同公開**，不得放券商帳號等敏感資料；持股與成本數字放進來前先問 Hachi。
- 不屬於 Investment_Tracker_Core，可以寫入。Core 仍嚴禁修改。

## 欄位

每列一筆訊號，第一列為表頭，欄位順序固定：

| 欄位 | 內容 |
| --- | --- |
| `id` | `sig-YYYY-MM-DD-<流水號>`，日期為訊號日期，流水號全表遞增不重複 |
| `date` | 訊號日期 YYYY-MM-DD |
| `ticker` | 代號，如 `00882`。寫入要加 `'` 前綴存成文字，否則會變 `882` |
| `title` | 一句話結論，含關鍵數字 |
| `rawContent` | 事實原文摘要，附數字與日期 |
| `sourceUrl` | 來源網址，沒有就留空 |
| `sourceType` | `drive_doc`（來自 Drive 文件）、`drive_sheet`（來自試算表）；其他值見 APP 型別 |
| `dimension` | 只能是 `dividend_sustainability`、`valuation_margin`、`friction_fx` |
| `direction` | 只能是 `bullish`、`neutral`、`bearish` |
| `weight` | 1 到 5 的整數，越大越影響股利 |
| `hardFacts` | 硬事實，以 `\|` 分隔 |
| `extractedMetrics` | 指標，`名稱=數值`，以 `\|` 分隔 |
| `impliedDividendShift` | 對每股年配息的推估影響（元），無法量化填 `0` |
| `objectiveReasoning` | 推論說明，明講哪些是推論、影響是否量化 |
| `tags` | 以逗號分隔 |
| `extractionMethod` | `ai_assisted` 或 `rule_engine` |
| `verification` | 核對程度：已核對（對照什麼）／部分核對（哪些沒核對）／未核對 |
| `sourceNote` | 出處筆記或文件名，或取代了哪個舊 id |

## 歸納規則

1. **只收可驗證的硬數據**：有數字、日期、來源的事實才入庫。論點、決策與追蹤指標留在筆記。
2. **事實與推論分開**：`hardFacts`、`extractedMetrics` 只放事實；推論寫在 `objectiveReasoning`，並標明「此為推論」。
3. **不得編造**：筆記沒寫的數字不補。媒體轉述、沒對照官方公告的，`verification` 寫「部分核對」並說明。
4. **來源不一致時以官方為準**，兩個數字都記下並在 `verification` 說明（例：華能淨利港交所 −28.29%、媒體 −28.9%）。
5. **去重**：寫入前先讀整張表；同一事實已有一列就更新該列，不新增。舊訊號被修正時沿用 id 或在 `sourceNote` 寫明取代哪個 id，不要靜默刪除。
6. **寫入方式**：用 Google Sheets 的 `update_values` 寫入新列。這個工具不接受 `valueInputOption`，預設會解析輸入，所以 ticker 要加 `'`。寫完讀回確認。
7. **Drive 上一律是 Google 文件／試算表／簡報**，不放 .md。
