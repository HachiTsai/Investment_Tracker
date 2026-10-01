---
name: fin-commit
description: 財商工程 REPO 的標準 commit 流程（committer.py）。自動暫存、依路徑判定類別／type／scope、輸出草擬指令，並在提交前檢查訊息是否符合規格書。財商架構、標的研究、趨勢覺察、交易紀錄、快照、skill 開發等所有 commit 都走這個流程。凡是在這個 REPO 執行 git commit，或使用者說「commit」「提交」「記錄這筆交易」時使用。
---

# fin-commit：財商工程 Commit Workflow

- **規格書（SSOT）**：`references/spec-git-commit-protocol.md`，包含類別、type、唯一模板與檢查規則。
- **執行器**：`scripts/committer.py`，參考 delivery-commit-workflow 的 committer.py 改寫。
- **測試**：`tests/test_committer.py`，用 `python3 -m pytest -q .claude/skills/fin-commit/tests` 執行。

所有 commit 共用同一份詳細模板。**交易紀錄只是其中一種 commit**，差別是多了必填的「交易明細」區塊；`div` 則多了「股利明細」。

## 標準流程

```bash
# 1. 暫存並取得草擬指令（預設 git add .；可用 --stage-list / --exclude / --no-stage）
python3 .claude/skills/fin-commit/scripts/committer.py --stage-list <paths...>

# 2. 依指令中的 diff 與規格書 §4 模板，把訊息寫入 .git/COMMIT_MSG_TEMP

# 3. 檢查並提交（補執行裝置、Co-Author；不合規即擋下；預設會 push）
python3 .claude/skills/fin-commit/scripts/committer.py --no-stage --message-file .git/COMMIT_MSG_TEMP
```

- 類別、type、訊息內容由 Agent 自行判定，**不逐次詢問使用者**。
- 只有缺少的**數字**（股數、價格、金額、手續費）必須詢問，不得推測。
- 混了多種行為時，用 `--stage-list` 拆成多個 commit。

## 參數

| 參數 | 用途 |
| --- | --- |
| `--stage-list P...` | 清空暫存後只暫存指定路徑 |
| `--exclude P...` | `git add .` 後排除指定路徑 |
| `--no-stage` | 使用現有暫存區 |
| `--message-file F` | 檢查 F 後直接提交 |
| `--dry-run` | 只顯示最終訊息，不提交 |
| `--no-push` | 提交後不 push |
| `--skip-mdlint` | 略過暫存區 Markdown lint（僅限沒有 Node.js 時暫用，CI 仍會檢查） |
| `--category C` | 覆蓋自動判定的類別（交易紀錄／持股分析／財商架構／投資研究／趨勢覺察／IT） |
| `--agent A` | 指定執行者（kimi／claude／antigravity），否則讀 `AGENT_ID` 或 `CLAUDECODE` |
| `--auto-quick` | L1 機械式快速提交；交易紀錄、CLAUDE.md、本 skill 的變更會被擋下（`--allow-guarded` 可解除） |
| `--status` `--next` `--blocker` | L1 的 Session-Sync 欄位 |
| `--check F` | 只檢查訊息檔（commit-msg hook 用） |
| `--install-hook` | 安裝 commit-msg hook，讓直接 `git commit` 也經過檢查 |

## 自動補強與檢查

- **Markdown lint**：提交前用 `markdown-linter` skill 檢查暫存區的 `.md`，沒通過就不提交。

- **執行裝置**：寫進「## 驗證」區塊；可用環境變數 `AGENT_DEVICE` 覆蓋，否則標作業系統。
- **Co-Authored-By: Claude**：已有 Claude 署名時不重複。

## 範例：交易紀錄

```markdown
reinvest(00882): 股息 158,344 再投入 10 張 @15.08

## 核心變更

- 記錄 8/11 股息再投入 10 張

## 變更理由

- 7 月除息股利全數再投入，維持複利

## 交易明細

- **日期**: 2026-08-11
- **數量**: 10,000 股（10 張）
- **價格**: 15.08
- **金額**: 150,800 TWD
- **手續費**: 215
- **理由**: 股利再投入
- **來源**: Core/Transactions Tx_ID ad364a04

## 驗證

- 10,000 × 15.08 = 150,800，與 Core/Transactions 一致

## 目標影響

- 持股 290 張 → 300 張

## Session-Sync

- **執行者**: Claude
- **類別**: 交易紀錄
- **狀態**: 8/11 再投入已入帳
- **下一步**: 更新持股快照
- **阻塞**: 無
```
