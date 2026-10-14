# 資料來源與口徑（SSOT）

## 來源

| 資料 | 來源 | 備註 |
| --- | --- | --- |
| 公司公告 | 港交所披露易 `www1.hkexnews.hk`：`search/prefix.do`（代號→stockId）、`search/titleSearchServlet.do`（公告標題） | 關鍵字過濾：RESULT、DIVIDEND、PROFIT WARNING、DISTRIBUTION 等 |
| 公告原文 | 披露易 PDF，`pdftotext -layout` 轉文字 | 只接受 `www1.hkexnews.hk` 網址 |
| 南向資金 | 東方財富 `datacenter-web.eastmoney.com` 報表 `RPT_MUTUAL_DEAL_HISTORY`；`MUTUAL_TYPE` 006 合計、002 滬、004 深 | 金額單位百萬港元；附恒指收盤 |
| 南向驗證 | 港交所 `www.hkex.com.hk/eng/csm/DailyStat/data_tab_daily_YYYYMMDDe.js` | 滬＋深 Southbound 的 Buy − Sell，應與東方財富 net 相同（2026-10-09、10-14 實測一致） |
| 港股報價 | Yahoo Finance `query1.finance.yahoo.com/v8/finance/chart/<4位代號>.HK` | 延遲報價；`prev_close` 取日線倒數第二筆 |
| 00882 持股與價格 | 中信投信 `etf/ETFHoldingWeight` | 以本週、7 天前、去年 12/31 三個日期的價格算產業加權漲跌 |

## 網路限制（2026-10-14 實測）

Hachi 已把 `www.hkex.com.hk`、`www.etnet.com.hk`、東方財富、Yahoo Finance、Investing.com、Webb-site 加入允許清單。

- 可用：披露易、港交所統計 JS、東方財富 datacenter、Yahoo chart API、etnet（HTML，腳本尚未解析）、富途（需無頭 Chromium）。
- 不可用：Investing.com 回 403（反爬蟲）；Webb-site 已停止更新，網址轉到 `webbhk.substack.com`；`www3.hkexnews.hk`（CCASS 持股查詢）不在允許清單。
- 個股的南向持股變化：東方財富對應報表尚未找到，暫無。

## 改版處理

回傳碼 1 或欄位缺漏時，先用 curl 看原始回應，確認是網路、改版還是休市，再修腳本與測試，不用舊數字填補。
