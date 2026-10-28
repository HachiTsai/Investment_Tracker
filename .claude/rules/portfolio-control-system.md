# 投資組合控制系統架構規範（Portfolio Control System）

本規範將工業級分散式控制系統（Distributed Control System, DCS / Plant Model）的建模哲學導入財商工程，將個人投資組合視為一套嚴謹、具備回授調節與互鎖保護的「投資控制系統」。

---

## 1. 核心理念

傳統投資記錄往往依賴凌亂的試算表公式或主觀文字，容易產生黑盒子效應、邏輯斷鏈與過期無效資訊。
本架構以**「受控系統（Plant）＋控制迴路（Loop）＋邏輯互鎖（Interlock）＋卡片式解耦（Card-based）」**為基礎，建立一套透明、可追溯、防禦力強大的動態投資大腦。

---

## 2. 工業控制系統 vs 投資工程概念對照

| 控制系統架構概念 | 財商投資工程概念 | 具體在 00882 大本營的實踐 |
| :--- | :--- | :--- |
| **受控廠區 (Plant)** | **受控投資組合 (Portfolio)** | 00882 核心部位（未來可擴充 00878、美股等子系統） |
| **感測器訊號 (Sensors: AI/DI)** | **市場與情報訊號 (Signals)** | 現價、殖利率、匯率、南向資金流、港交所除息公告 |
| **控制迴路 (Control Loop: PID)** | **目標收斂迴路 (Goal Loop)** | **「50 萬股利收斂迴路」**：設定目標 SP=50萬，測量當前值 PV，計算缺口 Error，驅動加碼 MV |
| **邏輯互鎖 (BLS / Interlocks)** | **多空風控互鎖 (Risk Guardrails)** | **「高息陷阱互鎖」**：IF 殖利率 ≥ 8.0% 且（netScore < 50 或 divScore < 40）THEN 首日列為「陷阱觀察」；前一個交易日同一標的也成立時升級為「陷阱警戒」，處置為暫停額外單筆加碼、維持例行再投入。成分股財報覆蓋率低於 60% 時不判定（列為資料不足）。門檻唯一來源：`portfolio-patrol/references/interlock_rules.json` |
| **執行器動作 (Actuators: AO/DO)** | **資金調配動作 (Capital Actions)** | 股息 100% 再投入、按部就班分批買進、關閉閥門暫留現金緩衝 |
| **卡片實體 (Card)** | **投資卡片 (Investment Cards)** | 標的卡片、成分股卡片、控制迴路卡片、風控互鎖卡片 |
| **兩層對照 (Design vs As-Built)** | **模型推估層 vs 帳本實測層** | **設計推估層**（以近 12 個月實際配息推估的年配息）vs **實帳層**（Core 實際入帳與真實扣繳） |

---

## 3. 卡片式架構（Card-based Architecture）四大核心原則

### 原則一：模組化自包含卡片（Self-Contained Cards）

每個分析對象或控制邏輯獨立封裝為一張標準化卡片，具有明確的輸入、輸出與關聯邊：

1. **標的卡片（Ticker Card）**：記錄標的屬性、真實成本、即時感測指標與關聯成分股清單。
2. **成分股卡片（Component Card）**：記錄成分股代號、權重、分紅進度、性質標籤（如 `央企控股` 或 `週期型民企`）與對母標的之每股貢獻度。
3. **控制迴路卡片（Loop Card）**：定義期望目標（Setpoint）、當前推估實值（Process Value）、系統偏差（Error）與動作建議。
4. **風控互鎖卡片（Interlock Card）**：定義明確的布林邏輯條件（IF...THEN...），防止人性貪婪或恐懼導致盲目追高或殺低。

### 原則二：每句必附出處（Strict Provenance）

卡片與模型中記錄的事實數據，必須嚴格標記出處（Provenance）：

- 港交所官方公告（附 PDF 網址與日期）。
- 投信官方每日持股 API 或公開說明書。
- 交易所或權威報價來源（Google Finance / Yahoo Finance）。
- 嚴禁未經核對即將推論或媒體轉述包裝為客觀事實。

### 原則三：兩層對照與校準機制（Design vs As-Built & Reconciliation）

系統嚴格區分兩層資料：

- **設計層（Design / Model）**：基於 49 檔成分股分紅、歷史配發比與稅費所推估出的理論配息與進度。
- **實收層（As-Built / Core）**：實際由銀行帳戶入帳、記錄在 `Investment_Tracker_Core` 的真實金流與扣繳金額。
- 當兩層產生偏差時，**絕不竄改歷史帳本**，而是產出一筆**「校準事件（Reconciliation Event）」**，反饋修正模型的參數（如校準配發比或所得稅摩擦率）。

### 原則四：動靜分離（Separation of Logic and State）

- **靜態邏輯層（.md / REPO）**：負責記錄數學模型算式、決策原則、卡片結構與版本演進，不寫死高頻波動的即時價格。
- **動態狀態層（Google Sheets / Core）**：即時維護行情、持股張數與成分股母表。
- **隨需運算層（Evaluator CLI）**：需要當前結論時，由腳本現場讀取動態資料代入靜態邏輯，產出永不落後事實的最新儀表板。

---

## 4. 實體識別碼（ID）與卡片結構規範

