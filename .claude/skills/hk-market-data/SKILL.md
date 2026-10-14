---
name: hk-market-data
description: 查港股資料（唯讀）：港交所披露易的業績、股息、盈利警告公告與 PDF 原文數字，CCASS 持股與個股南向持股比例變化，港股通南向資金每日淨買入（東方財富，港交所交叉驗證），Yahoo Finance 港股報價，以及 00882 成分股各產業加權漲跌。使用者說「查港交所公告」「對照財報原文」「南向資金」「港股通流向」「CCASS」「誰在買」「南向持股」「港股報價」「00882 產業漲跌」「舊經濟風向」，或要核對港股財報、股息數字、更新 00882 風向週報時使用。
---

# hk-market-data：港股資料查詢

- **腳本**：`scripts/hkdata.py`（Python 標準函式庫，PDF 用系統的 `pdftotext`），輸出 JSON。
- **來源與口徑（SSOT）**：`references/sources.md`，包含哪些網站雲端讀不到。
- **唯讀**：只讀公開網站，不寫檔、不碰 Investment_Tracker_Core。

## 用法

在 REPO 根目錄執行：

```bash
S=.claude/skills/hk-market-data/scripts/hkdata.py
python3 $S announce 0939 1919 --days 30      # 業績、股息、盈利警告公告；--all 列全部公告
python3 $S pdf <披露易PDF網址> --grep "per share|net profit"
python3 $S ccass 0939 --compare-days 7       # CCASS 前十大持股與南向（港股通）持股比例變化
python3 $S southbound --days 10 --crosscheck  # 南向每日淨買入，百萬港元
python3 $S quote 0939 1919 --range 1mo        # 現價、前收、區間漲跌、52 週高低
python3 $S sectors --announce-days 8          # 00882 各產業近一週、今年以來加權漲跌＋成分股公告
```

代號可寫 `939`、`0939`、`00939`。多檔查詢時單檔失敗只影響該筆（`error`），回傳碼為 1。

## 使用規則

1. **財報數字以港交所公告原文為準**：先 `announce` 找公告，再 `pdf --grep` 讀出原文數字；媒體轉述與公告不同時，以公告為準並註明更正。
2. **寫明來源與時間**：例如「南向 10/14 淨賣出 1.35 億港元（東方財富，港交所驗證一致）」。
3. **單位**：南向資金為百萬港元；公告金額幣別依原文（人民幣或港元混用）。
4. **查不到就說查不到**：連線失敗或網站改版時如實回報，不用估值補上。
5. **產業分組是 Claude 的歸類**：`SECTOR` 對照表在腳本內；`unmapped` 不為空代表 00882 換股，先更新對照表。
6. **事實與觀點分開**：抓到的是事實；由此推論配息或景氣，要標明是觀點與假設。
