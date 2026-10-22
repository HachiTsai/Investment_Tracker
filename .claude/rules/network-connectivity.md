# 外部網路連線與資料來源清單

本專案於本機（Antigravity / macOS）與雲端沙盒環境（Claude Code Web）經實測可通聯之 35 個外部網域及 API 服務清單。

## 1. 核心證券交易所與主管機關

| 網域 | 服務說明 | 連線狀態 | 實務用途與讀取方式 |
| :--- | :--- | :---: | :--- |
| `www.twse.com.tw` | 台灣證券交易所官網 | ✅ HTTP 200 | 台股公告、收盤行情備援 |
| `openapi.twse.com.tw` | 證交所 OpenAPI | ✅ HTTP 200 | 自動化撈取每日收盤價與除權息資訊；上市公司季度損益與資產負債（`fundamental-analyzer` 財報資料層） |
| `mops.twse.com.tw` | 公開資訊觀測站 | ✅ HTTP 200 | 台股重大訊息、除權息公告 |
| `www.tpex.org.tw` | 證券櫃檯買賣中心 | ✅ HTTP 200 | 上櫃證券行情與除權息備援 |
| `www.hkex.com.hk` | 香港交易所官網 | ✅ HTTP 200 | 港股市場公告與交易規則 |
| `www.hkexnews.hk` | 港交所披露易 | ✅ HTTP 200 | 港股上市公司財報、業績與配息公告（`hk-market-data` 核心源） |
| `www1.hkexnews.hk` | 港交所披露易分流 1 | ✅ HTTP 200 | 披露易查詢備援節點 |
| `www3.hkexnews.hk` | 港交所披露易分流 3 | ✅ HTTP 200 | 披露易查詢備援節點 |
| `www.hsi.com.hk` | 恒生指數官網 | ✅ HTTP 200 | 恒生指數與各產業指數成分異動 |

## 2. 基金發行商與資產管理機構

| 網域 | 服務說明 | 連線狀態 | 實務用途與讀取方式 |
| :--- | :--- | :---: | :--- |
| `www.ctbcinvestments.com.tw` | 中國信託投信（台灣） | ✅ HTTP 200 | 00882 基金發行商、每日淨值與成分股權重（ETFHoldingWeight API） |
| `www.ctbcinvestments.com` | 中國信託投信（國際） | ✅ HTTP 200 | 國際版產品資訊 |
| `www.abfunds.com.tw` | 聯博投信 | ✅ HTTP 200 | 基金產品資訊 |
| `www.nomurafunds.com.tw` | 野村投信 | ✅ HTTP 200 | 基金產品資訊 |

## 3. 財經資訊平台與行情資料源

