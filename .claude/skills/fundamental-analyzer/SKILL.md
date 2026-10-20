---
name: fundamental-analyzer
description: 基本面財務指標與多維評分演算引擎。負責個股三大財務報表指標計算（ROE、自由現金流覆蓋倍數、盈餘配發率、營業利益率、負債比）與 ETF 穿透加權聚合評分（netScore、divScore、valScore、fricScore），為投資組合巡檢與高息陷阱互鎖提供客觀基本面數據。使用者說「查財報」「分析基本面」「ROE多少」「自由現金流」「配息可持續性」「財務體檢」「基本面評分」時使用。
---

# 基本面財務指標與評分演算技能（fundamental-analyzer）

本技能為投資組合財報基本面分析核心引擎，專門計算個股財務比率、現金流健康度，並結合 ETF 成分股權重執行穿透加權聚合，為 `portfolio-patrol` 日常巡檢之「高息陷阱斷路互鎖」與「積極進攻姿態」提供真實客觀的感測數據。

---

## 1. 核心功能

1. **個股三大報表量化體檢**：計算自由現金流股利覆蓋倍數（FCF Coverage）、盈餘配發率（Payout Ratio）、股東權益報酬率（ROE）、營業利益率與負債權益比（D/E）。
2. **標準化四象限評分**：
   - 🛡️ **`divScore`（股利可持續性分）**：由 FCF 覆蓋率（40%）、盈餘配發率（35%）、營業現金流含金量（25%）合成。
   - 💎 **`netScore`（綜合財務健康分）**：由 ROE 資本效率（40%）、負債比安全度（30%）、營業利益率（30%）合成。
   - 🎯 **`valScore`（估值與安全邊際分）**：由本益比 P/E、股價淨值比 P/B 與當前殖利率折價合成。
   - ⚖️ **`fricScore`（摩擦阻力分）**：考量境外稅率（美股 30%、中港 10%）、二代健保 2.11% 與債券免稅優勢。
3. **ETF 穿透加權聚合（Look-through Fundamentals）**：讀取 `models/<ticker>/cards/constituents.jsonl`，自動計算 ETF 前十大重倉股之加權 ROE 與加權四象限評分。
4. **全投資組合矩陣掃描**：一鍵掃描全部 27 檔跨市場標的之基本面體質與防禦水位。

---

## 2. 常用指令

```bash
# 1. 查詢單一個股財報體檢與評分（支援台、美、日、港股）
python3 .claude/skills/fundamental-analyzer/scripts/analyzer_cli.py stock 2330.TW
python3 .claude/skills/fundamental-analyzer/scripts/analyzer_cli.py stock NVDA --json
python3 .claude/skills/fundamental-analyzer/scripts/analyzer_cli.py stock 7203.T

# 2. 查詢指定 ETF 穿透加權基本面評分
python3 .claude/skills/fundamental-analyzer/scripts/analyzer_cli.py etf 00878 --top 10
python3 .claude/skills/fundamental-analyzer/scripts/analyzer_cli.py etf 0050

# 3. 掃描全投資組合標的基本面評分矩陣
python3 .claude/skills/fundamental-analyzer/scripts/analyzer_cli.py portfolio
```

---

## 3. 防護與架構原則

1. **嚴禁修改 Core**：本技能僅作為分析運算工具，絕不寫入 `Investment_Tracker_Core`。
2. **客觀量化無情緒**：所有結論必由數學公式與財報硬數據推導，不預設立場。
3. **離線單元測試保證**：全套單元測試內建 Mock 機制，無網路環境亦可驗證。

## 建立個股卡片

```bash
python3 .claude/skills/fundamental-analyzer/scripts/analyzer_cli.py scaffold-stock 1919 \
  --symbol HKG:1919 --yf-symbol 1919.HK --title "1919 中遠海控" --currency HKD --exchange HKEX
```

卡片規格見 `architecture/個股卡片規範.md`；`portfolio-patrol` 會自動納入 `category: STOCK` 的卡片。
