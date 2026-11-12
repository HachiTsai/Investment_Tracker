# 排程登記表

本表是 repo 內自動排程的單一清單（盤點 F8）。只列自動觸發的流程；手動執行與跨 repo 的排程（Stock_AIStudio `refresh-etf-data`）不在此列。新增、停用或改時間時，同步更新本表。

- **GitHub Actions 排程**：時間以 `.github/workflows/*.yml` 的 `cron` 為準（UTC），台北時間 = UTC + 8 小時。
- **雲端排程**：prompt 一律是單行呼叫，會讀取並執行對應的 `.claude/workflows/*.md`，所以改流程只要改文件，下次執行就生效。觸發時間與開關只存在雲端排程設定中，由建立者在雲端修改，修改後要同步更新本表。
- **健康檢查**：`ci.yml` 的 `schedule-health` 每日台北 20:17 檢查 GitHub Actions 排程（S1、S2）。雲端排程不在 GitHub 上，只能由 Artifact 更新時間或排程串核對（C1 至 C3）。

## 1. 總表

括號內為盤點編號（迴圈工程盤點）。

| ID | 流程 | 平台 | 觸發（台北） | 規格（SSOT） | 產出 | 健康檢查 |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| S1 | 波段觀察 Sheet 同步（L1） | GitHub Actions `swing-patrol.yml`，cron `23 9 * * 1-5` | 平日 17:23 | `swing-patrol-sheets.md` | 波段觀察 Sheet A:X（口袋名單加全市場 ETF 前 100 檔），心跳 Z1:AA2 | 每日，容許 96 小時 |
| S2 | 全市場 ETF 池（台股）Sheet 同步（L2） | GitHub Actions `market-etf.yml`，cron `37 9 * * 5` | 週五 17:37 | `market-etf-pool.md` | 全市場_ETF成分股資料庫 Sheet | 每日，容許 192 小時 |
| C1 | 每日投資組合巡檢（L6） | Claude 雲端排程 | 週二至週六 08:50 | `daily-portfolio-patrol.md` | Artifact `WLXXvrX7BzLemm9TxqZ6di`，ArtifactData `trap_state` | 無，靠排程串回報 |
| C2 | 00882 成分股股利表（L7） | Claude 雲端排程 | 週五 16:30 | `hk-00882-dividend.md` | Artifact `DSbfrxfywurJVo3TVwSzia`，Sheet `00882_成分股股利資料庫` | 無，靠排程串回報 |
| C3 | 台股 ETF 成分股池（L8） | Claude 雲端排程 | 週六 09:40 | `tw-etf-pool.md` | Artifact `RoDHVZRr588JCcgzMswsug`，Sheet `台股ETF成分股資料庫` | 無，靠排程串回報 |
| C4 | Our_Investment 快照版 | Claude 雲端排程 | 平日 09:30 | `ledger-snapshot.md` | Artifact `SBn43iC1bBG2zf2bexgmxZ` | 無，靠排程串回報 |
| C5 | 工作流對應地圖與工廠 | Claude 雲端排程 | 每日 23:10 | `workflow-map.md` | Artifact `ExaiqRk4EfWJoHe8CeLgY1`（地圖）、`CZS9eYwfwDVbdZZBbKREiy`（工廠） | 無，靠排程串回報；雲端排程已建立（2026-11-10），改每日 23:10 後 Hachi 需同步修改雲端排程 |
| CI | 排程健康檢查（F6） | GitHub Actions `ci.yml`，cron `17 12 * * *` | 每日 20:17 | 本表與 `.claude/skills/fin-commit/scripts/schedule_health.py` | CI 紀錄（成功或紅燈） | 本身即檢查 |

## 2. 雲端 prompt 原文

雲端排程設定中的 prompt 必須與下列逐字一致。S2 的雲端 prompt 是備用（S1 的 Claude 排程已於 2026-11-06 由 Hachi 刪除），GitHub Actions 失敗時可手動補跑。

- C1：`git pull --ff-only origin main，讀取並執行 .claude/workflows/daily-portfolio-patrol.md，完成後依規格回報。`
- C2：`git pull origin main，讀取並執行 .claude/workflows/hk-00882-dividend.md，完成後依規格回報。`
- C3：`git pull origin main，讀取並執行 .claude/workflows/tw-etf-pool.md，完成後依規格回報。`
- C4：`git pull --ff-only origin main，讀取並執行 .claude/workflows/ledger-snapshot.md，完成後依規格回報。`
- C5：`git pull origin main，讀取並執行 .claude/workflows/workflow-map.md，完成後依規格回報。`
- S2（備用）：`git pull origin main，讀取並執行 .claude/workflows/market-etf-pool.md，完成後依規格回報。`