| 網域 | 服務說明 | 連線狀態 | 實務用途與讀取方式 |
| :--- | :--- | :---: | :--- |
| `finlab.finance` | FinLab 財經 | ✅ HTTP 200 | 00882 歷史配息對帳源（`price-dividend-fetcher` 引用） |
| `www.moneydj.com` | MoneyDJ 理財網 | ✅ HTTP 200 | 00882 總管理費用率、持股比例查證；台股 ETF 持股明細與資料日期（`tw-etf-fetcher`，2026-10-22 實測 00985A） |
| `finance.yahoo.com` | Yahoo Finance 網頁 | ✅ HTTP 200 | 港股、美股歷史配息與行情抓取 |
| `query1.finance.yahoo.com` | Yahoo Finance API | ✅ HTTP 429/200 | 需帶正確 Ticker 與 Cookie/Crumb 參數發送請求 |
| `www.investing.com` | Investing.com | ✅ HTTP 200 | 總體經濟指標、全球殖利率走勢 |
| `www.aastocks.com` | 阿斯達克財經網 | ✅ HTTP 200 | 港股即時報價、股利日程與分析師評級 |
| `www.etnet.com.hk` | 經濟通 | ✅ HTTP 200 | 港股深度行情、資金流向 |
| `www.futunn.com` | 富途牛牛 | ✅ HTTP 200 | 成分股歷史股息（LFY/TTM）、股息分組與公司資訊 |
| `xueqiu.com` | 雪球主站 | ✅ HTTP 200 | 陸港股市場調研與投資人討論 |
| `stock.xueqiu.com` | 雪球行情 API | ✅ HTTP 403/200 | 需帶 User-Agent 與 Cookie 繞過基本防爬 |
| `quote.eastmoney.com` | 東方財富行情 | ✅ HTTP 200 | 陸港股報價與盤面概況 |
| `datacenter-web.eastmoney.com` | 東方財富數據中心 | ✅ HTTP 200 | 港股通南向資金每日淨買入資料源；A 股損益、資產負債、現金流年報（`fundamental-analyzer`） |
| `push2.eastmoney.com` | 東方財富即時推播 | ✅ HTTP 404/200 | 即時報價推播 API（需指定完整端點） |
| `datacenter.eastmoney.com` | 東方財富 F10 數據中心 | ✅ HTTP 200 | 港股主要財務指標年報（`RPT_HKF10_FN_MAININDICATOR`，`fundamental-analyzer`；2026-10-21 實測） |
| `data.sec.gov` | SEC EDGAR 資料 API | ✅ HTTP 200 | 美股 XBRL 財報事實（需帶含聯絡資訊的 User-Agent；2026-10-21 實測） |
| `www.sec.gov` | SEC EDGAR 官網 | ✅ HTTP 200 | 代號對 CIK 對照表 `files/company_tickers.json`（2026-10-21 實測） |
| `api.edinet-fsa.go.jp` | 金融廳 EDINET API v2 | ✅ HTTP 200 | 日股有價證券報告書清單與財報 CSV（`fundamental-analyzer`）；API key 由環境「網路密鑰」以標頭注入，腳本不帶 key，無 key 時回 401（2026-10-21 實測） |
| `api.finmindtrade.com` | FinMind 開放資料 API | ✅ HTTP 200 | 台股（上市與上櫃）現金流量表、資產負債表、損益表歷年季度，另有現金股利歷次分配（`TaiwanStockDividend`）、股價淨值比（`TaiwanStockPER`）、產業別（`TaiwanStockInfo`）；匿名有頻率限制（`fundamental-analyzer` 台股主來源，成分股明細頁快取 6 小時並可用 `FINMIND_TOKEN` 提高上限；2026-10-21 實測） |
| `tw.stock.yahoo.com` | Yahoo 股市（台灣） | ✅ HTTP 200 | 台股現金流量表頁，資料嵌在網頁 JSON，非官方、改版即失效（`fundamental-analyzer` 台股備援；2026-10-21 實測） |
| `mops.twse.com.tw` 報表端點、`goodinfo.tw` | MOPS 財報查詢、Goodinfo | ❌ 被擋 | MOPS 對非瀏覽器請求回「安全性考量無法呈現」，Goodinfo 被 Cloudflare 擋（403），不採用（2026-10-21 實測） |
| `webb-site.com` | Webb-site | ✅ HTTP 200 | 港股 CCASS 股權集中度與股東持股變動 |
| `www.webb-site.com` | Webb-site 完整域名 | ✅ HTTP 200 | 同上 |

## 4. 基礎搜尋、開發與沙盒網域

| 網域 | 服務說明 | 連線狀態 | 實務用途與讀取方式 |
| :--- | :--- | :---: | :--- |
| `www.google.com` | Google 搜尋引擎 | ✅ HTTP 200 | 國內外財經新聞與投資資訊檢索 |
| `pypi.org` | Python Package Index | ✅ HTTP 200 | Python 套件索引與資訊查詢 |
| `files.pythonhosted.org` | PyPI 下載節點 | ✅ HTTP 404/200 | 套件檔案下載（需指定完整路徑） |
| `*.frame.claudeusercontent.com` | Claude 沙盒內嵌網域 | ✅ 可解析/連線 | Claude Code 網頁端預覽與資料渲染 |
| `*.frame.staging.claudeusercontent.com` | Claude 預發沙盒網域 | ✅ 可解析/連線 | Claude 預發環境 |
