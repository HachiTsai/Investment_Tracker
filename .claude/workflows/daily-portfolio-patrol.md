# 口袋名單每日波段觀察巡檢報告排程工作流

本工作流為投資組合全標的每日巡檢與波段觀察戰報之標準作業程序（SOP），規格收斂於 Git REPO 作為單一真實來源（SSOT），專注於產出高互動性之單檔 HTML 視覺化戰報，並發布至 Claude 專屬 Artifact。

---

## 1. 觸發時機與排程

- **排程頻率**：每個平日例行執行（建議盤後或晚間定時觸發）。
- **觸發平台**：Claude 雲端排程。
- **雲端排程 Prompt（單行呼叫）**：

  ```text
  git pull --ff-only origin main，讀取並執行 .claude/workflows/daily-portfolio-patrol.md，完成後依規格回報。
  ```

---

## 2. 執行前置與環境

- **工作目錄**：REPO 根目錄。
- **前置動作**：`git pull --ff-only origin main`。
- **產出型態**：**純 Artifact（無 Sheet）**。
- **唯讀保護約束**：
  - 嚴禁寫入 `Investment_Tracker_Core`。
  - 不要 commit 或 push，不要發送 Slack 通報。

---

## 3. 標準執行步驟

```mermaid
flowchart TD
    A["1. git pull --ff-only origin main"] --> B["2. 執行 patrol.py --json > /tmp/patrol.json"]
    B --> C["3. 執行 swing.py --scan ... --daily-html /tmp/daily.html"]
    C --> D{"4. 檢查 ERROR 檔數 (Gate)"}
    D -->|異常 (>5檔)| E["終止！不覆寫 Artifact，回報失敗原因"]
    D -->|正常| F["5. 原地更新發布至 Artifact (WLXXvrX7...)"]
    F --> G["6. 簡短一句話回報"]
```

### 步驟 1：執行投資組合巡檢總管

在 REPO 根目錄執行：

```bash
python3 .claude/skills/portfolio-patrol/scripts/patrol.py --json > /tmp/patrol.json
```

*自動遍歷 models/*/cards/ 計算 DCS 姿態、SP/PV/Error 與例外管理分診（MBE）。*

### 步驟 2：執行波段掃描與戰報頁面渲染

在 REPO 根目錄執行：

```bash
python3 .claude/skills/price-dividend-fetcher/scripts/swing.py --scan 00882:15 --patrol /tmp/patrol.json --daily-html /tmp/daily.html > /tmp/scan.json
```

*現場結合技術面指標、動能斜率與巡檢姿態，渲染出完整互動式單檔 HTML。*

### 步驟 3：健康檢查門檻判定（Gatekeeper）

解析 `/tmp/scan.json` 內容：

- 若任何前置指令執行失敗，立即終止。
- 若 `scan.json` 內之 `ERROR` 狀態列超過 **5 檔**，**不要覆寫 Artifact**，結束時簡短說明失敗原因與發生錯誤的檔案。
- 資料日為前一交易日（週一早上為週五資料）；若全表最新資料日與上次相同（休市），仍照常更新，不另外警報。

### 步驟 4：Artifact 原地更新發布（Claude 雲端專屬）

- **固定目標 URL**：`https://claude.ai/artifact/WLXXvrX7BzLemm9TxqZ6di`
- **發布模式**：先 read 該 artifact 再以 `/tmp/daily.html` 原地更新，**嚴禁建立新的 Artifact**。

---

## 4. 執行回報規範

完成後僅需極簡的一句話回報：

```text
資料日：YYYY-MM-DD，標的檔數：X 檔，ERROR：Y 檔。Artifact 更新成功。
```

---

## 5. 雙 Agent 協同分工與代班邊界

- **日常運作**：本任務為「純 Artifact 任務」，100% 由 **Claude 雲端排程** 專屬負責發布。
- **本機代班邊界**：Artifact URL 屬 Anthropic 私有服務，Antigravity 本機無法直接推播更新。若遇雲端空窗代班，本機僅負責執行步驟 1~2 產出 `/tmp/daily.html`，並推送到 `claude/daily-patrol-fallback` 分支，待 Claude 喚醒後一鍵讀檔發布。
