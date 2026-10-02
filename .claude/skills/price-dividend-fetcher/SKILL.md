---
name: price-dividend-fetcher
description: 抓台股（ETF）的最新股價與歷史配息，並用近 12 個月配息算殖利率。使用者說「查股價」「現價多少」「抓 00882 的價格」「配息紀錄」「除息日」「最近一次配多少」「殖利率更新」「更新股價」，或要更新持股快照、股利試算需要最新價格與配息時使用。唯讀，只抓公開網頁，不寫入 Investment_Tracker_Core。
---

# price-dividend-fetcher：抓股價與配息

- **腳本**：`scripts/fetch.py`（只用 Python 標準函式庫與 `curl`），輸出 JSON。
- **來源與解析規則（SSOT）**：`references/sources.md`。股價取自 Google Finance，配息取自 FinLab。
- **唯讀**：只輸出到 stdout，不寫檔、不碰 Core。需要更新 Core 的 `Portfolio` 時，只能把建議的儲存格與新值以文字列給 Hachi。

## 用法

在 REPO 根目錄執行：

```bash
python3 .claude/skills/price-dividend-fetcher/scripts/fetch.py price 00882 [其他代號]
python3 .claude/skills/price-dividend-fetcher/scripts/fetch.py dividends 00882 [--since 2024-01-01]
python3 .claude/skills/price-dividend-fetcher/scripts/fetch.py both 00882
```

代號可寫 `00882` 或 `TPE:00882`。

| 指令 | 回傳重點 |
| --- | --- |
| `price` | `price`、`change`、`change_pct`、`prev_close`、`as_of`（UTC） |
| `dividends` | `events`（除息日、每單位金額、基準日、發放日）、`yearly_totals`、`ttm_total` |
| `both` | 以上兩者，加上 `yield_pct`（近 12 個月配息 ÷ 現價）與計算依據 |

## 使用規則

1. **回報時寫明來源與時間**：例如「00882 現價 14.76（Google Finance，2026-10-02 03:26 UTC，盤中可能變動）」。
2. **失敗就說失敗**：回傳碼 1 代表連線失敗或頁面改版，如實告訴 Hachi，不用舊數字或猜測補上；改版處理見 `references/sources.md`。
3. **配息是每單位金額**，不是實收。算實收要乘持股數並扣二代健保，依股利目標模型的規則。
4. **殖利率口徑**：近一年每股配息 ÷ 現價（見 CLAUDE.md）。和 Core 的 `Market_Yield_Pct` 或 FinLab 頁面數字有小差異時，說明是現價時點不同。
5. **事實與推估分開**：抓到的是事實；拿近 12 個月配息推年配息，要標明「假設配息持平」。
6. 查到的新配息與研究筆記 `00882_股利追蹤` 不同時，先告訴 Hachi，再用 tool-note-writer 在原筆記追加「更新（日期）」段落，不直接覆蓋。

## 常見搭配

- 產生持股快照前，用 `price` 取得最新價算市值與殖利率。
- 除息月（1、7 月）用 `dividends --since` 確認新配息，再和 Core 的 `Transactions`（Reinvest）核對入帳。

## 測試

```bash
python3 -m pytest -q .claude/skills/price-dividend-fetcher/tests
```

測試使用內嵌的樣本 HTML，不需要網路。
