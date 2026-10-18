---
name: portfolio-patrol
description: 投資組合全標的自動巡檢與每日簡報。遍歷 models/*/cards/ 執行各標的 DCS 閉環求值，實施例外管理（MBE：區分穩健複利與異常跳脫），檢查數據時效性（Watchdog），並產生 Google Doc 與終端 ASCII/JSON 簡報。使用者說「巡檢全標的」「每日簡報」「檢查投資組合」「巡檢」「狀態總覽」「資產姿態」「各標的狀況」時使用。
---

# portfolio-patrol：投資組合全標的巡檢與每日簡報

- **核心腳本**：`scripts/patrol.py`（Python 標準函式庫 + PyYAML），輸出 ASCII 儀表板、JSON 或 Google Doc 格式。
- **模板與規範**：`references/briefing-template.md`。
- **唯讀保護**：嚴禁碰觸 `Investment_Tracker_Core`；公開簡報零個人張數與本金隱私。

## 用法

在 REPO 根目錄執行：

```bash
S=.claude/skills/portfolio-patrol/scripts/patrol.py

# 1. 巡檢全標的，終端輸出 ASCII 儀表板
python3 $S

# 2. 指定特定標的
python3 $S --tickers 00882

# 3. 輸出結構化 JSON
python3 $S --json

# 4. 同步原地更新至 Drive 每日簡報 Google Doc
python3 $S --sync-doc <GOOGLE_DOC_ID>

# 5. 原地更新 reports/portfolio_briefing.md，自動 commit & push 觸發 Slack 每日簡報
python3 $S --commit
```

## 核心規則

1. **例外管理（MBE）**：若全標的處於預設穩健姿態，簡報精簡扼要；若有標的觸發互鎖警報（高息陷阱、資金急流、便宜進攻、估值過高），頂部大字標記「🚨 今日焦點事項」並附上處置指引。
2. **數據心跳檢查（Watchdog）**：自動比對成分股母表與情報庫日期，若超過更新週期（如週五母表未更）則標記警告。
3. **零隱私外洩**：公開簡報只放現價、殖利率、達成率（%）、姿態代碼與宏觀數據，不放個人持股張數與成本金額。
4. **防孤兒同構執行**：Claude 雲端平日定時任務與 Antigravity 本機日常調用執行同一支 `patrol.py`，維護同一份 Google Doc。
