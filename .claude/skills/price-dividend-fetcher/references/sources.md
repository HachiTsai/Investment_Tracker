# 資料來源與解析規則（SSOT）

腳本 `scripts/fetch.py` 只讀取下列公開網頁，不寫任何檔案，不碰 Investment_Tracker_Core。

## 來源

| 資料 | 來源 | 範圍 | 備註 |
| --- | --- | --- | --- |
| 現價、前收、漲跌（主） | Google Finance `https://www.google.com/finance/quote/<代號>:<交易所>` | 台股、美股、日股、港股 | CLAUDE.md 指定的股價來源；盤中為即時（可能延遲），收盤後為收盤價 |
| 現價、前收、漲跌（備援） | Yahoo Finance `https://query1.finance.yahoo.com/v8/finance/chart/<Yahoo 代號>` | 全市場，含上櫃 | Google Finance 失敗時自動改用（上櫃股 Google 查不到，實際上走這條）；`fallback_reason` 會記錄原因 |
| 收盤價（最後備援） | 證交所 `https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX` | 台股上市 | 當日全市場收盤表；前兩個來源都失敗時自動改用，輸出標 `price_type: close` |
| 收盤價（最後備援） | 櫃買中心 `https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?type=EW&response=json` | 台股上櫃 | 不帶日期即最近交易日；證交所找不到代號時接著用，輸出標 `price_type: close` |
| 配息歷史（海外） | Yahoo Finance chart API，`events=div`、`range=10y` | 美股、日股、港股 | 只有除息日與每單位金額，沒有基準日、發放日；已還原股票分割，金額為交易幣別 |
| 配息歷史（主） | FinLab `https://finlab.finance/stocks/<代號>/dividend` | 台股 ETF | 研究筆記 `00882_股利追蹤` 使用的來源 |
| 配息歷史（個股備援） | FinLab 個股頁 `https://finlab.finance/stocks/<代號>` | 台股個股 | 個股沒有 `/dividend` 頁（404），改讀「近期除息紀錄」表；金額四捨五入到 0.1 元，只列近約 6 次 |
| 配息歷史（台股備援） | 同上 Yahoo Finance | 台股 | FinLab 兩個頁面都讀不到時改用，不做證交所驗證，輸出附 `fallback_reason` |
| 配息歷史（驗證） | 證交所 `https://www.twse.com.tw/rwd/zh/exRight/TWT49U` | 台股上市 | 官方除權息結果表，取「息」與「權息」；「權息」的金額是權值＋息值，只比對除息日不比金額；與 FinLab 比對近兩個年度 |
| 最近配息摘要 | Google Finance 頁面的 Dividend 欄位 | 全市場 | 頁面顯示的原文（殖利率、最近除息日、最近一次金額），非完整歷史 |
| 配息日曆（人工比對） | 中信投信 `https://www.ctbcinvestments.com.tw/Product/DividendCalendar` | 00882 | 腳本不解析 |

## 代號格式

`交易所:代號`，與 Core 的 `TPE:00882` 一致；只寫代號視為台股。

| 市場 | 交易所 | 範例 |
| --- | --- | --- |
| 台股 | `TPE` | `TPE:00882` |
| 美股 | `NASDAQ`、`NYSE`、`NYSEARCA`、`NYSEAMERICAN` | `NASDAQ:AAPL`、`NYSEARCA:VOO` |
| 日股 | `TYO` | `TYO:7203` |
| 港股 | `HKG` | `HKG:0005`、`HKG:2800` |

## 網域與可用性（2026-10-14 實測）

環境的網路政策只放行部分網域，白名單由 Hachi 維護。以下是和本 skill 相關的網域，**實測結果**與用途：

| 網域 | 實測 | 本 skill 的用途 |
| --- | --- | --- |
| `www.google.com` | 可用 | 主要報價來源（Google Finance） |
| `query1.finance.yahoo.com` | 可用，需短 UA | 備援報價、海外與台股配息；`query2` 不在白名單 |
| `finlab.finance` | 可用 | 台股配息主來源 |
| `www.twse.com.tw` | `rwd` 端點可用（有條件，見下） | 台股收盤備援、除權息驗證 |
| `www.tpex.org.tw` | 可用 | 上櫃股收盤備援 |
| `www.moneydj.com` | 可用 | **未實作**。ETF 配息頁 `ETF/X/Basic/Basic0005.xdjhtm?etfid=<代號>.TW` 有基準日、除息日、發放日、金額，數字與其他來源一致，但只有近兩年且只有 ETF，和證交所驗證的範圍重疊 |
| `www.ctbcinvestments.com.tw`、`www.ctbcinvestments.com`、`www.abfunds.com.tw`、`www.nomurafunds.com.tw` | 首頁可連 | 投信官網，只用於人工查配息公告，不解析（各家格式不同） |
| `finance.yahoo.com` | 可連，頁面約 1 MB | 不使用，`query1` 的 API 已足夠 |
| `openapi.twse.com.tw` | 被網站防護擋下 | 不可用 |
| `mops.twse.com.tw` | 被網站防護擋下（回「無法呈現」） | 不可用 |
| `www.investing.com` | 403 | 不可用 |
| `stock.xueqiu.com` | API 回 400，需登入 | 不可用 |
| `www.aastocks.com` | 連線失敗 | 不可用 |
| `www.hkexnews.hk`、`www1.hkexnews.hk`、`www3.hkexnews.hk`、`www.hkex.com.hk`、`www.etnet.com.hk`、`www.futunn.com`、`xueqiu.com`、東方財富（`quote`、`datacenter-web`、`push2`）、`webb-site.com`、`www.hsi.com.hk` | — | 港股專用，歸 `hk-market-data` skill，見它的 `references/sources.md` |