| 實體類型 | ID 格式範例 | 對應檔案與生成條件 | 說明 |
| :--- | :--- | :--- | :--- |
| 標的卡片 | `card:ticker:00882` | `ticker.yml`（必備） | 核心追蹤投資標的；含 `category`（`ETF` / `STOCK`）、`tier`（`core` / `pool`）與 `strategy_type` 欄位 |
| 成分股卡片 | `card:comp:1919` | `constituents.jsonl`（ETF 必備） | 底層成分股代號、名稱、權重與持有股數 |
| 控制迴路卡片 | `card:loop:passive_income_500k` | `loop_dividend_500k.yml`（僅 `DIVIDEND_INCOME` 產生） | 50 萬被動股利年收入目標控制迴路；成長型（`CAPITAL_GROWTH`）等非高息型 ETF 不產生此卡片 |
| 風控互鎖卡片 | `card:interlock:yield_trap_guard` | `interlock_yield_trap.yml`（`HEDGING_OR_DERIVATIVE` 除外） | 殖利率陷阱與策略狀態互鎖保護邏輯 |
| 情報訊號 | `sig-YYYY-MM-DD-<流水號>` | 情報資料庫試算表 | 寫入情報資料庫的客觀事實訊號 |

### `ticker.yml` 之 `strategy_type` 策略類型定義

| `strategy_type` 值 | 資產策略定位 | `loop_dividend_500k.yml` 生成規則 | 巡檢狀態判定軌道 |
| :--- | :--- | :---: | :--- |
| `DIVIDEND_INCOME` | 高股息／收息型 ETF | ✅ 產生 | 殖利率區間 × 基本面高息陷阱互鎖（50 萬股利目標收斂） |
| `CAPITAL_GROWTH` | 市值／科技／成長型 ETF | ❌ 不產生 | 波段技術位階與趨勢配置狀態（不計算 50 萬股利達成率） |
| `BOND_DEFENSE` | 債券防禦型 ETF | ❌ 不產生 | 債券合理息收區間（積極佈建／穩健配置／防禦觀望） |
| `HEDGING_OR_DERIVATIVE` | 槓桿／反向／期貨型 ETF | ❌ 不產生 | 獨立避險或波段觀察，不納入長線收息迴路 |
| `STOCK` | 個股（`category: STOCK`，非 ETF 分類） | ❌ 不產生 | 個股分支評估（`category` 為 `STOCK` 時進入個股評估，不套用 ETF 策略分軌） |

---

## 5. 系統邊界與安全鐵律

1. **Core 唯讀禁令**：本控制系統只讀取 `Investment_Tracker_Core` 的持股與交易資料，**嚴禁任何寫入、修改或自動操作**。
2. **公開邊界隱私**：所有寫入 Google Drive 公開試算表（如 `情報資料庫`、`00882_成分股股利資料庫`）之內容，一律不得包含個人持股張數、總成本、缺口金額等敏感隱私部位。

---

## 6. 前後端語義隔離與金融專業措辭鐵律（Semantic Isolation & Terminology Guardrails）

本系統的核心設計哲學雖然借鑑工業級分散式控制系統（DCS）之閉環反饋與互鎖概念，但在**對外呈現層次**必須貫徹嚴格的「前後端語義隔離」原則：

### 1. 適用範圍劃分

- **後台／架構／演算引擎層（Backend & Internal Engine）**：
  - 僅限於內部檔案、後端架構文件、演算法引擎（如 `dcsControlEngine.ts`）、卡片結構（如 `loop_*.yml`、`interlock_*.yml`）及程式碼變數命名字串中使用 DCS、Plant、Control Loop、SP/PV/Error、Interlock 等控制理論模型術語。
- **前端 UI／報告／使用者介面層（Frontend UI & Briefings）**：
  - **嚴格禁止向使用者呈現任何 DCS、工程控制、軍事化或浮誇科幻之措辭**。
  - 所有面向使用者的元件、按鈕、標籤、卡片標題、通知提示與產出簡報，必須 100% 轉換為客觀、嚴謹、直觀的專業金融投資術語。

### 2. 嚴格禁止辭彙（黑名單）

- ❌ **DCS 相關**：`DCS`、`DCS 投資控制大腦`、`DCS 控制大腦`、`DCS 模組`
- ❌ **工程控制相關**：`目標控制迴路`、`控制迴路`、`閉環系統`、`系統閉環偏差`
- ❌ **軍事／浮誇科幻相關**：`戰術姿態`、`即時戰術姿態`、`姿態`、`戰術指引`、`全艦隊`、`大艦隊`、`艦隊`、`總裁`、`戰情`、`戰情簡報`

### 3. 客觀專業金融替代對照（白名單）

| 原始內部/工程用語 | ❌ 嚴禁前端 UI 用語 | ✅ 前端 UI / 簡報標準專業用語 |
| :--- | :--- | :--- |
| DCS Investment Brain | DCS 投資控制大腦 | **核心投資決策儀表** 或 **動態投資管理中心** |
| Control Loop & Tactical Posture | 目標控制迴路 & 即時戰術姿態 | **年度股利目標追蹤 & 即時配置建議** |
| Tactical Guide | 戰術指引 | **操作指引** 或 **配置建議** |
| Tactical Posture | 戰術姿態 / 姿態 | **配置策略** 或 **投資狀態**（如：穩健複利策略、積極增持配置、估值偏高觀望、陷阱防護警戒） |
| Setpoint (SP) | 目標設定值 (SP) | **目標年股利 (SP)** 或 **年度目標 (SP)** |
| Process Value (PV) | 測量值 (PV) | **目前推估年股利 (PV)** 或 **目前推估 (PV)** |
| System Error | 系統閉環偏差 (Error) | **目標達成缺口 (Gap)** |
| C-Engine Timeline | 複利滾雪球時間線 (C 引擎) | **股息複利再投入試算 (純股利無額外本金)** |
| Fleet / Entire Fleet | 全艦隊 / 大艦隊 / 艦隊 | **投資組合 / 全標的** |
| Briefing | 戰情簡報 | **投資巡檢簡報** 或 **投資組合狀態摘要** |
