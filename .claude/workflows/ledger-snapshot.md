# Our_Investment 快照版排程工作流

本工作流把互動版交易簿衍生為唯讀快照 Artifact，供家人在不需連接器的情況下查看。規格收斂於 Git REPO 作為單一真實來源（SSOT）。

---

## 1. 觸發時機與排程

- **排程頻率**：平日台北 09:30；也可隨時由 Hachi 說「更新快照」手動觸發。實際時間以雲端排程設定為準。
- **觸發平台**：Claude 雲端排程。
- **雲端排程 Prompt（單行呼叫）**：

  ```text
  git pull --ff-only origin main，讀取並執行 .claude/workflows/ledger-snapshot.md，完成後依規格回報。
  ```

---

## 2. 執行前置與環境

- **工作目錄**：REPO 根目錄；前置動作 `git pull --ff-only origin main`。
- **需要的工具**：Artifact（讀取與發布）、Google Sheets 的 `get_values`。
- **唯讀保護約束**：只讀 Our_Investment，嚴禁碰觸 `Investment_Tracker_Core`；不寫任何試算表。
- **必要環境變數**：`DRIVE_IDS` 須含 `CORE_SHEET_ID` 與 `OUR_INVESTMENT_SHEET_ID`（雲端環境同名設定）。缺任一鍵，建置腳本會中止、不發布（2026-11-09 Hachi 同意）。

---

## 3. 執行步驟

1. **取最新互動版**：用 Artifact `read` 讀 `https://claude.ai/artifact/TU6Yi51nEe9s783qoDukSs`，記下結果給的完整頁面檔案路徑（不要依賴上次的檔案）。
2. **讀線上快照**：用 Artifact `read` 讀 `https://claude.ai/artifact/SBn43iC1bBG2zf2bexgmxZ`，記下存檔路徑，再用 Read 把該檔從頭讀到最後一行。每次排程都是新的對話，沒看過線上版本就發布會被拒；這個檔案同時是步驟 4 的 `--prev`。
3. **讀資料**：用 `get_values` 讀 Our_Investment（`OUR_INVESTMENT_SHEET_ID`）的 `Portfolio!A1:U50`、`Transactions!A1:R200`、`Stock_Journal!A1:E300`、`資金餘額!A1:B9`。每個回應原文（含 `range` 與 `values` 的整段 JSON）原樣存成暫存目錄 `raw/` 下的 `portfolio.json`、`tx.json`、`journal.json`、`cash.json`，不重新排版、不合併成一個檔（不進 git）。任一範圍讀不到，整次中止並回報。
4. **產生快照**：

   ```bash
   python3 .claude/skills/ledger-snapshot/scripts/build_snapshot.py \
     --source <步驟 1 的檔案> --raw-dir raw/ --prev <步驟 2 的檔案> \
     --stamp "<台北時間 YYYY-MM-DD HH:MM>" --out snapshot.html
   ```

   - 結束碼 1（找不到標記、資料格式不對、`DRIVE_IDS` 缺鍵、快照含試算表 ID）：不發布，回報錯誤訊息；標記失效時說明互動版哪裡改版了。
   - 結束碼 2（既有的交易或日誌列與上一版不同）：逐筆對照 `get_values` 的回應原文。抄錯就修正 `raw/` 的檔案後重跑；確認是試算表真的改了，加 `--accept-history-changes` 重跑，並在回報列出這些變動。
5. **發布**：用 Artifact 以 `file_path` 為 `snapshot.html`、`url` 為 `https://claude.ai/artifact/SBn43iC1bBG2zf2bexgmxZ` 發布，不傳 `capabilities`（快照沒有連接器），`label` 寫「定時更新 YYYY-MM-DD」。被拒時依第 4 節「發布被拒」處理，不停下來等人。
6. **發布後檢查**：用 Artifact `read` 讀回 `https://claude.ai/artifact/SBn43iC1bBG2zf2bexgmxZ`，存成檔案後確認不含 `SHEET_ID`，也不含 `DRIVE_IDS` 內的兩個 ID（只回報有無，不印 ID），且頁面內的快照時間是這次的時間。檢查失敗就回報，不宣告成功。
7. **回報**：一行說明快照時間、持股檔數、交易與日誌筆數，以及發布連結。

---

## 4. 失敗處理

- 資料或來源頁讀不到：不發布，保留上一版快照，回報原因。
- 腳本標記失效：不發布，回報；由開發者更新 `build_snapshot.py` 與測試後再跑。
- `DRIVE_IDS` 缺鍵，或快照含試算表 ID：不發布，回報；線上版本維持原狀，不手動覆寫。
- 不用舊值、預設值或手寫數字代替抓不到的資料。
- **發布被拒（線上版本比這個對話看過的新）**：這不是失敗，照下列順序處理（2026-11-12 Hachi 同意）。
  1. 讀拒絕訊息附的差異。只有資料列（`const SNAPSHOT`）與時間戳（`const SNAPSHOT_AT`）不同，才算可以覆蓋；有其他差異就不發布，回報差異內容。
  2. 不原樣重送：同一份內容再送會再被擋一次。用當下的台北時間重跑步驟 4（時間戳要與上次不同，同一分鐘就等到下一分鐘），再發布。
  3. 連續兩次重建後仍被拒，才停止並回報拒絕訊息原文。
  4. 全程不用 `force`。`force` 會丟掉線上版本，只有 Hachi 明確要求時才用。

---

## 5. 互動版改版發佈與快照同步（2026-11-14）

互動版（TU6Yi）改版後，快照（SBn43i）若不同步，家人看到的就是舊版面；排程只在平日 09:30 跑，週末與下午改版會落差到隔天以上。互動版與快照視為同一個發佈單位，一次做完：

1. **發佈前預檢**：把要發佈的互動版檔案當 `--source`，跑 `build_snapshot.py --use-prev-data --prev <線上快照檔>`（不需連線）。失敗代表標記失效，先修腳本與測試，再一起發佈；沒修好就不發布互動版，避免快照從此建不出來。
2. **發布互動版**：`url` 為 `https://claude.ai/artifact/TU6Yi51nEe9s783qoDukSs`，**省略 `capabilities`**（沿用既有的 Google Sheets 連接器宣告，傳錯會讓頁面失去讀寫權限）。被拒時先 `read` 新版、合併後再發，不用 `force`。
3. **發布後檢查**：`read` 讀回，確認頁面仍含連接器程式與寫入程式、版本是剛發的那版。
4. **立刻重發快照**：照第 3 節完整跑一次（含讀資料、`--prev`、發布後檢查），不等排程。
5. **回報**：一行寫互動版與快照各自的發佈結果；快照失敗要明說「互動版已發、快照沒同步」，並保留原因。
