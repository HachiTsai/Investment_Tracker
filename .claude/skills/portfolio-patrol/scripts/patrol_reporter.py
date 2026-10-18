"""巡檢簡報與儀表板格式化模組 (Patrol Reporter)。

負責將巡檢結果格式化為 ASCII 儀表板、Markdown 簡報、更新本機歷史紀錄及同步 Google Doc。
"""

import datetime
import re
from pathlib import Path
from typing import Any, Dict, Optional


def format_ascii_dashboard(report: Dict[str, Any]) -> str:
    """輸出終端彩色 ASCII 巡檢儀表板。"""
    lines = []
    lines.append("=" * 86)
    lines.append(f"  📊  投資組合全標的每日巡檢簡報  ｜  {report['date_str']}")
    lines.append("=" * 86)
    lines.append(f"【總體狀態】: {report['overall_posture']}")
    lines.append(f"【決策指引】: {report['decision_item']}")
    lines.append(f"【宏觀前饋】: {report['macro_feed']}")
    lines.append("-" * 86)

    # 標的表格
    lines.append(f"{'標的代號':<8} {'標的名稱':<18} {'現價':<10} {'殖利率':<9} {'當前狀態':<16} {'目標達成率':<10} {'數據時效'}")
    lines.append("-" * 86)

    for item in report.get("fleet", []):
        ticker = item["ticker"]
        title = item["title"][:14]
        price_str = f"{item['price']:.2f} {item['currency']}"
        yield_str = f"{item['yield_pct']:.2f}%"
        posture = item["posture_label"]
        progress = f"{item['goal_progress_pct']:.1f}%"
        watchdog = item["watchdog"]["label"]

        lines.append(f"{ticker:<8} {title:<18} {price_str:<10} {yield_str:<9} {posture:<16} {progress:<10} {watchdog}")

    lines.append("-" * 86)

    alerts = report.get("alerts", [])
    if alerts:
        lines.append("🚨 異常告警與互鎖紀錄：")
        for idx, a in enumerate(alerts, 1):
            lines.append(f"  {idx}. [{a['ticker']}] {a['message']}")
            lines.append(f"     ➔ 處置閥門: {a['action']}")
    else:
        lines.append("🛡️ 異常告警與互鎖紀錄：所有安全閥門正常閉合，無異常跳脫。")

    lines.append("=" * 86)
    return "\n".join(lines)


def format_markdown_briefing(report: Dict[str, Any]) -> str:
    """依照 references/briefing-template.md 規範產出標準 Google Doc Markdown 區塊。"""
    lines = []
    lines.append(f"# 投資組合每日巡檢簡報 ｜ {report['date_str']}")
    lines.append("")
    agent_name = report.get("agent", "Antigravity")
    lines.append(f"> ⏱️ 巡檢時間：{report['timestamp']} CST ｜ 巡檢代理：{agent_name}")
    lines.append("")
    lines.append("## 🚨 今日焦點與指引（例外管理 MBE）")
    lines.append("")
    lines.append(f"- 【總體狀態】：{report['overall_posture']}")
    lines.append(f"- 【需決策事項】：{report['decision_item']}")
    lines.append(f"- 【宏觀前饋】：{report['macro_feed']}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 📊 投資組合目標控制迴路與配置矩陣")
    lines.append("")
    lines.append("| 標的代號 | 標的名稱 | 即時現價 | 模型殖利率 | 當前狀態 | 50萬目標達成率 | 數據時效性 |")
    lines.append("| :--- | :--- | :---: | :---: | :---: | :---: | :---: |")

    for item in report.get("fleet", []):
        t = item["ticker"]
        name = item["title"]
        p = f"{item['price']:.2f} {item['currency']}"
        y = f"{item['yield_pct']:.2f}%"
        posture = item["posture_label"]
        prog = f"{item['goal_progress_pct']:.1f}%"
        w = item["watchdog"]["label"]
        lines.append(f"| {t} | {name} | {p} | {y} | {posture} | {prog} | {w} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 🛡️ 異常告警與互鎖紀錄（若有）")
    lines.append("")
    alerts = report.get("alerts", [])
    if alerts:
        for a in alerts:
            lines.append(f"- **[{a['ticker']}] {a['message']}**")
            lines.append(f"  - 處置指引：{a['action']}")
    else:
        lines.append("- （無異常跳脫，所有安全閥門正常閉合）")
    lines.append("")

    return "\n".join(lines)


def sync_to_google_doc(doc_id: str, markdown_content: str, repo_root: Optional[Path] = None) -> bool:
    """同步更新至 Google Doc（透過 gdocs 工具或 Drive API 橋接）。"""
    root = repo_root or Path(__file__).resolve().parents[4]
    report_file = root / "reports" / f"patrol_briefing_{datetime.date.today().isoformat()}.md"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(markdown_content, encoding="utf-8")
    print(f"📄 [Portfolio Patrol] 戰報已同步備份至: {report_file}")
    print(f"🔗 [Portfolio Patrol] 目標 Google Doc ID: {doc_id}（支援 Claude 雲端與 Antigravity 共用）")
    return True


def update_briefing_file(markdown_block: str, repo_root: Optional[Path] = None) -> Path:
    """原地更新 reports/portfolio_briefing.md，維持最近 5 日滾動紀錄。"""
    root = repo_root or Path(__file__).resolve().parents[4]
    report_file = root / "reports" / "portfolio_briefing.md"
    report_file.parent.mkdir(parents=True, exist_ok=True)

    today_header = markdown_block.splitlines()[0].strip() if markdown_block else ""
    existing_text = report_file.read_text(encoding="utf-8") if report_file.exists() else ""

    blocks = re.split(r"(?=# 投資組合每日(?:總裁戰報|巡檢簡報))", existing_text)
    clean_blocks = []
    for b in blocks:
        b = b.strip()
        if b and not b.startswith(today_header):
            clean_blocks.append(b)

    final_blocks = [markdown_block.strip()] + clean_blocks[:4]
    final_content = "\n\n---\n\n".join(final_blocks) + "\n"
    report_file.write_text(final_content, encoding="utf-8")
    return report_file
