# Our_Investment 快照版排程工作流

本工作流把互動版交易簿衍生為唯讀快照 Artifact，供家人在不需連接器的情況下查看。規格收斂於 Git REPO 作為單一真實來源（SSOT）。

---

## 1. 觸發時機與排程

- **排程頻率**：建議每日台北 21:00；也可隨時由 Hachi 說「更新快照」手動觸發。實際時間以雲端排程設定為準。
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

---

## 3. 執行步驟

1. **取最新互動版**：用 Artifact `read` 讀 `https://claude.ai/artifact/TU6Yi51nEe9s783qoDukSs`，記下結果給的完整頁面檔案路徑（不要依賴上次的檔案）。
2. **讀資料**：用 `get_values` 讀 Our_Investment（`1uIWpKYkHljK6fy-P3ddkmMRqm0hN2X-oI-aCga8Kko0`）的 `Portfolio!A1:S50`、`Transactions!A1:N200`、`Stock_Journal!A1:E300`，依 `.claude/skills/ledger-snapshot/references/snapshot-spec.md` 第 2 節存成 `data.json`（存在暫存目錄，不進 git）。任一範圍讀不到，整次中止並回報。
3. **產生快照**：

   ```bash
   python3 .claude/skills/ledger-snapshot/scripts/build_snapshot.py \
     --source <步驟 1 的檔案> --data data.json --stamp "<台北時間 YYYY-MM-DD HH:MM>" --out snapshot.html
   ```

   腳本失敗（找不到標記、資料格式不對）就不發布，回報錯誤訊息，並說明互動版哪裡改版了。
4. **發布**：用 Artifact 以 `file_path` 為 `snapshot.html`、`url` 為 `https://claude.ai/artifact/SBn43iC1bBG2zf2bexgmxZ` 發布，不傳 `capabilities`（快照沒有連接器），`label` 寫「定時更新 YYYY-MM-DD」。
5. **回報**：一行說明快照時間、持股檔數、交易與日誌筆數，以及發布連結。

---

## 4. 失敗處理

- 資料或來源頁讀不到：不發布，保留上一版快照，回報原因。
- 腳本標記失效：不發布，回報；由開發者更新 `build_snapshot.py` 與測試後再跑。
- 不用舊值、預設值或手寫數字代替抓不到的資料。