## 3. 待驗證（2026-11-06）

- GitHub 排程實際觸發明顯晚於 cron：S1 2026-10-30 至 11-05 的 5 次排程建立於台北 23:43 至隔日 03:19；S2 2026-10-30 建立於台北 23:49（cron 為 17:10）。原因在 GitHub 排程端，未查明；2026-11-06 起 cron 改到非整點（S1 `:23`、S2 `:37`、CI `:17`），觀察延遲是否縮短。判斷 Sheet 是否已更新時看 run 的建立時間，不要假設設定時間已完成。
- S2 已於 2026-10-30 首次排程成功（原「尚無排程紀錄」已解除）。
- C1 至 C4 的執行紀錄不在 GitHub，無法從 repo 驗證；2026-11-01 用雲端排程清單核對過觸發時間與開關（見異動紀錄）。「成功」只代表排程跑完，不代表產出內容已核對。
- 一致性檢查：`fin-commit/tests/test_workflow_consistency.py` 在每次 PR 的 CI 比對本表與 `.github/workflows/*.yml` 的 cron、台北時間、規格檔是否存在、規格檔的排程時間與 prompt，以及各規格檔引用的腳本路徑是否存在；不一致即 CI 失敗。

## 4. 異動紀錄

- 2026-11-10：C5 改為每日 23:10，並同時重產與發布工作流工廠頁（`workflow_map.py build --factory`），讓新增或改時間的工作流自動進工廠。Hachi 要求（討論串 2026-11-10「那我們的C5 能不能改成每天晚上23:10 更新」）。
- 2026-11-12：C4 流程補三項：發布前先讀線上快照（否則每次排程的第一次發布都被拒）、資料改存 `get_values` 回應原文並用 `--raw-dir` 建置、以 `--prev` 對照上一版擋下既有列的錯漏字；另寫明發布被拒的處理順序（不原樣重送、不用 `force`）。排程時間與 prompt 不變。Hachi 同意（討論串 2026-11-12「同意，讓這個排程之後都可以順利發佈」）。
- 2026-11-10：新增 C5（工作流對應地圖），規格 `workflow-map.md`，產生器 `fin-commit/scripts/workflow_map.py`；排程時間週五 23:10 由 Hachi 指定，雲端排程 Hachi 已於同日建立（名稱 C5_工作流工廠每週更新）。Hachi 要求（討論串 2026-11-10「幫我寫一個workflow」）。
- 2026-11-10：C3 由每月 23 日 09:30 改為週六 09:40（雲端排程 `CRON_TZ=Asia/Taipei 40 9 * * 6`），名單改為與 C1 每日巡檢相同的 core 卡片（`etf_pool.py --tier core`）；C1 巡檢頁加明細頁連結（`swing.py --etf-detail`），兩頁維持分開。Hachi 同意（討論串「確認每日巡檢有跑市場修正追蹤」2026-11-10 選「分開+連結，改週更」）。
- 2026-11-06：C1 由每日改為週二至週六 08:50（雲端排程 `CRON_TZ=Asia/Taipei 50 8 * * 2-6`，Hachi 已在雲端設定修改），週日、週一的資料日與週六相同。S1、S2、CI 的 cron 改到非整點（17:23、17:37、20:17），新增 workflow 一致性測試；修正每日巡檢回報範本、成分股股利調查注意事項、全市場 ETF 列數敘述等過時內容。Hachi 同意（討論串「檢查 PR 217 與 218 修正」2026-11-06「同意，另外讓這些workflow時常被檢視與跟上每次的變化」）。
- 2026-11-06：S1 掃描範圍加入全市場 ETF（前 100 檔台股 ETF，與雷達矩陣同一份清單），工作逾時由 15 分鐘放寬為 30 分鐘；C1 巡檢不再寫波段觀察 Sheet（先前同日加入的步驟 5 撤回）。Hachi 同意（討論串 2026-11-06「1 同意」）。

- 2026-11-01：依雲端排程實際設定校正 C1 至 C4 觸發時間（C1 每日 08:50、C2 週五 16:30、C3 每月 23 日 09:30、C4 平日 09:30）；C3 確認已建立。Hachi 同意（討論串 2026-11-01「同意，開PR做」）。
- 2026-10-30：新增 C4（Our_Investment 快照版）。
- 2026-10-28：建立本表（盤點 F8）。雲端 prompt 皆為單行呼叫，依 Hachi 指示，改流程直接改對應的 `.claude/workflows/*.md`。
