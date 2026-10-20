---
name: repo-manager
description: 跨 REPO 安全拉取（sync）、巡檢與提交前檢查：巡檢實際環境（系統工具、git、Python、pyproject 與已安裝套件）、提交前檢查（敏感檔、受保護分支、未登記依賴、規則檔同步、.claude/ 變更需掃描 rules）。使用者說「巡檢環境」「檢查 pyproject」「全 REPO 狀態」時使用。
---

# repo-manager

跨 REPO 管理工具，只用標準函式庫（Python 3.11+）。規則在 `scripts/rules/*.json`，增修不必改程式。

## 指令

```bash
python3 .claude/skills/repo-manager/scripts/committer.py sync [--repo NAME] [--fetch-only]
python3 .claude/skills/repo-manager/scripts/committer.py patrol [--repo NAME] [--json]
python3 .claude/skills/repo-manager/scripts/committer.py check <REPO>
python3 .claude/skills/repo-manager/scripts/committer.py commit <REPO> --message-file <F> [--no-push]
```

- `sync`：安全拉取。`git fetch` 後只做 `--ff-only` 快轉；有未提交變更、與遠端分叉、分支已併入 main 時一律不動，只回報。不使用 rebase、reset、force。多人（雲端 Claude 與本機 Antigravity）協作時，開工前先跑。
- `patrol`：只讀；有 FAIL 結束碼為 1，WARN 不影響。
- `check`：對該 REPO 暫存區檢查；在 main 上、含敏感檔、未登記依賴、規則檔不同步為 FAIL；改了 `.claude/` 卻沒動規則檔為 WARN。
- `commit`：check 通過才 `git commit -F`，預設 push，不建 PR。本 REPO 的正式提交仍走既有 committer（見 `.claude/rules/git-commit-workflow.md`）。

## 規則檔

| 檔案 | 用途 |
| --- | --- |
| `scripts/rules/repos.json` | 受管 REPO、venv、預期 Python 版本、規則檔、原生 committer |
| `scripts/rules/tools.json` | 巡檢要求的系統工具與最低版本 |
| `scripts/rules/commit.json` | 敏感檔樣式、受保護分支、import 對照、rules 掃描路徑 |

`repos.json` 的 `workdir` 預設 `/home/user`，本機環境請改成實際的 repo 上層目錄。

詳細規則與鐵律見 `references/rules-guide.md`。
