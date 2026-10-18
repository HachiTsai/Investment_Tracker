---
name: tw-etf-fetcher
description: 台股 ETF 專用資料管線與穿透分析工具。負責抓取全市場 ETF 股號清單、解析各 ETF 完整成分股與持股權重、執行投資組合穿透分析（Look-through），並支援一鍵生成 DCS 建模卡片。
---

# 台股 ETF 資料管線與成分股穿透分析技能（tw-etf-fetcher）

本技能為台股 ETF 專用資料管線，專門處理全市場 ETF 清單、底層成分股持股穿透、資產曝險分析與自動化 DCS 建模卡片建構。

---

## 1. 核心功能

1. **全市場 ETF 清單盤點**：連線台灣證券交易所（TWSE）官方端點，獲取全市場 270+ 檔 ETF 清單（支援依高股息、市值型、債券型過濾）。
2. **完整成分股穿透抓取**：精準解析指定 ETF 之 100% 完整底層個股代號、名稱、投資權重（%）與持有股數。
3. **投資組合實質穿透分析（Look-through）**：輸入個人多檔 ETF 持股張數，自動折算加權背後實質持有各個股之總金額與投資組合總佔比，偵測隱形集中度風險。
4. **DCS 建模卡片一鍵建置（Scaffold Model）**：自動將抓取的 ETF 與成分股資料轉換為 `models/<ticker>/cards/` 標準卡片，無縫納入 `portfolio-patrol` 日常巡檢體系。

---

## 2. 常用指令

```bash
# 1. 查詢全市場 ETF（支援關鍵字或類型過濾）
python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py list --filter 高息
python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py list --limit 20

# 2. 抓取指定 ETF 之完整成分股與權重
python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py holdings 00878
python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py holdings 00878 00919 0056 --json

# 3. 投資組合穿透分析（計算個人實質持有個股總曝險）
# 例如持有 10 張 00878 與 5 張 00919
python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py lookthrough --portfolio "00878:10,00919:5"

# 4. 為指定 ETF 一鍵建置 DCS 建模卡片（自動放入 models/<ticker>/cards/）
python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py scaffold-model 00878
```

---

## 3. 架構與防護規則

1. **唯讀資料庫鐵律**：本技能僅作為資料擷取與運算工廠，嚴禁對 `Investment_Tracker_Core` 進行任何寫入。
2. **客觀專業用語**：所有終端報告與註解維持客觀金融分析用語，嚴禁使用浮誇詞彙。
3. **離線單元測試保證**：全套單元測試內建 Mock 機制，確保在無外網環境下維持 100% 綠燈。
