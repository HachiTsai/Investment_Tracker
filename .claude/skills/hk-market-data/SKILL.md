---
name: hk-market-data
description: 查港股資料（唯讀）：港交所披露易的業績、股息、盈利警告公告與 PDF 原文數字，CCASS 持股與個股南向持股比例變化，港股通南向資金每日淨買入（東方財富，港交所交叉驗證），Yahoo Finance 港股報價，00882 成分股各產業加權漲跌，以及宏觀指標（LPR利率、中債10年/30年國債收益率、USD/CNH與HKD/TWD匯率、SCFI運價與沿海煤炭運價）。使用者說「查港交所公告」「對照財報原文」「南向資金」「港股通流向」「CCASS」「誰在買」「南向持股」「港股報價」「00882 產業漲跌」「舊經濟風向」「宏觀指標」「國債殖利率」「LPR」「匯率」「SCFI運價」，或要核對港股財報、股息數字、更新 00882 風向週報時使用。
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
python3 $S macro                             # 宏觀指標：LPR利率、中債10年/30年國債收益率、雙重匯率、SCFI運價、沿海煤炭運價
```

代號可寫 `939`、`0939`、`00939`。多檔查詢時單檔失敗只影響該筆（`error`），回傳碼為 1。

## 使用規則

1. **財報數字以港交所公告原文為準**：先 `announce` 找公告，再 `pdf --grep` 讀出原文數字；媒體轉述與公告不同時，以公告為準並註明更正。
2. **寫明來源與時間**：例如「南向 10/14 淨賣出 1.35 億港元（東方財富，港交所驗證一致）」。
3. **單位**：南向資金為百萬港元；公告金額幣別依原文（人民幣或港元混用）。
4. **查不到就說查不到**：連線失敗或網站改版時如實回報，不用估值補上。
5. **產業分組是 Claude 的歸類**：`SECTOR` 對照表在腳本內；`unmapped` 不為空代表 00882 換股，先更新對照表。
6. **事實與觀點分開**：抓到的是事實；由此推論配息或景氣，要標明是觀點與假設。

## 風向日報底稿（`references/wind_report.html`）

- 00882 舊經濟風向日報的頁面底稿，每日排程以它為基礎，更新日期、產業漲跌表、資金流向、南向持股變化表、各產業新事實與結論後，發佈到固定的 Artifact 網址。
- 排程在乾淨的 session 執行，改過的頁面不會寫回 REPO；要延續前一天的內容，先讀取目前已發佈的 Artifact 當基礎，底稿只在第一次或版面需要重置時使用。
- 版面調整（欄位、樣式）直接改這份底稿並走 PR；每日資料不要 commit。
- 事實附來源與日期，港交所核對過的標「港交所」，觀點標為觀點。

## 00882 成分股股利表（`scripts/constituents_table.py`）

- 產生 49 檔成分股股利明細頁與 `table.json`：持股、股數、權重取中信投信官方 API，股息 TTM／LFY 與中期股利取富途牛牛（需無頭 Chromium），頁面範本為 `references/constituents_template.html`。
- 用法：`python3 .claude/skills/hk-market-data/scripts/constituents_table.py out.html [prev.html] [table.json]`，約 10 分鐘；`prev.html` 是上一版頁面，用來沿用去年欄位。輸出的 JSON 摘要有 `rows`、`fails`、`has26`，`fails` 超過 5 檔或連不上 futunn.com／ctbcinvestments.com.tw 就不要發佈。
- 這支腳本只產生頁面與 JSON，不寫 Drive、不碰 Investment_Tracker_Core；寫 Sheet 由排程用 Sheets 工具做，且不得放持股張數、成本、缺口等個人部位數字。
- 腳本載入時即連網抓資料，測試只做靜態檢查（編譯、佔位符與範本一致）。
