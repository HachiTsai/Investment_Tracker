# Git 結構化提交流程規範

本 REPO 採用結構化 Git 提交標準，所有提交與合併均遵循嚴格工作流：

## 1. 分支與 PR 鐵律

1. **先開 PR 再合併 `main`**：
   - 所有變更（包含文件與筆記）都在工作階段指定的分支上 commit 並推送，向 `main` 發起 Pull Request。
   - PR 的 CI（`markdown-lint` 與 `pytest`）全綠後才可合併，失敗需立刻修正。
   - **禁止直接 push 到 `main` 分支**。
2. **合併方式一律採用 Merge Commit**：
   - 不使用 squash、不使用 rebase，保留分支上每個 commit 的完整訊息與歷程，便於以 `git log --grep` 追溯歷史決策。
3. **全自動持續交付（模式 B）**：
   - Agent 端到端流程：獨立分支 ➔ 本地驗證（pytest / mdlint）➔ 提交並推送 ➔ 發起 PR ➔ 監聽 CI 狀態。
   - GitHub Actions CI 全綠通過後，由 `ci.yml` 的 `auto-merge` job 以標準 Merge Commit（`gh pr merge <id> --merge --delete-branch`）自動合入 `main`；僅限同 repo、`claude/` 開頭分支（草稿會先自動轉正式），使用 Secrets `AUTO_MERGE_PAT`（用 PAT 才會觸發 `main` 的 CI）。
   - Agent 在合併後確認 `main` 的 CI 通過並切回 `main` 保持最新同步；個人帳號無法設 branch protection，故不使用內建 auto-merge。
   - **草稿 PR 全自動**：雲端工作階段的系統指令要求 PR 先開為草稿。`auto-merge` job 不分草稿與否，CI 全綠後先以 `gh pr ready` 轉為正式 PR，再 Merge Commit 合併，全程免人工。
4. **雙 Agent 協同交接機制**：
   - Claude 雲端（前端 Artifact 渲染＋排程）與 Antigravity（本機重度後端＋回測）透過 Git 分支與 commit 之 `## Session-Sync` 區塊無縫接力。
   - 額度受限或未完成工作可提交至 `claude/*` 分支並在 `下一步` 標註接手項目；任一方開工執行 `--sync`、`--patrol` 或啟動時自動透過 `check_handoff` 偵測草稿筆記、最新交接事項與近期未合併分支。
   - **排程即程式碼與試算表契約**：所有定時排程規格集中於 `.claude/workflows/*.md` 為單一真實來源（SSOT）；試算表 Schema 統一收斂於 `architecture/APP讀取清單-Stock_AIStudio.md`。Artifact 100% 由 Claude 雲端專屬發布（本機代班僅產出 HTML 推送分支）；純資料表（全市場 ETF、波段觀察）由 GitHub Actions 自動排程直寫 Google Sheets（節省 Claude Token），亦支援本機直寫代班；雙棲表（00882、台股 ETF）固定由雲端統籌發布與寫入。排程互鎖比對資料日期，並支援 `--force` 手動強制補跑。

## 2. 結構化 Commit 流程

所有 commit 均透過 `fin-commit` skill 執行：

```bash
# 0. 開工先安全拉取（只 fast-forward；有未提交變更或分叉時不動並回報）
python3 .claude/skills/fin-commit/scripts/committer.py --sync

# 1. 暫存並取得草擬指令
python3 .claude/skills/fin-commit/scripts/committer.py --stage-list <paths...>

# 2. 依模板將 commit message 寫入 .git/COMMIT_MSG_TEMP

# 3. 檢查並提交（自動進行 Markdown lint 與格式驗證）
python3 .claude/skills/fin-commit/scripts/committer.py --no-stage --message-file .git/COMMIT_MSG_TEMP
```

## 3. 提交規範與禁止事項

- 規格書 SSOT：`.claude/skills/fin-commit/references/spec-git-commit-protocol.md`。
- 一個 commit 只記錄一個投資事件或一個主題。
- 嚴禁提交券商帳號、密碼、身分證字號等敏感個資（腳本會自動以 `find_sensitive` 攔截）。
- 要推送時若目前在 `main`，腳本會中止（`--no-push` 本機提交不受限）；變更 `.claude/` 卻沒動到 rules 或索引時會提醒。
- 嚴禁未經記錄即引用第三方套件（腳本會自動以 AST 掃描 staged `.py` 檔案與 `pyproject.toml`，未同步時自動攔截中止，可加 `--allow-missing-deps` 略過）。
