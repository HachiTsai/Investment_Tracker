---
name: artifact-registry
description: 追蹤每個 Artifact 的來源、腳本與排程，偵測斷鏈並產出告警。使用者說「盤點 Artifact」「Artifact 來源」「斷鏈檢查」「排程有沒有更新」「登記簿」，或每日巡檢排程要檢查 Artifact、排程、repo 腳本與 Drive 公開 Sheet 是否一致時使用。
---

# artifact-registry：Artifact 來源登記與斷鏈告警

- **登記簿（SSOT）**：`references/registry.json`。每個 Artifact 標記 `scheduled`（有排程與腳本）或 `manual`（人工產出）。
- **檢查腳本**：`scripts/registry_check.py`（Python 標準函式庫，唯讀）。
- **範圍**：只放 Investment_Tracker；Stock_AIStudio 是乾淨的 APP，不登記其 Artifact 與排程，只登記它匿名讀取的 Drive 公開 Sheet。
- **不碰 `portfolio-patrol`**：兩個技能互不 import、互不執行。

## 用法

排程 session 先 `git pull`，現場蒐集三份清單寫成 `live.json`，再執行：

```bash
python3 .claude/skills/artifact-registry/scripts/registry_check.py --live live.json
```

`live.json` 格式：

```json
{"artifacts": [{"url": "...", "updated_at": "ISO8601"}],
 "triggers": [{"name": "...", "enabled": true, "last_run_ok": true}],
 "drive": [{"id": "...", "public": true}]}
```

- Artifact 清單用 Artifact 工具 `list scope:mine`（以帳號清單為準）。
- 排程清單用 `list_triggers`；Drive 分享狀態用 `get_file_permissions`，匿名可讀才算 `public`。

## 會偵測的斷鏈

| code | 意義 |
| --- | --- |
| `artifact_missing` | 登記簿有，帳號清單找不到 |
| `stale` | 排程型 Artifact 超過 `max_age_hours` 沒更新 |
| `trigger_missing` / `trigger_disabled` / `trigger_failed` | 排程不存在、停用、最近一次失敗 |
| `script_missing` | 登記的腳本或底稿在 repo 找不到 |
| `unregistered_artifact` / `unregistered_trigger` | 帳號有但登記簿沒有 |
| `drive_not_public` | APP 依賴的 Sheet 不再公開 |

有任何告警結束碼為 1，輸出 JSON；排程只在有告警時通知，沒有告警就靜默結束。

## 維護規則

1. 新增、刪除 Artifact 或排程時，同一個 PR 更新 `registry.json`。
2. `max_age_hours` 要比排程週期寬鬆（日報 30 小時、週報 192 小時），避免假警報。
3. 內容新鮮度（資料源改版造成腳本成功但內容為空）目前不檢查，列為後續擴充。
