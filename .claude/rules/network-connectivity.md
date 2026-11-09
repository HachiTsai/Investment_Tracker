# 外部網路連線與資料來源清單

本專案於本機（Antigravity / macOS）與雲端沙盒環境（Claude Code Web）經實測可通聯之 38 個外部網域及 API 服務清單。

## 1. 核心證券交易所與主管機關

| 網域 | 服務說明 | 連線狀態 | 實務用途與讀取方式 |
| :--- | :--- | :---: | :--- |
| `www.twse.com.tw` | 台灣證券交易所官網 | ✅ HTTP 200（連續請求會回 307） | 台股公告、收盤行情備援；三大法人買賣金額（`BFI82U`）、信用交易統計融資餘額（`MI_MARGN`）、市場成交資訊加權指數（`FMTQIK`）供巡檢頁市場修正追蹤（`market_stress.py`）。短時間連續請求會被防護擋下，回 HTTP 307 與「因為安全性考量」頁，跟隨轉址也拿不到資料（2026-11-05 實測：連發約六成被擋、間隔 3 秒約一成）；`fetch_common.twse_get` 全程序節流每 3 秒一次、被擋後等 10／20／30 秒重試，不偽裝瀏覽器 |
| `openapi.twse.com.tw` | 證交所 OpenAPI | ✅ HTTP 200 | 自動化撈取每日收盤價與除權息資訊；上市公司季度損益與資產負債（`fundamental-analyzer` 財報資料層） |
| `openapi.taifex.com.tw` | 期交所 OpenAPI | ✅ HTTP 200 | 三大法人臺股期貨未平倉淨額（`MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate`，只有最新一日），供巡檢頁市場修正追蹤（`market_stress.py`；2026-11-05 實測） |
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
| `www.ctbcinvestments.com.tw` | 中國信託投信（台灣） | ⚠️ 2026-11-06 雲端沙盒整站 HTTP 403（Incapsula，連 `robots.txt` 也擋） | 00882 基金發行商；與 `.com` 為同一套 API（ETFHoldingWeight、`product/GetNAV` 等，需先取 token）。2026-11-06 實測距上次請求數小時、只送一次仍 403，判斷為來源 IP 被封鎖，不是請求頻率；同時間 `.com` 正常。現為備援網域：`ctbc_api.py` 先打 `.com`，被 403 才換這裡送一次。 |
| `www.ctbcinvestments.com` | 中國信託投信（國際） | ✅ HTTP 200 | 中信投信 API 主網域（2026-11-06 起，Hachi 同意）：AuthToken、ETFHoldingWeight、`product/GetNAV` 實測可用（2026-11-06）。所有中信投信請求經 `tw-etf-fetcher/scripts/ctbc_api.py` 送出：連續請求至少間隔 3 秒、同程序同一網域只取一次 token；遇 403 該網域本程序內不再使用，改用下一個網域送一次，同網域不重試，全部被擋才停止。不偽裝瀏覽器、不繞過防護。 |
| `www.abfunds.com.tw` | 聯博投信 | ✅ HTTP 200 | 基金產品資訊 |
| `www.nomurafunds.com.tw` | 野村投信 | ✅ HTTP 200 | 基金產品資訊 |

## 3. 財經資訊平台與行情資料源

