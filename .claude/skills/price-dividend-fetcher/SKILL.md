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

## 共用回測引擎（`scripts/backtest.py`）

規則可插拔（進場、出場、停損各自是函式）、成本模型（各市場手續費、交易稅、滑價，幣安合約另計資金費率）、槓桿與逐倉清算、可做空、資金曲線與風險指標（勝率、清算次數、最大回撤、最長連虧、與買進持有比較）。`swing.py` 的超跌反彈回測已改由此引擎執行（結果與舊版逐筆相同）；費波那契與三週期分級是「位置之後 N 日報酬」的統計，不是交易模擬，維持原樣。

```bash
python3 .claude/skills/price-dividend-fetcher/scripts/backtest.py NASDAQ:TQQQ --strategy trend --side both --compare --margin-pct 1 --capital 15000
python3 .claude/skills/price-dividend-fetcher/scripts/backtest.py BINANCE:TQQQUSDT --strategy discipline --compare --capital 15000
python3 .claude/skills/price-dividend-fetcher/scripts/backtest.py TPE:0050 --strategy oversold --range 10y --trades
```

- 策略：`trend`（收盤站上 N 日線且均線 5 日上彎做多、反之做空，跌破或站回均線出場）、`discipline`（交易紀律預設：順勢、單筆保證金 1%、2×ATR 停損、虧損後冷卻 1 根，槓桿超過 5 倍會警告）、`bbmid`（布林中線 ±1% 進場、持有 N 根，對照組）、`oversold`（RSI≤30）。
- 代號：股票同上方格式；`BINANCE:<合約>` 讀幣安 USDⓈ-M 合約公開 K 線與資金費率（`www.binance.com/fapi`，不需帳號）。美股代幣化合約（如 `TQQQUSDT`）上市時間短，樣本少時要看 `period` 與 `bars`。
- 成本預設在 `COSTS`（保守假設，非券商實際費率），可用 `--fee-bps`、`--slip-bps`、`--sell-tax-bps` 覆寫；台股 ETF 證交稅用 `--sell-tax-bps 10`。
- 限制：日線看不到盤中路徑，同一根同時碰停損與清算一律算清算；策略報酬用未還原收盤價、不含配息；股票加槓桿是以合約口徑模擬。回測只代表過去，不是買賣指示。

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
python3 .claude/skills/price-dividend-fetcher/scripts/swing.py --scan 00882:15 --patrol patrol.json --daily-html out.html --stress --stress-track 00406A   # 加「市場修正追蹤」區塊（market_stress.py，單獨跑會輸出 JSON）：六個趨緩訊號（外資現貨買賣超、外資台指期淨空單、融資餘額、加權 10 日線、10 日波動、費半 5 日）、修正期第幾天對照歷史類比中位數，與追蹤持股的最近配息、β 與上漲／下跌捕獲率（寫成 `代號:成本` 才加相對成本與只靠配息回本期數；巡檢頁是公開連結，排程不給成本）；來源為期交所 OpenAPI、證交所、Yahoo，抓不到顯示 -
python3 .claude/skills/price-dividend-fetcher/scripts/swing.py --scan 00882:15 --patrol patrol.json --daily-html out.html --etf-detail https://claude.ai/artifact/RoDHVZRr588JCcgzMswsug   # 頁首與台股 ETF 視窗放台股 ETF 成分股明細頁連結（只列成分股有 5 檔以上台股個股的 ETF，規則同 etf_pool.discover）
python3 .claude/skills/price-dividend-fetcher/scripts/swing.py --scan 00882:15 --patrol patrol.json --daily-html out.html --alerts-from-sheet   # 讀波段觀察 Sheet「告警紀錄」分頁（公開連結 gviz CSV，唯讀，DRIVE_IDS 的 SWING_SHEET_ID），點亮最近一個偵測日的關鍵組合轉換；目前組合已變回或距今超過 4 天不點亮，讀不到不中止

`--daily-html`（每日巡檢頁）一律套用內建發布門檻（`check_daily_gate`，不需 `--gate`）：掃描結果為空失敗；核心持股 00882、00406A 零容忍（ERROR、NO_DATA、資料落後或缺口任一即失敗）；其餘列異常合計超過 2 檔失敗；任一市場最新資料日距今超過 7 天失敗。通過後頁面另經預檢（占位符、資料日、無成本數值）。未過時退出碼 1、不寫檔，rows 仍印在 stdout 供排查。`--gate` 只用於波段 Sheet（ERROR 與 NO_DATA 合計上限 10 檔；新掛牌日線不足 60 根的 NO_DATA 不計入）。

`--scan` 掃描後若有標的最後一根日線早於同市場最新資料日（尾端落後），或同市場超過半數標的有、該檔缺少的交易日（中間日缺口，交易日以同市場多數為準，不需假日表），會先等待 30、60 秒，只重抓這些標的，且只採用資料日較新或缺口較少的結果；證交所補缺失敗會在 stderr 印出「證交所補缺失敗（代號 月份）」。重抓後仍有問題時，stderr 會列出代號與缺的日期，頁面也會標示「資料落後至 YYYY-MM-DD」與「缺 MM-DD」。不用 Firecrawl 或 FinMind 補查：每檔一點的成本太高，且 FinMind 免費版沒有還原價。
# 頁面含「表格｜矩陣｜象限｜動態」四種檢視（動態可播放近 60 日趨勢×動能氣泡圖與近 20／60／120 日報酬賽跑折線，純 SVG，不需外部元件；按「選擇標的」可用快速組合（我的最愛、綜合分前 10、ETF、個股、台股、港股）或逐檔勾選要播放的標的，記在瀏覽器）；點標的的視窗另有 K 線、指標矩陣、近 60 日軌跡動畫（2D，可播放） 三個分頁；頁首「更新最新報價」鈕經 Firecrawl 連線器向證交所取台股即時價（Artifact 需宣告 mcp 能力，排程重發時省略 capabilities 即沿用）；標的左側星號可加「我的最愛」，「只看我的最愛」與地區、類型篩選疊加，存在 db 能力的 data/users/<id>/favs（Artifact 需宣告 db、user；無法同步時退回 localStorage）；表格檢視可按「選擇指標欄位」依群組（波段判定、評分、配置與估值）或逐欄勾選要顯示的欄，設定記在瀏覽器；表格與矩陣最多顯示 20 檔，其餘縱向捲動、表頭固定；象限預設座標貼合資料範圍、圓點一律小而一致、游標移到圓點才顯示股號，象限可滾輪縮放與拖曳平移；標的視窗 K 線可在游標處滾輪縮放、拖曳平移，價格與 RSI、MACD 範圍貼合可見區間
```
