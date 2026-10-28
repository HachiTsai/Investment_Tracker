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

- 產生 49 檔成分股「股利與財報明細」頁與 `table.json`：持股、股數、權重取中信投信官方 API，股價取 Google Finance（`price-dividend-fetcher`），年化股息（已除息的最近兩次定期分配合計；有季度分配取 4 次，只有年度分配取 1 次；不含特別分配）、上財年股息與中期股利取東方財富歷次分配（不再用富途牛牛與無頭 Chromium），頁面範本與渲染改由 `tw-etf-fetcher` 共用（`references/constituents_template.html`、`scripts/etf_page.py` 的 `hk` 設定）。頁面兩個分頁：**財報（主頁）**與股利明細。財報頁重點指標在前（單季／單期 EPS、累計 EPS、當年度已配發股息、當期配息率與上年度配息率、股價、ROE、配發率、經營現金流、營收、PB、PE），其餘指標與規則式訊號在後，點一檔開視窗看趨勢圖與近 8 期明細；財報取自 `fundamental-analyzer` 的東方財富資料層 `hk_detail`（含近 10 期累計數，單季與年增由 `fundamental-analyzer/scripts/fin_trend.py` 推算（港股、台股共用）；歷次分配取 `hk_dividends`（東方財富 `RPT_HKF10_MAIN_DIVBASIC`），當年度已配發＝今年付款日已過的每股股息合計，當期配息率＝最近一次宣派 ÷ 對應期間累計 EPS，上年度配息率＝上一年報財年全年現金股息 ÷ 年報 EPS（幣別不同時以隱含匯率近似，EPS 為負或最近一期未宣派則留空），金額為報表幣別不換算；`fin_fails` 列出抓不到財報的代號）。股利明細分頁以同一份歷次分配計算上財年與前一財年全年股息、最近一次中期對去年中期的增減（不再用公告標題與搜尋摘要）。財報頁後段另有毛利率、淨利率、ROA、ROIC、流動比率（東方財富最近一期）與股息覆蓋、連續配息年數、股息年複合成長（歷次分配推算）。另有自由現金流覆蓋（`hk_cashflow`：經營現金流減購建固定資產，除以已付股息，金融業不適用）與 PB 相對合理值（PB ÷ ROE÷10%，要求報酬率 10% 為假設）。欄位標題與個股視窗的指標旁有 ⓘ，點開跳出說明小視窗（文字在範本 `HELP`）。富途抓不到殖利率的檔仍列入財報頁（殖利率留白，`__MISS__`）。每欄可篩選，代號與名稱欄及標題列固定。估值位置（`fundamental-analyzer` 的 `fin_trend.valuation_position`）用 Yahoo 近 5 年未還原日收盤價（`price-dividend-fetcher` 的 `get_yahoo`）與歷次分配算「殖利率歷史分位」（目前年化殖利率在歷史同口徑殖利率中的分位，越高越便宜）與「股價 5 年高低位置」，Yahoo 抓不到時這兩欄留白。財報頁摘要卡有「00882 整體本益比」：以成分股權重對東方財富 PE（TTM）做調和加權（Σ權重 ÷ Σ權重／PE），PE 為負或缺值的檔不納入並顯示涵蓋檔數與權重，另拆金融股與其他。財報頁的「選擇欄位」可按群組（EPS 與配息、營收與獲利成長、獲利品質、償債與現金流、股息可持續性、估值）或逐欄勾選要看的欄位，設定記在瀏覽器（localStorage，鍵 `fincols.v1`），群組定義在範本 `GRP`。
- 用法：`python3 .claude/skills/hk-market-data/scripts/constituents_table.py out.html [prev.html] [table.json]`，約 1 分鐘；`prev.html` 是上一版頁面，用來沿用去年欄位。輸出的 JSON 摘要有 `rows`、`fails`、`has26`、`pool_rows`（收益平準金每日資料列數，0 代表抓取失敗、頁面缺少該分頁，`--gate` 會擋），`fails`（缺股價或歷次分配的檔，仍會列在財報頁、殖利率留白）超過 5 檔或連不上 google.com／datacenter.eastmoney.com／ctbcinvestments.com.tw 就不要發佈。殖利率欄的分子是這個年化股息（2026-10-22 Hachi 選定），避免中期股息剛除息時「最近 12 個月」含到三次而高估。
- 頁面第三個分頁「收益平準金」：每日收益平準金與資本平準金走勢、歷次配息表（資料來自中信投信 `product/GetNAV`，由 `tw-etf-fetcher` 的 `nav_composition.py` 抓取；抓取失敗只印警告、頁面缺該分頁，不擋整頁）。
- 這支腳本只產生頁面與 JSON，不寫 Drive、不碰 Investment_Tracker_Core；寫 Sheet 由排程用 Sheets 工具做，且不得放持股張數、成本、缺口等個人部位數字。
- 腳本載入時即連網抓資料，測試只做靜態檢查（編譯、佔位符與範本一致）。
