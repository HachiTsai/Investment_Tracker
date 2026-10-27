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
3. **本機環境、分支與測試鐵律**：
   - 本機環境（macOS / Antigravity）一律綁定 Conda 環境（`ai-it-go`，Python 3.14.8）。
   - 分支命名：Antigravity 作業一律使用 `agy/<task-name>` 分支，Claude 作業一律使用 `claude/<task-name>` 分支；不得直接 push 至 `main`。`ci.yml` 的 `auto-merge` 對 `claude/` 與 `agy/` 開頭分支皆自動合併（不限定 PR 範圍）。
   - 提交前必須先執行測試與語法檢查（`pytest` 與 `markdown-linter`）。

4. **憲法（動工前預檢與 PR 規則掃描，同 `CLAUDE.md`）**：
   - **動工前預檢**：開工前必先寫出作業範圍、流程、步驟，逐步對照 `.claude/rules/*.md`、`CLAUDE.md` 與本檔（`.agent/rules/AGENT.md`）。相關的話先列清單給 Hachi，經同意後才改；無關也要明寫「已掃描 rules，無需更新」。
   - **PR 描述固定段落與 CI 備援檢查**：所有 PR 描述固定加上「規則掃描」段落（列出掃了哪些檔、結論、Hachi 同意的訊息位置）。CI 設有備援檢查：PR 若改到 `.claude/`、`CLAUDE.md` 或 `.agent/rules/AGENT.md` 卻缺少「規則掃描」段落即失敗。

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
- **ETF 資料管線 Skill（台股、港股、美股、日股）**：@[.claude/skills/tw-etf-fetcher/SKILL.md](../../.claude/skills/tw-etf-fetcher/SKILL.md)
- **基本面財務指標評分 Skill**：@[.claude/skills/fundamental-analyzer/SKILL.md](../../.claude/skills/fundamental-analyzer/SKILL.md)
- **00882 成分股股利調查工作流**：@[.claude/workflows/component-dividend-investigation.md](../../.claude/workflows/component-dividend-investigation.md)
- **投資組合全標的巡檢工作流**：@[.claude/workflows/portfolio-patrol.md](../../.claude/workflows/portfolio-patrol.md)
- **台股 ETF 成分股明細工作流**：@[.claude/workflows/tw-etf-pool.md](../../.claude/workflows/tw-etf-pool.md)
- **00882 成分股股利表排程工作流**：@[.claude/workflows/hk-00882-dividend.md](../../.claude/workflows/hk-00882-dividend.md)
- **全市場 ETF 資料庫排程工作流**：@[.claude/workflows/market-etf-pool.md](../../.claude/workflows/market-etf-pool.md)
- **波段觀察資料庫排程工作流**：@[.claude/workflows/swing-patrol-sheets.md](../../.claude/workflows/swing-patrol-sheets.md)
- **每日波段巡檢戰報排程工作流**：@[.claude/workflows/daily-portfolio-patrol.md](../../.claude/workflows/daily-portfolio-patrol.md)
