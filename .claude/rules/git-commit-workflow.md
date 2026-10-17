# Git 結構化提交流程規範

本 REPO 採用結構化 Git 提交標準，所有提交與合併均遵循嚴格工作流：

## 1. 分支與 PR 鐵律

1. **先開 PR 再合併 `main`**：
   - 所有變更（包含文件與筆記）都在工作階段指定的分支上 commit 並推送，向 `main` 發起 Pull Request。
   - PR 的 CI（`markdown-lint` 與 `pytest`）全綠後才可合併，失敗需立刻修正。
   - **禁止直接 push 到 `main` 分支**。
2. **合併方式一律採用 Merge Commit**：
   - 不使用 squash、不使用 rebase，保留分支上每個 commit 的完整訊息與歷程，便於以 `git log --grep` 追溯歷史決策。

## 2. 結構化 Commit 流程

所有 commit 均透過 `fin-commit` skill 執行：

```bash
# 1. 暫存並取得草擬指令
python3 .claude/skills/fin-commit/scripts/committer.py --stage-list <paths...>

# 2. 依模板將 commit message 寫入 .git/COMMIT_MSG_TEMP

# 3. 檢查並提交（自動進行 Markdown lint 與格式驗證）
python3 .claude/skills/fin-commit/scripts/committer.py --no-stage --message-file .git/COMMIT_MSG_TEMP
```

## 3. 提交規範與禁止事項

- 規格書 SSOT：`.claude/skills/fin-commit/references/spec-git-commit-protocol.md`。
- 一個 commit 只記錄一個投資事件或一個主題。
- 嚴禁提交券商帳號、密碼、身分證字號等敏感個資。
