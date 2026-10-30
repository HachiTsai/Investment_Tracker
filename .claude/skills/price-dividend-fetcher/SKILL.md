---
name: price-dividend-fetcher
description: 抓台股、美股、日股、港股的最新股價與歷史配息，並用近 12 個月配息算殖利率。使用者說「查股價」「現價多少」「抓 00882 的價格」「美股／日股／港股報價」「配息紀錄」「除息日」「最近一次配多少」「殖利率更新」「更新股價」，或要更新持股快照、股利試算需要最新價格與配息時使用。唯讀，只抓公開網頁，不寫入 Investment_Tracker_Core。
---

# price-dividend-fetcher：抓股價與配息

- **腳本**：`scripts/fetch.py`（只用 Python 標準函式庫與 `curl`），輸出 JSON。
- **來源與解析規則（SSOT）**：`references/sources.md`。股價取自 Google Finance，失敗時依序備援 Yahoo Finance、證交所收盤價（上市）、櫃買中心收盤價（上櫃）；台股配息取自 FinLab 並與證交所交叉驗證，個股沒有 FinLab 配息頁時改讀個股頁（金額精度 0.1 元，另附 `stock_dividend` 股票股利）；美、日、港股配息取自 Yahoo Finance。
- **唯讀**：只輸出到 stdout，不寫檔、不碰 Core。需要更新 Core 的 `Portfolio` 時，只能把建議的儲存格與新值以文字列給 Hachi。

## 用法

在 REPO 根目錄執行：

```bash
python3 .claude/skills/price-dividend-fetcher/scripts/fetch.py price 00882 NASDAQ:AAPL TYO:7203 HKG:0005
python3 .claude/skills/price-dividend-fetcher/scripts/fetch.py dividends 00882 [--since 2024-01-01] [--no-crosscheck]
python3 .claude/skills/price-dividend-fetcher/scripts/fetch.py both 00882
```

正式版分級（`--scan` 每列多出 long、mid、short、fib3、combo）：長期 5 級（強勢、偏多、中性、偏弱、弱勢）、中期 3 級（偏多、中性、偏空）、短期只標註（站上或跌破 20 日線，加短線偏熱或短線超跌）、費波那契 3 段（近端、中段、遠端）。提醒只在三週期組合變成「三週期共振偏多、三週期共振偏空、長多短回檔、長空短反彈」時觸發。短期各級回測後續報酬差異不明顯，因此不分級；中期 5 級不單調，因此合併成 3 級。狀態標籤「過熱」已改稱「短線偏熱」，舊狀態檔的標籤會自動對應。狀態標籤「未觸發條件」已改稱「無明確型態」（2026-10-30），判定規則不變，舊狀態檔的標籤同樣自動對應。

代號格式為 `交易所:代號`（與 Core 的 `TPE:00882` 一致），只寫代號視為台股。交易所：`TPE`、`NASDAQ`、`NYSE`、`NYSEARCA`、`NYSEAMERICAN`、`TYO`、`HKG`。

| 指令 | 回傳重點 |
| --- | --- |
| `price` | `price`、`change`、`change_pct`、`prev_close`、`currency`、`as_of`（UTC）、`price_type`（`last` 或 `close`）；來自 Google 的結果可能附 `dividend_summary`；有備援時附 `fallback_reason` |
| `dividends` | `events`（除息日、每單位金額；台股另有基準日、發放日）、`yearly_totals`、`ttm_total`；台股附 `crosscheck`（與證交所比對），海外附 `currency` |
| `both` | 以上兩者，加上 `yield_pct`（近 12 個月配息 ÷ 現價）與計算依據 |

`price` 可一次查多檔、混合市場，`--source google|yahoo|twse|tpex` 可指定單一來源（預設依序嘗試）；單檔失敗只影響該筆（`error` 欄位），其他照常回傳，回傳碼為 1。

## 使用規則

1. **回報時寫明來源與時間**：例如「00882 現價 15.12（Google Finance，2026-10-13 06:31 UTC，盤中可能變動）」；備援來源（Yahoo、證交所、櫃買中心）要照 `source` 欄位寫明；證交所與櫃買中心的價格是收盤價。
2. **失敗就說失敗**：回傳碼 1 代表連線失敗或頁面改版，如實告訴 Hachi，不用舊數字或猜測補上；改版處理見 `references/sources.md`。
3. **海外配息只有 Yahoo 一個來源**：沒有交叉驗證，重要數字請 Hachi 對照公司公告。Yahoo 會列入特別股息，近 12 個月合計與殖利率可能因此偏高，回報時要點出。幣別為原幣，不自動換算台幣。
4. **`crosscheck.consistent` 為 false 時**：列出差異給 Hachi，以證交所（官方）為準，不自行挑一邊。`crosscheck` 內有 `error` 只代表驗證沒做成，不代表配息有誤。
5. **配息是每單位金額**，不是實收。算實收要乘持股數並扣二代健保，實際扣除額以入帳為準。
6. **殖利率口徑**：近一年每股配息 ÷ 現價（見 CLAUDE.md）。和 Core 的 `Market_Yield_Pct` 或 FinLab 頁面數字有小差異時，說明是現價時點不同。
7. **事實與推估分開**：抓到的是事實；拿近 12 個月配息推年配息，要標明「假設配息持平」。
8. 查到的新配息與實績表 `models/00882/profile/actual_payouts.yml` 不同時，先告訴 Hachi，確認後再更新該檔，不直接覆蓋。

