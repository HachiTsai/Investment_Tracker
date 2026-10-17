# Python 執行環境與 `pyproject.toml` 同步規範

## 1. 執行環境選擇

- **本機環境（macOS / Antigravity）**：
  - 統一使用 Conda 環境 `ai-it-go`（Python 3.14.8，路徑：`/opt/homebrew/Caskroom/miniforge/base/envs/ai-it-go/bin/python`）。
  - 本地 IDE（VS Code / Cursor / Antigravity）透過 `.vscode/settings.json` 指向此直譯器。
  - `.vscode/` 已加入 `.gitignore`，確保本機設定不外溢至雲端或 Git 歷史。
  - 執行測試或腳本時，一律使用該環境的直譯器：

    ```bash
    /opt/homebrew/Caskroom/miniforge/base/envs/ai-it-go/bin/python -m pytest -q .claude/skills
    ```

- **雲端環境（Claude Web）**：
  - 使用 Linux 標準 Python 3.12+ 環境。
  - 統一以 `pyproject.toml` 作為唯一的套件依賴與工具設定來源。

## 2. 單一依賴來源與同步鐵律

- **廢除 `requirements.txt`**：專案統一以 **`pyproject.toml`** 作為唯一的套件依賴與工具設定來源，不再維護 `requirements.txt`。
- **禁止只安裝不記錄**：新增任何第三方套件時，**嚴禁**只執行 `pip install <pkg>` 或手動安裝而不更新設定檔。一律優先使用 **`uv add <pkg>`** 進行安裝，或手動在 `pyproject.toml` 登記。
- **腳本以標準函式庫為原則**：`.claude/skills/` 內的所有自動化工具與抓取腳本，以只使用 Python 標準函式庫為原則，避免環境相依問題。
- **規則檔與設定檔必須完全一致**：下方第 3 節收錄了標準 `pyproject.toml` 完整內容。當透過 `uv add <pkg>` 或手動更新 `pyproject.toml` 時，**必須同步更新本檔案下方區塊**，確保兩者 100% 一致。`committer.py` 提交時會自動進行 AST 掃描與雙向比對攔截。
- **測試覆蓋與提交前驗證**：提交前必須先在本機 Conda 環境跑過全數測試（`pytest`）並通過 `markdown-linter` 檢查。

## 3. 標準 `pyproject.toml` 內容（須與專案根目錄保持一致）

```toml
[project]
name = "investment-tracker"
version = "0.1.0"
description = "Hachi 的個人財商工程基地：架構、投資思考、趨勢覺察、交易紀錄與投資管理 skill"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    # 測試與品質（CI 與本機環境）
    "pytest>=8.0.0",
    # 資料分析與解析、網頁抓取（按需使用）
    "numpy>=2.0.0",
    "pandas>=2.2.0",
    "openpyxl>=3.1.0",
    "requests>=2.31.0",
    "lxml>=5.0.0",
    "pdfplumber>=0.11.0",
    "pymupdf>=1.24.0",
    "beautifulsoup4>=4.12.0",
    "playwright>=1.40.0",
]

[tool.pytest.ini_options]
testpaths = [".claude/skills"]

[tool.ruff]
line-length = 120
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W"]
ignore = ["E501", "E741"]
```
