# Antigravity 專案導引與 `.claude/` 單一真實來源規範

本檔案為 Antigravity 唯一入口規則，旨在將所有專案規則、技能（Skills）與設定統一收斂至 **`.claude/`** 目錄下管理，避免維護兩套重複檔案。

---

## 1. 單一真實來源（Single Source of Truth）鐵律

1. **所有實體設定一律集中於 `.claude/`**：
   - 模組化規則庫統一存放於 `.claude/rules/*.md`。
   - 技能與自動化腳本統一存放於 `.claude/skills/`（如 `.claude/skills/fin-commit/`）。
2. **採用 Claude Code 官方語法編寫**：
   - 新增或修改任何 Rule、Skill（`SKILL.md`）或設定時，一律遵循 **Claude 官方原生語法與目錄結構**編寫於 `.claude/` 下。
   - 新增 `.claude/rules/<name>.md` 時，同步將引用加入根目錄 `CLAUDE.md` 與本檔案（`.agent/rules/AGENT.md`）第 2 節清單中。
3. **本機環境與測試鐵律**：
   - 本機環境（macOS / Antigravity）一律綁定 Conda 環境（`ai-it-go`，Python 3.14.8）。
   - 提交前必須先執行測試與語法檢查（`pytest` 與 `markdown-linter`）。
   - 變更提交一律遵循分支與 PR 機制，不得直接 push 至 `main`。

4. **憲法（同 `CLAUDE.md`）**：變更 `.claude/` 下的 skills／workflows／hooks／tools 時，提交前必須先掃描 `.claude/rules/`、`CLAUDE.md` 與本檔，條列可能需要更新的規定並詢問 Hachi，經同意才更新。

---

## 2. 專案規則與技能自動載入（指向 `.claude/`）

- **專案總覽入口**：@[CLAUDE.md](../../CLAUDE.md)
- **後台資料庫禁令與資料源**：@[.claude/rules/core-database.md](../../.claude/rules/core-database.md)
- **Python 執行環境與依賴規範**：@[.claude/rules/python-environment.md](../../.claude/rules/python-environment.md)
- **Git 結構化提交流程規範**：@[.claude/rules/git-commit-workflow.md](../../.claude/rules/git-commit-workflow.md)
- **外部網路連線與資料源清單**：@[.claude/rules/network-connectivity.md](../../.claude/rules/network-connectivity.md)
- **投資組合控制系統架構規範**：@[.claude/rules/portfolio-control-system.md](../../.claude/rules/portfolio-control-system.md)
- **Git 提交流程 Skill**：@[.claude/skills/fin-commit/SKILL.md](../../.claude/skills/fin-commit/SKILL.md)
- **財商筆記撰寫 Skill**：@[.claude/skills/tool-note-writer/SKILL.md](../../.claude/skills/tool-note-writer/SKILL.md)
- **港股資料查詢 Skill**：@[.claude/skills/hk-market-data/SKILL.md](../../.claude/skills/hk-market-data/SKILL.md)
- **股價與配息抓取 Skill**：@[.claude/skills/price-dividend-fetcher/SKILL.md](../../.claude/skills/price-dividend-fetcher/SKILL.md)
- **Markdown 檢查 Skill**：@[.claude/skills/markdown-linter/SKILL.md](../../.claude/skills/markdown-linter/SKILL.md)
- **投資組合全標的巡檢 Skill**：@[.claude/skills/portfolio-patrol/SKILL.md](../../.claude/skills/portfolio-patrol/SKILL.md)
- **台股 ETF 資料管線 Skill**：@[.claude/skills/tw-etf-fetcher/SKILL.md](../../.claude/skills/tw-etf-fetcher/SKILL.md)
- **基本面財務指標評分 Skill**：@[.claude/skills/fundamental-analyzer/SKILL.md](../../.claude/skills/fundamental-analyzer/SKILL.md)
- **Artifact 來源登記與斷鏈檢查 Skill**：@[.claude/skills/artifact-registry/SKILL.md](../../.claude/skills/artifact-registry/SKILL.md)
- **00882 成分股股利調查工作流**：@[.claude/workflows/component-dividend-investigation.md](../../.claude/workflows/component-dividend-investigation.md)
- **投資組合全標的巡檢工作流**：@[.claude/workflows/portfolio-patrol.md](../../.claude/workflows/portfolio-patrol.md)
