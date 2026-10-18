# 資料來源與口徑（SSOT）

## 來源

| 資料 | 來源 | 備註 |
| --- | --- | --- |
| 公司公告 | 港交所披露易 `www1.hkexnews.hk`：`search/prefix.do`（代號→stockId）、`search/titleSearchServlet.do`（公告標題） | 關鍵字過濾：RESULT、DIVIDEND、PROFIT WARNING、DISTRIBUTION 等 |
| 公告原文 | 披露易 PDF，`pdftotext -layout` 轉文字 | 只接受 `www1.hkexnews.hk` 網址 |
| 南向資金 | 東方財富 `datacenter-web.eastmoney.com` 報表 `RPT_MUTUAL_DEAL_HISTORY`；`MUTUAL_TYPE` 006 合計、002 滬、004 深 | 金額單位百萬港元；附恒指收盤 |
| 南向驗證 | 港交所 `www.hkex.com.hk/eng/csm/DailyStat/data_tab_daily_YYYYMMDDe.js` | 滬＋深 Southbound 的 Buy − Sell，應與東方財富 net 相同（2026-10-09、10-14 實測一致） |
| CCASS 持股 | 港交所 `www3.hkexnews.hk/sdw/search/searchsdw.aspx`（ASP.NET 表單，先取 `__VIEWSTATE` 再 POST） | 參與者持股與占已發行股份比例；南向持股 = `A00003`（滬）＋`A00004`（深）；約可查一年內；港交所條款限個人非商業用途 |
| 港股報價 | Yahoo Finance `query1.finance.yahoo.com/v8/finance/chart/<4位代號>.HK` | 延遲報價；`prev_close` 取日線倒數第二筆 |
| 00882 持股與價格 | 中信投信 `etf/ETFHoldingWeight` | 以本週、7 天前、去年 12/31 三個日期的價格算產業加權漲跌 |
| 基準利率 (LPR) | 東方財富 `datacenter-web.eastmoney.com` 報表 `RPTA_WEB_RATE` | 1 年期與 5 年期以上貸款市場報價利率（%） |
| 國債收益率 | 中國債券信息網 `yield.chinabond.com.cn` | 中債國債 10 年期與 30 年期收益率曲線（%） |
| 雙重匯率摩擦 | Yahoo Finance `USDCNH=X`、`HKDTWD=X` | 離岸人民幣匯率與港幣兌新台幣即時匯率 |
| 航運與煤炭運價 | 上海航運交易所 `www.sse.net.cn` (`scfi`, `cbofi`) | 上海出口集裝箱運價指數 (SCFI)、中國沿海煤炭運價指數 (CBOFI) |

## 網路限制（2026-10-14 實測）

Hachi 已把 `www.hkex.com.hk`、`www.etnet.com.hk`、東方財富、Yahoo Finance、Investing.com、Webb-site 加入允許清單。

- 可用：披露易、港交所統計 JS、東方財富 datacenter、Yahoo chart API、etnet（HTML，腳本尚未解析）、富途（需無頭 Chromium）。
- 不可用：Investing.com 回 403（反爬蟲）；Webb-site 已停止更新，網址轉到 `webbhk.substack.com`；Webb-site 的 CCASS 分析改用港交所 CCASS 原始資料（2026-10-14 已加入 `www3.hkexnews.hk`）。
- 個股的南向持股變化：用 `ccass` 子指令（CCASS 的 A00003＋A00004）。

## 改版處理

回傳碼 1 或欄位缺漏時，先用 curl 看原始回應，確認是網路、改版還是休市，再修腳本與測試，不用舊數字填補。
