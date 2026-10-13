# 資料來源與解析規則（SSOT）

腳本 `scripts/fetch.py` 只讀取下列公開網頁，不寫任何檔案，不碰 Investment_Tracker_Core。

## 來源

| 資料 | 來源 | 範圍 | 備註 |
| --- | --- | --- | --- |
| 現價、前收、漲跌 | Google Finance `https://www.google.com/finance/quote/<代號>:<交易所>` | 台股、美股、日股、港股 | CLAUDE.md 指定的股價來源；盤中為即時（可能延遲），收盤後為收盤價 |
| 收盤價（備援） | 證交所 `https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX` | 台股上市 | 當日全市場收盤表；Google Finance 失敗時自動改用，輸出標 `price_type: close` |
| 配息歷史（主） | FinLab `https://finlab.finance/stocks/<代號>/dividend` | 台股 | 研究筆記 `00882_股利追蹤` 使用的來源 |
| 配息歷史（驗證） | 證交所 `https://www.twse.com.tw/rwd/zh/exRight/TWT49U` | 台股上市 | 官方除權息結果表，只取「息」；與 FinLab 比對近兩個年度 |
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

## 網路限制（2026-10-13 實測）

環境的網路政策只放行部分網域。目前白名單包含 `www.google.com`、`finlab.finance`、`www.twse.com.tw`、`openapi.twse.com.tw`、`www.ctbcinvestments.com.tw`、`pypi.org`、`files.pythonhosted.org`。

- **不在白名單（代理回 403）**：Yahoo Finance、`mis.twse.com.tw`、TPEx、FinMind、Stooq。因此海外標的**沒有配息歷史來源**，只有 Google Finance 的摘要。
- **在白名單但被網站防護擋下**：`openapi.twse.com.tw` 全部回「因安全性考量無法呈現」；`www.twse.com.tw` 的個股日成交 `STOCK_DAY` 同樣被擋。
- **證交所的 `rwd` 端點可用，但有條件**：
  - 要帶瀏覽器 User-Agent 與 Referer。
  - 防護機制間歇性回 307（實測約 6 次 1 次），腳本重試 3 次。
  - 除權息查詢的結束日**不可超過今天**，否則會被擋；區間跨多年會被重置連線，所以逐年查，每次間隔 3 秒。
- 若日後白名單放寬，再加來源並更新本表。

## 解析規則

- **Google Finance 現價**：頁面內嵌多檔商品（側欄的指數、期貨等），所以用 `["代號","交易所"],"名稱",型別,"幣別",[現價,漲跌,漲跌幅,…],null,前收,…,[epoch]` 定位主報價，代號與交易所都要吻合。`epoch` 轉成 UTC 寫入 `as_of`。
- **Google Finance 配息摘要**：頁面「標籤／數值」成對的欄位中，標籤含 `ividend` 者（`Dividend`、`Ex-dividend date`、`Quarterly dividend` 等）。標籤是 Google 的原文，不保證與實際配息頻率一致（例如半年配的股票也可能標 Quarterly），金額以公司公告為準。
- **FinLab 配息**：明細表每列四欄，依序為除息交易日、每單位配發（元）、收益分配基準日、發放日。
- **證交所收盤**：`MI_INDEX` 中含「收盤價」欄位的表。漲跌方向取自 `漲跌(+/-)` 欄的 HTML，前收 = 收盤 − 漲跌。
- **證交所除權息**：`TWT49U` 的民國日期轉西元；`權/息` 欄為「息」者才算現金股利，金額取「權值+息值」。
- **交叉驗證**：以除息日為鍵，金額差 > 0.005 或一邊缺少，記入 `crosscheck.differences`。
- **殖利率**：近 12 個月（含今日往前 365 天，以除息日計）配息合計 ÷ 現價，符合 CLAUDE.md 的口徑。FinLab 頁面上的殖利率以前一日收盤計，可能差 0.01–0.05 個百分點。
- 配息金額是**每單位**，不是實收；實收要依持股數與二代健保扣除計算，見股利目標模型。

## 頁面改版時

這些來源都是網頁而不是正式 API，改版後解析會失敗。腳本遇到找不到資料時直接報錯（回傳碼 1），**不得用猜測值或舊數字補上**。處理方式：

1. 用 `curl` 抓頁面（帶瀏覽器 User-Agent），找出報價或配息表的新結構。
2. 修改 `fetch.py` 的解析函式，並更新 `tests/test_fetch.py` 的樣本。
3. 同步更新本檔。

## 已知限制

- 海外標的只有現價與 Google 的配息摘要，沒有配息歷史、也不能算近 12 個月殖利率。
- 不含股價歷史；只有最新價與前收。
- 海外標的的幣別為原幣（USD、JPY、HKD），換算台幣要用 Core 的 `Exchange_Rates`，腳本不處理。
- 除息公告早於除息日時，FinLab 與證交所可能尚未列出，要以投信公告為準。
