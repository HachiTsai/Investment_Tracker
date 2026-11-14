---
name: ledger-snapshot
description: 把互動版交易簿（Our_Investment）衍生成唯讀快照 Artifact，不需連接器，可分享給家人。使用者說「更新快照」「快照版」「重發快照」，或互動版版面更新後需要同步快照時使用。
---

# ledger-snapshot：私人帳本唯讀快照

- **核心腳本**：`scripts/build_snapshot.py`（只用 Python 標準函式庫）。讀互動版頁面 HTML，拿掉記帳分頁、連接器與所有寫入程式，把試算表的值內嵌進頁面，輸出快照 HTML。
- **規範**：`references/snapshot-spec.md`（資料範圍、保留與移除的部分、隱私）。
- **排程流程**：`.claude/workflows/ledger-snapshot.md`。
- **唯讀保護**：只讀 Our_Investment，嚴禁碰觸 `Investment_Tracker_Core`；腳本與測試都會擋掉輸出中出現 Core 與 Our_Investment 的 ID，以及連接器常數名。缺 `DRIVE_IDS` 的 `CORE_SHEET_ID` 或 `OUR_INVESTMENT_SHEET_ID` 時不輸出（fail closed）。

## 用法

執行前需要環境變數 `DRIVE_IDS`（含 `CORE_SHEET_ID`、`OUR_INVESTMENT_SHEET_ID`）。測試由 `.claude/skills/conftest.py` 提供假值。

```bash
python3 .claude/skills/ledger-snapshot/scripts/build_snapshot.py \
  --source <互動版頁面.html> --raw-dir <raw/> --prev <上一版快照.html> \
  --stamp "YYYY-MM-DD HH:MM" --out <快照.html>
```

- `--raw-dir`：資料夾內放四個 `get_values` 回應原文（`portfolio.json`、`tx.json`、`journal.json`、`cash.json`），不必重排成 `data.json`；也可改用 `--data <data.json>`。
- `--prev`：上一版快照頁。既有的交易或日誌列有變動時中止（結束碼 2），確認後加 `--accept-history-changes`。
- `--use-prev-data`：改版預檢。資料沿用 `--prev` 快照內嵌的值（不需連線），只驗證新互動版的標記與輸出安全檢查；互動版發佈前一定先跑（見排程流程第 5 節）。
- 發布被拒的處理方式見排程流程第 4 節，不原樣重送、不用 `force`。

互動版版面改了，不用手改快照：重跑一次，快照就跟著更新。來源頁改版導致腳本的標記找不到時，腳本會失敗並指出缺哪個標記，不輸出半成品，此時要回頭更新腳本。

## 測試

```bash
python3 -m pytest -q .claude/skills/ledger-snapshot/tests
```