| 網域 | 服務說明 | 連線狀態 | 實務用途與讀取方式 |
| :--- | :--- | :---: | :--- |
| `finlab.finance` | FinLab 財經 | ✅ HTTP 200 | 00882 歷史配息對帳源（`price-dividend-fetcher` 引用） |
| `www.moneydj.com` | MoneyDJ 理財網 | ✅ HTTP 200 | 00882 總管理費用率、持股比例查證；台股 ETF 持股明細與資料日期（`tw-etf-fetcher`，2026-10-22 實測 00985A） |
| `finance.yahoo.com` | Yahoo Finance 網頁 | ✅ HTTP 200 | 港股、美股歷史配息與行情抓取 |
| `query1.finance.yahoo.com` | Yahoo Finance API | ✅ HTTP 429/200 | 需帶正確 Ticker 與 Cookie/Crumb 參數發送請求 |
| `query2.finance.yahoo.com` | Yahoo Finance API（Crumb 與基本面端點） | ✅ HTTP 429 | yfinance 取得 Crumb 與基本面時序；美股、日股前幾大持股與財報備援經由 yfinance 取得（2026-10-27 探測回 429，限流中，可連線但可用性依限流狀況而定） |
| `fc.yahoo.com` | Yahoo Cookie 端點 | ✅ HTTP 404 | yfinance 取得 Cookie 的端點；根路徑回 404 但會發出 Set-Cookie，屬正常（2026-10-27 實測） |
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
| `api.edinet-fsa.go.jp` | 金融廳 EDINET API v2 | ✅ HTTP 200 | 日股有價證券報告書清單與財報 CSV（`fundamental-analyzer`）；API key 在沙盒由環境「網路密鑰」注入；GitHub Actions 讀 secret `EDINET_API_KEY`，以 `Subscription-Key` 查詢參數帶上（EDINET 仕様書的參數名），無 key 時回 401（2026-10-21 實測）；2026-10-27 Actions 讀到空白或空值時，下載的回應不是 zip（日誌為 BadZipFile），未見 HTTP 401，以日誌印出的原因為準 |
| `api.finmindtrade.com` | FinMind 開放資料 API | ✅ HTTP 200 | 台股（上市與上櫃）現金流量表、資產負債表、損益表歷年季度，另有現金股利歷次分配（`TaiwanStockDividend`）、股價淨值比（`TaiwanStockPER`）、產業別（`TaiwanStockInfo`）；匿名有頻率限制（`fundamental-analyzer` 台股主來源，成分股明細頁快取 6 小時並可用 `FINMIND_TOKEN` 提高上限；2026-10-21 實測） |
| `tw.stock.yahoo.com` | Yahoo 股市（台灣） | ✅ HTTP 200 | 台股現金流量表頁，資料嵌在網頁 JSON，非官方、改版即失效（`fundamental-analyzer` 台股備援；2026-10-21 實測） |
| `mops.twse.com.tw` 報表端點、`goodinfo.tw` | MOPS 財報查詢、Goodinfo | ❌ 被擋 | MOPS 對非瀏覽器請求回「安全性考量無法呈現」，Goodinfo 被 Cloudflare 擋（403），不採用（2026-10-21 實測） |
| `www.binance.com` | 幣安（`/fapi/v1` 合約公開行情） | ✅ HTTP 200 | USDⓈ-M 合約日線 K 線（`klines`）、資金費率（`fundingRate`）、合約清單（`exchangeInfo`，含美股代幣化合約如 `TQQQUSDT`），供 `price-dividend-fetcher` 的 `backtest.py`；不需帳號。`api.binance.com`、`fapi.binance.com` 在雲端沙盒回 HTTP 451（地區限制），不採用（2026-11-06 實測） |
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
| `sheets.googleapis.com` | Google Sheets API v4 | ✅ HTTPS 443 | 供 GitHub Actions 與本機排程透過 `GCP_SA_KEY` 服務帳號直寫外圍公開／協作試算表（嚴禁對 Core 授權） |
| `docs.google.com` | Google 試算表公開連結（gviz CSV） | ✅ HTTP 200 | 每日巡檢頁讀波段觀察 Sheet「告警紀錄」分頁（`swing.py --alerts-from-sheet`），只讀公開連結、不帶憑證，ID 取自 `DRIVE_IDS` 的 `SWING_SHEET_ID`；讀不到不中止發布（2026-11-09 實測，Hachi 同意） |
| `oauth2.googleapis.com` | Google OAuth 2.0 憑證端點 | ✅ HTTPS 443 | 供 `google-auth` 以服務帳號私鑰簽發並刷新存取權杖（Access Token） |
| `api.github.com` | GitHub REST API | ✅ HTTP 200 | 排程健康檢查（`fin-commit/scripts/schedule_health.py`）讀取工作流的排程執行紀錄與建立時間，`swing-patrol.yml` 漏跑時補送 `workflow_dispatch`（2026-11-09 Hachi 同意，Issue #232）；CI 內以 `GITHUB_TOKEN`（`actions: write`）呼叫，沙盒經代理注入（2026-10-28 實測） |
