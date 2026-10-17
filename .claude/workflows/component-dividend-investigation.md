# 00882 成分股股利調查與 Google Sheets 同步工作流

本工作流為 Antigravity 本地自動化標準作業程序（SOP），負責自港交所披露易檢索 00882 成分股最新分紅公告，產出獨立標的研究筆記，並自動同步至 Google Drive 原生 Google Sheet。

---

## 1. 觸發時機

- **除息季定期檢索**：港股中期分紅季（9～11 月）與年度分紅季（3～5 月）。
- **重大公告發布時**：核心成分股（中遠海控、國有大行、神華等）發布盈喜、盈利預警或分紅派息公告。
- **使用者明確指令**：使用者要求「查成分股最新消息/公告」、「更新成分股股利調查」時觸發。

---

## 2. 標準執行步驟

```mermaid
flowchart TD
    A["1. hk-market-data 檢索公告"] --> B["2. 提煉事實數據與 PDF 原文"]
    B --> C["3. tool-note-writer 產出 research 筆記"]
    C --> D["4. gsheets 在 Google Drive 建立/更新原生試算表"]
    D --> E["5. 分頁配置（明細表 + 摘要與觀點）"]
    E --> F["6. 格式驗證（notes.py check + mdlint.py）"]
```

### 步驟 1：檢索港交所披露易官方公告

使用專案內建的 `hk-market-data` 腳本，透過 Python 連線披露易：

```bash
# 檢索 00882 全數 49 檔成分股近兩週公告
python3 .claude/skills/hk-market-data/scripts/hkdata.py sectors --announce-days 14

# 針對核心權重股檢索近 30 天詳細公告
python3 .claude/skills/hk-market-data/scripts/hkdata.py announce 1919 0939 1398 3988 1288 1088 0998 1766 --days 30
```

### 步驟 2：解析 PDF 提煉硬事實

利用 `hkdata.py pdf` 抓取並解析公告關鍵字，提取每股股息、除息日與現金發放日：

```bash
python3 .claude/skills/hk-market-data/scripts/hkdata.py pdf <披露易PDF網址> --grep "Dividend declared|Ex-dividend|Payment"
```

### 步驟 3：使用筆記技能歸納至 `research/`

依據 `format-research.md` 規範，在 REPO 的 `research/` 目錄建立或更新獨立研究筆記（例如 `research/00882_成分股股利調查.md`）：

- **遵循六大必填段落**：摘要、論點、依據、風險與反方觀點、追蹤指標、更新紀錄。
- **事實與觀點分開**：依據段落記錄客觀除息表格與 PDF 原文連結；論點段落記錄對現金流與分紅常態化的解讀。

### 步驟 4：建立與同步 Google Drive 原生 Google Sheet

在雲端硬碟 `Portfolio_00882/成分股股利資料庫/` 目錄建立原生 Google Sheet：

1. **尋找目錄 ID**：

   ```bash
   gdrive readonly search --name-exact "成分股股利資料庫" --type folder
   ```

2. **建立 Google Sheet 並移動至目標目錄**：

   ```bash
   gsheets mutate create --title "00882_核心成分股2026中期配息調查"
   gdrive mutate mv <SHEET_ID> <FOLDER_ID>
   ```

3. **分頁 1 配置（數據明細表）**：
   - 記錄代號、公司名稱、權重、每股配息 (RMB)、除息日、現金發放日、披露易公告。
   - 套用樣式：凍結首列、標題列加粗與深藍底色（`#1b365d`）、自動欄寬（`autosize`）。
4. **分頁 2 配置（摘要與觀點）**：
   - 新增分頁 `摘要與觀點`：

     ```bash
     gsheets mutate add-sheet <SHEET_ID> --title "摘要與觀點"
     ```

   - 寫入調查摘要、核心論點、風險觀點、關鍵追蹤指標與資料來源。
   - 套用樣式：設定欄寬（項目 260px / 內容 750px）並開啟文字自動換行（`--wrap`）。

### 步驟 5：雙向參照與合規檢查

1. **筆記連結**：在 research 筆記的 `sources` 欄位加入新建立的 Google Sheet 連結。
2. **合規驗證**：

   ```bash
   python3 .claude/skills/tool-note-writer/scripts/notes.py check
   python3 .claude/skills/markdown-linter/scripts/mdlint.py
   ```

---

## 3. 注意事項與禁止規則

1. **嚴禁 CSV 混入**：上傳至 Google Drive 的檔案必須為原生 Google Workspace 格式（`.gsheet`），不保留中介 `.csv` 或 `.md`。
2. **禁止修改 Core**：本工作流只操作 `Portfolio_00882/成分股股利資料庫/`，**嚴禁修改 `Investment_Tracker_Core`**。
3. **保持獨立性**：00882 整體 ETF 的歷年配息由 `00882_股利追蹤.md` 管理；成分股個別調查維持獨立筆記與獨立 Sheet，兩者不混為一談。