**不在白名單（代理回 403）**：`query2.finance.yahoo.com`、`mis.twse.com.tw`、FinMind、Stooq。

### 各站的使用條件

- **Yahoo 的 User-Agent 要短**：用 `Mozilla/5.0` 回 200；用完整的 Chrome UA 反而回 429（Too Many Requests）。腳本的 `YAHOO_UA` 就是為此獨立設定。
- **證交所的 `rwd` 端點**：
  - 要帶瀏覽器 User-Agent 與 Referer。
  - 防護機制間歇性回 307（實測約 6 次 1 次），腳本重試 3 次。
  - 除權息查詢的結束日**不可超過今天**，否則會被擋；區間跨多年會被重置連線，所以逐年查，每次間隔 3 秒。
  - 個股日成交 `STOCK_DAY` 同樣被防護擋下。
- **櫃買中心**：不帶 `date` 參數回最近交易日（回應的 `date` 欄為 `YYYYMMDD`）；帶非交易日的日期會回 0 筆。
- 白名單變動時，更新本表。

## 解析規則

- **Google Finance 現價**：頁面內嵌多檔商品（側欄的指數、期貨等），所以用 `["代號","交易所"],"名稱",型別,"幣別",[現價,漲跌,漲跌幅,…],null,前收,…,[epoch]` 定位主報價，代號與交易所都要吻合。`epoch` 轉成 UTC 寫入 `as_of`。
- **Google Finance 配息摘要**：頁面「標籤／數值」成對的欄位中，標籤含 `ividend` 者（`Dividend`、`Ex-dividend date`、`Quarterly dividend` 等）。標籤是 Google 的原文，不保證與實際配息頻率一致（例如半年配的股票也可能標 Quarterly），金額以公司公告為準。
- **FinLab 配息**：明細表每列四欄，依序為除息交易日、每單位配發（元）、收益分配基準日、發放日。
- **FinLab 個股頁**：「近期除息紀錄」每列為除息日（`th`）、股利所屬期間、現金股利、股票股利；「—」代表沒有，現金為「—」時 `amount` 記 0。
- **證交所收盤**：`MI_INDEX` 中含「收盤價」欄位的表。漲跌方向取自 `漲跌(+/-)` 欄的 HTML，前收 = 收盤 − 漲跌。
- **櫃買中心收盤**：回應 `tables[0]` 的欄位名稱帶空白，要先 strip；`漲跌` 欄為「+5.00」「-3.00」「0.00」，除息日等特殊日是文字，這時前收與漲跌回 null；收盤為「----」代表未成交。
- **證交所除權息**：`TWT49U` 的民國日期轉西元；`權/息` 欄為「息」者才算現金股利，金額取「權值+息值」。
- **交叉驗證**：以除息日為鍵，金額差 > 0.005 或一邊缺少，記入 `crosscheck.differences`。
- **Yahoo 代號**：台股上市 `<代號>.TW`、上櫃 `<代號>.TWO`（代號看不出差別，所以先試 `.TW`，404 再試 `.TWO`）、日股 `<代號>.T`、港股補零到 4 位加 `.HK`（`00700` → `0700.HK`）、美股 `.` 換成 `-`（`BRK.B` → `BRK-B`）。
- **Yahoo 現價與前收**：現價取 `meta.regularMarketPrice`。前收**不能用** `meta.chartPreviousClose`（那是查詢區間起點之前的收盤，5 年區間會差到好幾倍），改取日線中最近一個「早於今日交易日」的收盤，日期以 `meta.gmtoffset` 換成交易所當地日期判斷。
- **Yahoo 配息**：`events.dividends` 的每筆 `date`（UTC 日期即除息日）與 `amount`。特別股息也會列入，近 12 個月合計與殖利率會因此偏高（例如 HSBC 2026-03-12 的 3.52 港元）；沒有配息的公司回空清單，不算錯誤。
- **殖利率**：近 12 個月（含今日往前 365 天，以除息日計）配息合計 ÷ 現價，符合 CLAUDE.md 的口徑。FinLab 頁面上的殖利率以前一日收盤計，可能差 0.01–0.05 個百分點。
- 配息金額是**每單位**，不是實收；實收要依持股數與二代健保扣除計算，見股利目標模型。

## 頁面改版時

這些來源都是網頁而不是正式 API，改版後解析會失敗。腳本遇到找不到資料時直接報錯（回傳碼 1），**不得用猜測值或舊數字補上**。處理方式：

1. 用 `curl` 抓頁面（帶瀏覽器 User-Agent），找出報價或配息表的新結構。
2. 修改 `fetch.py` 的解析函式，並更新 `tests/test_fetch.py` 的樣本。
3. 同步更新本檔。

## 已知限制

- 海外標的的配息來自單一來源（Yahoo），沒有第二來源可交叉驗證；Yahoo 的金額偶爾與公司公告有小數位差異，重要數字以公告為準。
- Yahoo 的海外配息沒有基準日與發放日；ADR 或外幣配息的公司（例如以美元配息的 HSBC），金額是 Yahoo 換算後的交易幣別。
- 不含股價歷史；只有最新價與前收。
- 上櫃股的 Google Finance 沒有頁面（交易所碼不是 `TPE`），價格實際來自 Yahoo；Yahoo 也失敗時只剩櫃買中心的收盤價。上櫃股 FinLab 可能沒有配息頁，會改用 Yahoo，沒有交叉驗證。
- 海外標的的幣別為原幣（USD、JPY、HKD），換算台幣要用 Core 的 `Exchange_Rates`，腳本不處理。
- 除息公告早於除息日時，各來源可能尚未列出，要以投信或公司公告為準。
