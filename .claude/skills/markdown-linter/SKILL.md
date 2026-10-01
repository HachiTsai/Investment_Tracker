---
name: markdown-linter
description: 用 markdownlint-cli2 檢查並修正 REPO 內的 Markdown，確保沒有 MD 格式錯誤，並和 CI 使用同一份設定。只要新增或修改任何 .md 檔案（CLAUDE.md、筆記、快照、skill 文件、規格書），提交前都要使用；使用者提到 markdown lint、MD 錯誤、MD0xx 規則編號、格式檢查、CI 的 markdown-lint 失敗時也要使用。
---

# markdown-linter：Markdown 格式檢查

- **設定（SSOT）**：REPO 根目錄的 `.markdownlint-cli2.jsonc`。本機、CI 與編輯器外掛都讀這一份，結果才會一致。
- **工具**：`scripts/mdlint.py`，包裝固定版本的 `markdownlint-cli2`。版本寫在腳本的 `LINTER_PACKAGE`，升級時只改這裡。
- **相依**：Node.js（內含 `npx`），第一次執行時會自動下載 linter。
- **CI**：`.github/workflows/ci.yml` 的 `markdown-lint` job 在 push 到 main 與每個 PR 時執行同一支腳本。

## 用法

以下指令都在 REPO 根目錄執行：

```bash
python3 .claude/skills/markdown-linter/scripts/mdlint.py                 # 檢查全部 *.md
python3 .claude/skills/markdown-linter/scripts/mdlint.py CLAUDE.md       # 只檢查指定檔案
python3 .claude/skills/markdown-linter/scripts/mdlint.py --fix <檔案>    # 自動修正可修的問題
```

回傳碼：`0` 表示通過，`1` 表示有 lint 錯誤，`2` 表示無法執行（缺 Node.js 或下載失敗）。

## 自動整合

- **fin-commit**：`committer.py` 提交前會檢查暫存區的 `.md`，不通過就不提交。
- **tool-note-writer**：`notes.py check` 檢查完筆記欄位後，會接著做 Markdown lint。
- 這兩個地方的 `--skip-mdlint` / `--no-mdlint` 只在本機沒有 Node.js 時暫時使用，CI 仍會擋下錯誤。

## 修正流程

1. 先執行 `--fix`，自動修掉空行、清單符號、行尾空白這類機械性問題。
2. 再執行一次檢查，手動修正剩下的問題。常見問題：

   | 規則 | 問題 | 修法 |
   | --- | --- | --- |
   | MD040 | 程式碼區塊沒寫語言 | 加上 `bash`、`markdown`、`text` 等 |
   | MD036 | 用 `**粗體**` 當標題 | 改成 `###` 標題 |
   | MD025 | 有兩個 H1 | frontmatter 的 `title` 已算作 H1，正文不要再寫 `#` |
   | MD031 / MD032 | 程式碼區塊或清單前後沒空行 | 前後各加一個空行；在清單項目內也一樣 |
   | MD024 | 同一層出現同名標題 | 改名，或調整標題層級 |

3. 修正應該讓文件更正確，不要為了通過檢查而刪除內容。

## 調整規則

只在規則和這個 REPO 的寫作方式根本衝突時才調整，例如中文段落不適合 MD013 行長限制。調整方式：

1. 修改 `.markdownlint-cli2.jsonc`，並在該規則旁用註解寫明原因。
2. 執行全 REPO 檢查，確認通過。
3. 用 fin-commit 提交，type 為 `chore`。

不要用 `<!-- markdownlint-disable -->` 在個別檔案關閉規則，例外應該集中寫在設定檔裡。

## 測試

```bash
python3 -m pytest -q .claude/skills/markdown-linter/tests
```

測試包含「全 REPO Markdown 必須通過 lint」。沒有 Node.js 的環境會自動略過需要 linter 的測試項目。
