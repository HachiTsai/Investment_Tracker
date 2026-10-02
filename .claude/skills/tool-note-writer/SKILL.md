---
name: tool-note-writer
description: 撰寫、修改與搜尋財商工程 REPO 的筆記，所有筆記使用固定格式（frontmatter＋固定段落），讓 Claude 與 Obsidian 都能精準搜尋。支援財商架構筆記（type: arch，放在 architecture/）與標的研究筆記（type: research，放在 research/）。只要使用者想記錄或整理財商規則、目標、資產配置、現金流、股利再投入、風險控管、稅務、決策規則、資料系統設計，或某個標的（ETF、股票）的研究、配息紀錄、持有論點，或說「寫筆記」「記下來」「整理成架構」「這條規則改一下」「找一下我之前寫的…」「哪些規則該回顧了」，都應使用本 skill，即使使用者沒有說出「筆記」兩個字。
---

# tool-note-writer：財商筆記撰寫工具

筆記是長期累積的思考資產。格式固定，是為了讓幾個月或幾年後，Claude 和 Obsidian 都能用欄位精準找到筆記，也能回頭看出「當時怎麼想、依據是什麼、後來為什麼改」。

- **格式規格**：寫筆記前先讀對應類型的規格，裡面有完整範例。

  | 類型 | 用途 | 位置與檔名 | 規格 |
  | --- | --- | --- | --- |
  | `arch` | 財商架構：目標、配置、規則 | `architecture/<主題>.md` | `references/format-arch.md` |
  | `research` | 標的研究：論點、依據、配息、風險 | `research/<代號>_<主題>.md` | `references/format-research.md` |

- **受控詞彙**：`references/vocabulary.md`。`domain`、`tags`、arch 的 `status`、research 的 `status`（`research_status`）只能用表內的詞。
- **工具**：`scripts/notes.py`，提供 `new`、`check`、`find`、`vocab` 四個指令。
- **相依**：`check` 會呼叫 `markdown-linter` skill，需要安裝 Node.js。

以下指令都在 REPO 根目錄執行：`python3 .claude/skills/tool-note-writer/scripts/notes.py <指令>`。

## 寫新筆記

1. **先搜尋，避免重複**：用 `find --text <關鍵字>` 或 `find --domain <領域>` 查是否已有相關筆記。若已有，改走下一節「修改既有筆記」。規則散在兩篇筆記，日後就很難知道哪一篇才算數。
2. **選類型並決定 metadata**：規則、目標、配置用 `arch`；針對某個標的的研究用 `research`。
   - `title`：arch 用名詞片語描述「這是什麼規則」，例如 `股息再投入規則`；research 用 `<代號>_<主題>`，例如 `00882_股利追蹤`。不含日期、不含空白。
   - `domain`：arch 從詞彙表選一個；research 不使用。
   - `tickers`：research 必填，第一個代號要和檔名一致。
   - `tags`：從詞彙表選，可以多選。用 `vocab` 指令查看完整清單。
   - 找不到合適的詞時，先確認詞彙表裡沒有同義詞，再到 `references/vocabulary.md` 新增，並告訴使用者新增了哪個詞。不要硬塞一個意思不對的詞，也不要隨手造同義詞。
3. **建立骨架**：

   ```bash
   notes.py new arch <title> --domain <領域> --tags <詞,詞> [--tickers 00882] [--status 草稿]
   notes.py new research <代號>_<主題> --tickers <代號> --tags <詞,詞> [--status 觀察]
   ```

   - arch 的 `status` 預設為 `草稿`；使用者明確說規則已經在執行，才設為 `生效`。
   - research 的 `status` 預設為 `觀察`；實際持有就設為 `持有`。
4. **填寫內容**：把所有「（待填）」換成實際內容，各段落的寫法見下方「寫好內容」。需要時補上選填欄位 `review`、`related`、`aliases`、`sources`。
5. **檢查**：`notes.py check <路徑>`。它會檢查欄位格式，也會呼叫 `markdown-linter` skill 檢查 Markdown 語法，兩者都要通過。Markdown 錯誤可以先用 `mdlint.py --fix <路徑>` 自動修正。
6. **提交**：用 `fin-commit` skill 提交，arch 筆記的 type 為 `arch`，research 筆記的 type 為 `research`。

## 修改既有筆記

### arch：版本管理

- **規則有實質改變**：
  - `version` +1，`updated` 改成今天。
  - 在「變更紀錄」新增 `### v<新版>（YYYY-MM-DD）`，寫明變更內容與原因。
  - 被取代的舊條文搬到該版本的變更紀錄裡保留，不要直接刪除。之後要回顧決策品質，靠的就是這些舊條文。
- **只是修錯字或排版**：不升版。
- **規則不再使用**：`status` 改為 `廢止`，檔案保留，不要刪除。

### research：以日期追加更新

- 在「更新紀錄」最上方新增 `### YYYY-MM-DD`，`updated` 改成同一天。
- 看法改變時，寫明「原本怎麼想 → 現在怎麼想 → 為什麼」，舊判斷保留在更新紀錄裡。
- 出清或決定不投資：`status` 改為 `放棄`，檔案保留。

改完同樣執行 `check`，再用 `fin-commit` 提交。

## 寫好內容

- **摘要**：一到兩句話。`find` 的搜尋結果會顯示這段，要讓人不打開全文也看得懂。
- **規則**：用編號條列，寫成可以照著執行的句子。有數字就寫出數字，例如「單一標的 ≤ 60%」，不要只寫「不要太集中」。
- **理由**：分開寫「事實／數據」和「判斷／觀點」。事實要附來源與日期。持股數字以 Investment_Tracker_Core 或 `portfolio/snapshots/` 為準。Core 只能讀，嚴禁修改。
- **適用範圍與例外**：寫出規則什麼時候不適用，這能避免日後機械式地誤用規則。
- **論點**（research）：這是 Hachi 自己的判斷。資料不足時寫「（待 Hachi 補充）」，不要替使用者編造持有理由。
- **追蹤指標**（research）：寫出「看到什麼就要重新評估」，例如「下次配息低於 0.40」。
- 使用者沒有提供的數字或依據，不要自己編造。可以寫「（待確認）」並提醒使用者。

## 搜尋筆記

```bash
notes.py find --ticker 00882                 # 和某個標的相關
notes.py find --domain 風險 --status 生效      # 某領域目前生效的規則
notes.py find --tag 股利 --tag 複利            # 多個 tag 同時符合
notes.py find --due                          # 已到回顧日、該重新檢視的規則
notes.py find --text 殖利率                   # 全文關鍵字
notes.py check                               # 檢查全部筆記格式
```

回答使用者時，列出筆記的路徑、狀態和摘要；如果有需要，再讀全文。

## Obsidian 相容性

frontmatter 是 Obsidian Properties 原生格式，Dataview 可以直接查詢，例如：

```dataview
TABLE status, domain, version, updated FROM "architecture" WHERE status = "生效" SORT updated DESC
```

`related` 寫成 `"[[筆記名]]"`，會顯示為 Obsidian 的雙向連結；`aliases` 讓 Obsidian 搜尋時也能用別名找到筆記。

## 擴充新類型（例如 trend、journal）

1. 在 `scripts/notes.py` 的 `NOTE_TYPES` 註冊新類型：目錄、必填與選填欄位、狀態詞彙、段落。
2. 新增 `references/format-<type>.md`，內容包含規格與範例。
3. 在 `tests/` 補上測試，用 `python3 -m pytest -q .claude/skills/tool-note-writer/tests` 執行。
4. 檔名同樣不使用日期。
