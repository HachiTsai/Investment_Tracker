# 排程登記表

本表是 repo 內自動排程的單一清單（盤點 F8）。只列自動觸發的流程；手動執行與跨 repo 的排程（Stock_AIStudio `refresh-etf-data`）不在此列。新增、停用或改時間時，同步更新本表。

- **GitHub Actions 排程**：時間以 `.github/workflows/*.yml` 的 `cron` 為準（UTC），台北時間 = UTC + 8 小時。
- **雲端排程**：prompt 一律是單行呼叫，會讀取並執行對應的 `.claude/workflows/*.md`，所以改流程只要改文件，下次執行就生效。觸發時間與開關只存在雲端排程設定中，由建立者在雲端修改，修改後要同步更新本表。
- **健康檢查**：`ci.yml` 的 `schedule-health` 每日台北 20:00 檢查 GitHub Actions 排程（S1、S2）。雲端排程不在 GitHub 上，只能由 Artifact 更新時間或排程串核對（C1 至 C3）。

## 1. 總表

括號內為盤點編號（迴圈工程盤點）。

| ID | 流程 | 平台 | 觸發（台北） | 規格（SSOT） | 產出 | 健康檢查 |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| S1 | 波段觀察 Sheet 同步（L1） | GitHub Actions `swing-patrol.yml`，cron `0 9 * * 1-5` | 平日 17:00 | `swing-patrol-sheets.md` | 波段觀察 Sheet A:X，心跳 Z1:AA2 | 每日，容許 96 小時 |
| S2 | 全市場 ETF 池（台股）Sheet 同步（L2） | GitHub Actions `market-etf.yml`，cron `10 9 * * 5` | 週五 17:10 | `market-etf-pool.md` | 全市場_ETF成分股資料庫 Sheet | 每日，容許 192 小時 |
| C1 | 每日投資組合巡檢（L6） | Claude 雲端排程 | 平日 08:30 | `daily-portfolio-patrol.md` | Artifact `WLXXvrX7BzLemm9TxqZ6di`，ArtifactData `trap_state` | 無，靠排程串回報 |
| C2 | 00882 成分股股利表（L7） | Claude 雲端排程 | 週五 17:00 | `hk-00882-dividend.md` | Artifact `DSbfrxfywurJVo3TVwSzia`，Sheet `00882_成分股股利資料庫` | 無，靠排程串回報 |
| C3 | 台股 ETF 成分股池（L8） | Claude 雲端排程 | 每月第 1 個營業日 09:00（建議） | `tw-etf-pool.md` | Artifact `RoDHVZRr588JCcgzMswsug`，Sheet `台股ETF成分股資料庫` | 無，排程是否已建立待確認 |
| C4 | Our_Investment 快照版 | Claude 雲端排程 | 每日 21:00（建議） | `ledger-snapshot.md` | Artifact `SBn43iC1bBG2zf2bexgmxZ` | 無，靠排程串回報 |
| CI | 排程健康檢查（F6） | GitHub Actions `ci.yml`，cron `0 12 * * *` | 每日 20:00 | 本表與 `.claude/skills/fin-commit/scripts/schedule_health.py` | CI 紀錄（成功或紅燈） | 本身即檢查 |

## 2. 雲端 prompt 原文

雲端排程設定中的 prompt 必須與下列逐字一致。S1、S2 的雲端 prompt 是備用，GitHub Actions 失敗時可手動補跑。

- C1：`git pull --ff-only origin main，讀取並執行 .claude/workflows/daily-portfolio-patrol.md，完成後依規格回報。`
- C2：`git pull origin main，讀取並執行 .claude/workflows/hk-00882-dividend.md，完成後依規格回報。`
- C3：`git pull origin main，讀取並執行 .claude/workflows/tw-etf-pool.md，完成後依規格回報。`
- C4：`git pull --ff-only origin main，讀取並執行 .claude/workflows/ledger-snapshot.md，完成後依規格回報。`
- S1（備用）：`git pull origin main，讀取並執行 .claude/workflows/swing-patrol-sheets.md，完成後依規格回報。`
- S2（備用）：`git pull origin main，讀取並執行 .claude/workflows/market-etf-pool.md，完成後依規格回報。`

## 3. 待驗證（2026-10-28）

- S2 還沒有任何排程紀錄，首次排程為 2026-10-30（週五）。工作流建立後 192 小時內沒有排程紀錄，健康檢查不判定失敗。
- S1 實測觸發晚於 cron（2026-10-26 UTC 15:58、2026-10-27 UTC 15:13），原因未查。
- C1 至 C3 的執行紀錄不在 GitHub，目前無法從 repo 驗證；C3 的排程是否已建立，待確認。

## 4. 異動紀錄

- 2026-10-30：新增 C4（Our_Investment 快照版）。
- 2026-10-28：建立本表（盤點 F8）。雲端 prompt 皆為單行呼叫，依 Hachi 指示，改流程直接改對應的 `.claude/workflows/*.md`。
