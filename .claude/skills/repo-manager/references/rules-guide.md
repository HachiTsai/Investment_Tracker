# repo-manager 規則說明

`scripts/committer.py` 讀取 `scripts/rules/` 的 JSON 規則；增修規則只需改檔，不必改程式。

| 檔案 | 用途 |
| --- | --- |
| `scripts/rules/repos.json` | 受管 repo、各自的 venv、預期 Python 版本、規則檔與原生 committer 路徑 |
| `scripts/rules/tools.json` | 巡檢要求的系統工具與最低版本 |
| `scripts/rules/commit.json` | 敏感檔樣式、受保護分支、import 與套件名對照、commit 結尾署名 |

## 鐵律（沿用各 repo 既有規範）

1. 所有變更走分支 + PR 到 `main`，CI 全綠後 Merge Commit 合併；禁止直推 `main`（`commit` 子命令會擋）。
2. 禁止 `reset --hard`、`rebase`、`push --force`，除非使用者明確同意。
3. 新增第三方套件必須同步 `pyproject.toml`（與規則檔內的 toml 區塊），`check` 會比對。
4. 提交訊息一律用 `--message-file`（`git commit -F`），不用 `git commit -m`。
5. 巡檢只讀：不 push、不安裝、不改 repo 內容。
6. 拉取只用 `sync`：fetch 後僅 `--ff-only`；有未提交變更、分叉、舊分支一律不動。

## 用法

```bash
python3 scripts/committer.py sync                  # 安全拉取全部 repo（--repo NAME、--fetch-only）
python3 scripts/committer.py patrol                  # 巡檢工具與五個 repo（可加 --json、--repo NAME）
python3 scripts/committer.py check Investment_Tracker   # 對該 repo 暫存區做提交前檢查
python3 scripts/committer.py commit Stock_AIStudio --message-file msg.txt [--no-push]
```

`patrol` 結束碼：有 FAIL 為 1，否則 0（WARN 不影響）。
