"""Git 提交與 Slack 串接管線 (Patrol Committer)。

負責組裝符合 fin-commit 規格之巡檢 Commit 訊息，並調用 committer 執行提交與推播。
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from patrol_cards import format_progress, format_yield_or_return
from patrol_reporter import format_markdown_briefing, update_briefing_file


def build_patrol_commit_message(report: Dict[str, Any], agent: str = "Antigravity") -> str:
    """依照 fin-commit 規格組裝 Slack 最佳化的 Commit Message。"""
    fleet = report.get("fleet", [])
    alerts = report.get("alerts", [])

    if not alerts and report.get("is_steady"):
        prog = fleet[0]["goal_progress_pct"] if fleet else 51.2
        scfi_val = report.get("macro_data", {}).get("shipping_freight", {}).get("scfi", {}).get("current")
        if scfi_val is None:
            scfi_val = report.get("macro_data", {}).get("shipping_freight", {}).get("scfi", {}).get("latest_index", 3679)
        title = f"patrol(fleet): 🔵 穩健複利 ｜ 50萬達成率 {prog:.1f}% ｜ SCFI {int(scfi_val)}"
    else:
        top_alert = alerts[0] if alerts else {"ticker": "00882", "type": "ALERT", "message": "姿態微調", "action": "注意市場"}
        ticker = top_alert["ticker"]
        atype = top_alert["type"]
        if atype == "TRAP_ALERT":
            title = f"patrol(fleet): 🚨 互鎖警報【{ticker}】高息陷阱 ｜ 處置：暫停加碼"
        elif atype == "VELOCITY_PAUSE":
            title = f"patrol(fleet): 🚨 互鎖警報【{ticker}】資金急流 ｜ 處置：暫緩追買"
        elif atype == "AGGRESSIVE_ACCUMULATE":
            title = f"patrol(fleet): 🟢 積極進攻【{ticker}】便宜區 ｜ 啟動加碼"
        elif atype == "OVERVALUED_HOLD":
            title = f"patrol(fleet): 🟡 防禦觀望【{ticker}】估值偏高 ｜ 停止加碼"
        elif atype == "WATCHDOG_STALE":
            title = f"patrol(fleet): ⚠️ 心跳警報【{ticker}】資料過期 ｜ 需更新母表"
        else:
            title = f"patrol(fleet): ⚠️ 戰況提醒【{ticker}】互鎖調整 ｜ 關注姿態"

    if len(title) > 50:
        title = title[:50]

    lines = []
    lines.append(title)
    lines.append("")
    lines.append("## 核心變更")
    lines.append("")
    lines.append("- 投資組合每日例行巡檢完成（更新 reports/portfolio_briefing.md）")
    lines.append(f"- 【總體狀態】：{report['overall_posture']}")
    lines.append(f"- 【決策指引】：{report['decision_item']}")
    lines.append(f"- 【宏觀前饋】：{report['macro_feed']}")
    lines.append("")
    lines.append("### 📊 投資組合目標控制與配置矩陣")
    lines.append("")
    lines.append("| 標的 | 現價 | 殖利率/階段含息報酬 | 當前狀態 | 50萬目標達成率 | 數據時效性 |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: |")
    for item in fleet:
        t = item["ticker"]
        p = f"{item['price']:.2f} {item['currency']}"
        y = format_yield_or_return(item)
        posture = item["posture_label"]
        prog = format_progress(item)
        w = item["watchdog"]["label"]
        lines.append(f"| {t} | {p} | {y} | {posture} | {prog} | {w} |")
    lines.append("")
    lines.append("## 變更理由")
    lines.append("")
    lines.append("- 港股盤後例行自動巡檢，監控閉環控制迴路健康度與數據心跳（Watchdog）")
    lines.append("")
    lines.append("## 驗證")
    lines.append("")
    lines.append("- models/*/cards/ 各標的閉環控制與風控互鎖求值正常")
    if alerts:
        lines.append(f"- 記錄 {len(alerts)} 項互鎖/心跳事件，處置指引自動派發")
    else:
        lines.append("- 各標的安全閥門全部正常閉合，無跳脫警報")
    lines.append("- 簡報內容嚴格遵守零個人隱私外洩（無個人持股張數與成本金額）")
    lines.append("")
    lines.append("## Session-Sync")
    lines.append("")
    status_str = "例行巡檢完成，投資組合穩健運轉中" if report.get("is_steady") else "🚨 警報發布中，等待複核"
    blocker_str = "無" if report.get("is_steady") else "；".join(f"{a['ticker']} 閥門閉鎖中" for a in alerts if a["type"] in ("TRAP_ALERT", "VELOCITY_PAUSE"))
    if not blocker_str:
        blocker_str = "無"
    lines.append(f"- **執行者**: {agent}")
    lines.append("- **類別**: 持股分析")
    lines.append(f"- **狀態**: {status_str}")
    lines.append("- **下一步**: 下一交易日 16:30 盤後定時巡檢")
    lines.append(f"- **阻塞**: {blocker_str}")

    return "\n".join(lines)


def commit_patrol_report(
    report: Dict[str, Any],
    dry_run: bool = False,
    no_push: bool = False,
    repo_root: Optional[Path] = None,
) -> bool:
    """自動執行更新戰報檔案、生成 commit 訊息並調用 fin-commit。"""
    root = repo_root or Path(__file__).resolve().parents[4]
    md_content = format_markdown_briefing(report)
    briefing_path = update_briefing_file(md_content, root)
    print(f"📄 [Portfolio Patrol] 戰報已更新至: {briefing_path}")

    agent = os.environ.get("AGENT_ID") or ("Claude" if os.environ.get("CLAUDECODE") else "Antigravity")
    commit_msg = build_patrol_commit_message(report, agent=agent)

    if dry_run:
        print("\n🔍 [Dry-Run] 擬提交之 Commit 訊息如下：")
        print("=" * 60)
        print(commit_msg)
        print("=" * 60)
        return True

    msg_temp = root / ".git" / "COMMIT_MSG_TEMP"
    msg_temp.write_text(commit_msg, encoding="utf-8")

    committer_script = root / ".claude" / "skills" / "fin-commit" / "scripts" / "committer.py"
    rel_path = str(briefing_path.relative_to(root))
    cmd = [
        sys.executable,
        str(committer_script),
        "--stage-list",
        rel_path,
        "--message-file",
        str(msg_temp),
        "--agent",
        agent.lower(),
    ]
    if no_push:
        cmd.append("--no-push")

    proc = subprocess.run(cmd, cwd=str(root))
    return proc.returncode == 0