## 常見搭配

- 產生持股快照前，用 `price` 取得最新價算市值與殖利率。
- 除息月（1、7 月）用 `dividends --since` 確認新配息，再和 Core 的 `Transactions`（Reinvest）核對入帳。

## 測試

```bash
python3 -m pytest -q .claude/skills/price-dividend-fetcher/tests
```

測試使用內嵌的樣本，不需要網路。

## 個股波段指標（`scripts/swing.py`）

5 天到 4 週波段用的日線指標（均線、RSI、MACD、ATR、布林、量能、52 週位置）與狀態判定，另有超跌反彈規則回測。只用標準函式庫、唯讀 Yahoo；只描述條件，不構成買賣指示，波段部位與股利再投入部位分開看。

```bash
python3 .claude/skills/price-dividend-fetcher/scripts/swing.py TPE:2356 --backtest
python3 .claude/skills/price-dividend-fetcher/scripts/swing.py --batch 00882:15   # 成分股彙總回測
python3 .claude/skills/price-dividend-fetcher/scripts/swing.py --fib-backtest   # 費波那契回檔位置（近 30 日高低點）之後 5/10/20 日含息報酬，觀察清單全標的
python3 .claude/skills/price-dividend-fetcher/scripts/swing_levels.py   # 短、中、長期分級回測：各週期 5 級、費波那契 6 級、三週期組合的後續含息報酬（正式版只採用回測站得住的部分，見下）
python3 .claude/skills/price-dividend-fetcher/scripts/swing.py --scan 00882:15      # 觀察清單掃描（個股卡片＋成分股前 N 大），輸出 JSON
python3 .claude/skills/price-dividend-fetcher/scripts/swing.py --scan 00882:15 --prev prev.json --html out.html --sheet sheet.json   # --html 另存 Artifact 頁面；--prev 給上次 --scan 輸出，標出狀態變化；--sheet 輸出 Sheet 二維表（表頭加資料列，A 到 X 欄順序固定，排程整張寫入）
python3 .claude/skills/portfolio-patrol/scripts/patrol.py --json > patrol.json && python3 .claude/skills/price-dividend-fetcher/scripts/swing.py --scan 00882:15 --patrol patrol.json --daily-html out.html   # 每日投資組合巡檢頁：波段觀察加評分矩陣（趨勢、動能、量能、績效，`swing_scores.py`，與 APP 同算法），併入配置狀態與殖利率，可依地區與類型篩選

`--scan` 掃描後若有標的最後一根日線早於同市場最新資料日（尾端落後），或同市場超過半數標的有、該檔缺少的交易日（中間日缺口，交易日以同市場多數為準，不需假日表），會先等待 30、60 秒，只重抓這些標的，且只採用資料日較新或缺口較少的結果；證交所補缺失敗會在 stderr 印出「證交所補缺失敗（代號 月份）」。重抓後仍有問題時，stderr 會列出代號與缺的日期，頁面也會標示「資料落後至 YYYY-MM-DD」與「缺 MM-DD」。不用 Firecrawl 或 FinMind 補查：每檔一點的成本太高，且 FinMind 免費版沒有還原價。
# 頁面含「表格｜矩陣｜象限｜動態」四種檢視（動態可播放近 60 日趨勢×動能氣泡圖與近 20／60／120 日報酬賽跑折線，純 SVG，不需外部元件；按「選擇標的」可用快速組合（我的最愛、綜合分前 10、ETF、個股、台股、港股）或逐檔勾選要播放的標的，記在瀏覽器）；點標的的視窗另有 K 線、指標矩陣、近 60 日軌跡動畫（2D，可播放） 三個分頁；頁首「更新最新報價」鈕經 Firecrawl 連線器向證交所取台股即時價（Artifact 需宣告 mcp 能力，排程重發時省略 capabilities 即沿用）；標的左側星號可加「我的最愛」，「只看我的最愛」與地區、類型篩選疊加，存在 db 能力的 data/users/<id>/favs（Artifact 需宣告 db、user；無法同步時退回 localStorage）；表格檢視可按「選擇指標欄位」依群組（波段判定、評分、配置與估值）或逐欄勾選要顯示的欄，設定記在瀏覽器；表格與矩陣最多顯示 20 檔，其餘縱向捲動、表頭固定；象限預設座標貼合資料範圍、圓點一律小而一致、游標移到圓點才顯示股號，象限可滾輪縮放與拖曳平移；標的視窗 K 線可在游標處滾輪縮放、拖曳平移，價格與 RSI、MACD 範圍貼合可見區間
```
