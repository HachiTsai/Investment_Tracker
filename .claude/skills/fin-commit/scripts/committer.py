"""Fin-Commit Workflow 主入口。

職責：自動化 Git 暫存、變更驗證與提交指令生成，確保 Commit Message 符合規格書 SSOT。
本模組為 facade 入口，底層模組拆分為：
- registry.py: 類別、Type 名冊與路徑推斷
- validator.py: 格式檢查、算術核對與 Co-Author 補強
- dep_guard.py: 敏感檔案檢查與 Python AST 依賴比對
- git_ops.py: 底層 Git 命令、暫存與 Markdown Lint 檢查
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import repo_health
from dep_guard import (
    REPO_ROOT,
    SENSITIVE_PATTERNS,
    find_dependency_issues,
    find_env_issues,
    find_rule_sync_issues,
    find_sensitive,
    normalize_pkg_name,
    parse_pyproject_deps,
    parse_rule_toml_deps,
    path_matches,
)
from git_ops import (
    MDLINT_DIR,
    SKILL_DIR,
    get_git_diff,
    get_git_stats,
    get_staged_file_list,
    git,
    install_hook,
    lint_staged_markdown,
    run_git_add,
)
from registry import (
    AGENT_REGISTRY,
    AMOUNT_TOLERANCE,
    AUTO_QUICK_FILE_SOFT_LIMIT,
    AUTO_QUICK_GUARDED_FILES,
    AUTO_QUICK_GUARDED_PREFIXES,
    CATEGORIES_REGISTRY,
    CATEGORY_ARCH,
    CATEGORY_IT,
    CATEGORY_PATH_RULES,
    CATEGORY_PORTFOLIO,
    CATEGORY_RESEARCH,
    CATEGORY_TRADE,
    CATEGORY_TREND,
    COAUTHOR_LINE,
    COAUTHOR_RE,
    DATE_RE,
    DEFAULT_CATEGORY,
    DIFF_PREVIEW_CHARS,
    DIVIDEND_SECTION,
    ENV_FALSY_VALUES,
    FIELD_RE,
    HEADER_RE,
    IMPACT_SECTION,
    L1_UNSPECIFIED,
    MAX_SUMMARY,
    MESSAGE_FILE,
    NUMBER_RE,
    RECOMMENDED_SECTIONS,
    REQUIRED_SECTION_FIELDS,
    SECTION_RE,
    SKIP_RE,
    TICKER_RE,
    TRADE_SECTION,
    TRADE_TYPES,
    TYPES,
    UNKNOWN_AGENT,
    UNKNOWN_AGENT_LABEL,
    check_auto_quick_guard,
    detect_agent,
    get_agent_label,
    infer_category,
    infer_commit_type,
    infer_scope,
    normalize_agent,
)
from validator import (
    ensure_coauthor_line,
    first_number,
    parse_sections,
    report,
    validate_message,
)

SPEC_PATH = SKILL_DIR / "references" / "spec-git-commit-protocol.md"


def finalize_commit(
    message_file: Path,
    no_push: bool = False,
    dry_run: bool = False,
    skip_mdlint: bool = False,
) -> int:
    """Markdown lint、補上 Co-Author、檢查格式，通過後 commit（並 push）。"""
    if not skip_mdlint and lint_staged_markdown(get_staged_file_list()) != 0:
        print("❌ [Finalize] 暫存區的 Markdown 未通過 lint，未提交。可先執行 mdlint.py --fix。", file=sys.stderr)
        return 1
    if not message_file.exists():
        print(f"❌ [Finalize] 找不到訊息檔：{message_file}", file=sys.stderr)
        return 1
    msg = message_file.read_text(encoding="utf-8")
    if not msg.strip():
        print("❌ [Finalize] Commit message 是空的。", file=sys.stderr)
        return 1

    original = msg
    signed = ensure_coauthor_line(msg)
    if signed != msg:
        print("   ✍️ [Co-Author] 訊息尾端補上 Co-Authored-By")
        msg = signed

    errors, warnings = validate_message(msg)
    if not report(errors, warnings):
        print("❌ [Finalize] 訊息不符規格書，未提交。請修正後重跑。", file=sys.stderr)
        return 1

    if dry_run:
        print("   🧪 [Dry Run] 將以下列訊息提交：")
        print("-" * 60)
        print(msg)
        print("-" * 60)
        if not no_push:
            print("   🧪 [Dry Run] 提交後將 push。")
        return 0

    if msg != original:
        message_file.write_text(msg, encoding="utf-8")

    print(f"   📦 [Git] git commit -F {message_file}")
    if subprocess.run(["git", "commit", "-F", str(message_file)]).returncode != 0:
        print("❌ [Git] commit 失敗。", file=sys.stderr)
        return 1
    if no_push:
        print("   ✅ [Commit] 完成（--no-push，未推送）。")
        return 0
    print("   🚀 [Git] git push")
    if subprocess.run(["git", "push"]).returncode != 0:
        print("❌ [Git] push 失敗。", file=sys.stderr)
        return 1
    print("   ✅ [Commit & Push] 完成。")
    return 0


def build_quick_commit_message(
    staged_files: List[str],
    category: str,
    agent: Optional[str] = None,
    status: Optional[str] = None,
    next_step: Optional[str] = None,
    blocker: Optional[str] = None,
) -> str:
    """L1 快速提交訊息：純由路徑生成，Session-Sync 未帶入的欄位填佔位語。"""
    if not staged_files:
        raise ValueError("沒有已暫存的檔案，無法產生快速提交訊息。")
    ctype = infer_commit_type(staged_files)
    scope = infer_scope(staged_files)
    total = len(staged_files)
    summary = f"更新 {staged_files[0]}" if total == 1 else f"更新 {total} 個檔案"
    if len(summary) > MAX_SUMMARY:
        summary = f"更新 {Path(staged_files[0]).name}"
    bullets = "\n".join(f"- `{p}`" for p in staged_files[:AUTO_QUICK_FILE_SOFT_LIMIT])
    if total > AUTO_QUICK_FILE_SOFT_LIMIT:
        bullets += f"\n- …另有 {total - AUTO_QUICK_FILE_SOFT_LIMIT} 個檔案"
    return f"""{ctype}({scope}): {summary}

## 核心變更

{bullets}

## 變更理由

- L1 快速提交（純機械生成）

## 驗證

- 無需驗證—L1 快速提交

## Session-Sync

- **執行者**: {get_agent_label(agent)}
- **類別**: {category}
- **狀態**: {(status or '').strip() or L1_UNSPECIFIED}
- **下一步**: {(next_step or '').strip() or L1_UNSPECIFIED}
- **阻塞**: {(blocker or '').strip() or L1_UNSPECIFIED}
"""


def build_agent_directive(category: str, agent_label: str, stats: str, diff: str, spec: str) -> str:
    """草擬指令：交給 Agent 依 diff 與規格書直接寫出訊息並提交。"""
    script = Path(__file__).resolve()
    try:
        script = script.relative_to(Path.cwd())
    except ValueError:
        pass
    return f"""
==============================================================================
🔴 AGENT 強制執行指令 (MANDATORY DIRECTIVE) 🔴
==============================================================================
你現在被 `fin-commit` 技能接管。請依下方 [Git 變更] 與 [規格書]，草擬 Commit Message 並直接完成提交。
類別、type、訊息內容一律不詢問使用者；只有缺少的**數字**（價格、股數、金額）必須詢問，不得推測。

## SOP

1. **[理解]** 閱讀 stats 與 diff，判斷這次是哪一種投資行為或維運變更。
2. **[拆分]** 若混了多種行為（例：股利入帳＋再投入），用 `--stage-list` 拆成多個 commit。
3. **[合規]** 依規格書 §3 選 type／scope；交易類必填「交易明細」，div 必填「股利明細」。
4. **[類別]** 已自動判定為 **{category}**；需要覆蓋時重跑並帶 `--category`。
5. **[核對]** 數量 × 價格 = 金額；數字以 Investment_Tracker_Core 為準（唯讀，嚴禁修改）。
6. **[草擬]** 依規格書 §4 唯一模板寫出最終訊息（不提供多個選項），選用區塊依內容決定。
7. **[提交]** 寫入 `{MESSAGE_FILE.as_posix()}`，執行：
   `python3 {script.as_posix()} --no-stage --message-file {MESSAGE_FILE.as_posix()}`
   （會檢查 Markdown 與訊息格式、補 Co-Author；不通過即不提交）。

## Session-Sync 預填值

- **執行者**: {agent_label}
- **類別**: {category}

---
📂 [Git 變更統計 (Stats)]
{stats}
---
📄 [Git 變更內容 (Diff, max {DIFF_PREVIEW_CHARS} chars)]
{diff[:DIFF_PREVIEW_CHARS] if diff else "None"}
---
📜 [SSOT 規格書 ({SPEC_PATH.name})]
{spec}
==============================================================================
"""


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fin-Commit Workflow（財商工程 commit 流程）")
    p.add_argument("--category", choices=CATEGORIES_REGISTRY, help="覆蓋自動判定的類別")
    p.add_argument("--message-file", type=Path, help="已寫好的訊息檔，檢查後直接提交")
    p.add_argument("--exclude", nargs="+", help="git add . 後排除的路徑")
    p.add_argument("--stage-list", nargs="+", help="只暫存指定路徑（與 --exclude 互斥）")
    p.add_argument("--no-stage", action="store_true", help="不自動 git add，使用現有暫存區")
    p.add_argument("--no-push", action="store_true", help="commit 後不 push")
    p.add_argument("--dry-run", action="store_true", help="只顯示訊息，不提交")
    p.add_argument("--auto-quick", action="store_true", help="L1 機械式快速提交（交易紀錄禁用）")
    p.add_argument("--allow-guarded", action="store_true", help="解除 --auto-quick 防呆閘門")
    p.add_argument("--agent", type=lambda s: s.strip().lower(), choices=sorted(AGENT_REGISTRY), help="指定執行者")
    p.add_argument("--status", help="L1 的 Session-Sync 狀態")
    p.add_argument("--next", dest="next_step", help="L1 的 Session-Sync 下一步")
    p.add_argument("--blocker", help="L1 的 Session-Sync 阻塞")
    p.add_argument("--skip-mdlint", action="store_true", help="略過暫存區 Markdown lint（僅限無 Node.js 時暫用，CI 仍會檢查）")
    p.add_argument("--allow-sensitive", action="store_true", help="略過敏感檔案檢查")
    p.add_argument("--allow-missing-deps", action="store_true", help="略過未記錄套件與依賴檔同步檢查")
    p.add_argument("--check", type=Path, metavar="FILE", help="只檢查訊息檔格式（commit-msg hook 用）")
    p.add_argument("--check-env", action="store_true", help="比對 pyproject.toml 與實際安裝套件（唯讀，只警告）")
    p.add_argument("--install-hook", action="store_true", help="安裝 commit-msg hook")
    p.add_argument("--sync", action="store_true", help="安全拉取：fetch 後只 fast-forward，有未提交變更或分叉時不動並回報")
    p.add_argument("--fetch-only", action="store_true", help="搭配 --sync：只 fetch 並回報落後，不快轉")
    p.add_argument("--patrol", action="store_true", help="巡檢系統工具、git 狀態與 pyproject／安裝環境（沿用 --check-env 的比對）")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if args.check:
        errors, warnings = validate_message(args.check.read_text(encoding="utf-8"))
        return 0 if report(errors, warnings) else 1
    if args.install_hook:
        return install_hook()
    if args.check_env:
        issues = find_env_issues()
        if issues:
            print("⚠️ [Env] pyproject.toml 與安裝環境不一致：", *issues, sep="\n   - ")
            print("   ➜ 請用 `uv sync` 或 `uv add <pkg>` 對齊（此檢查只警告，不中止）。")
        else:
            print("✅ [Env] pyproject.toml 與安裝環境一致。")
        return 0
    if args.sync:
        return repo_health.print_report(repo_health.sync_repo(fetch_only=args.fetch_only))
    if args.patrol:
        return repo_health.print_report(repo_health.patrol_repo(installed_check=find_env_issues))
    if args.auto_quick and args.message_file:
        print("   ❌ --auto-quick 與 --message-file 不可併用。", file=sys.stderr)
        return 1
    if args.stage_list and args.exclude:
        print("   ❌ --stage-list 與 --exclude 不可併用。", file=sys.stderr)
        return 1

    print("🚀 [Fin-Commit] Initializing...")
    agent_id = detect_agent(args.agent)
    if agent_id == UNKNOWN_AGENT:
        print(f"   ⚠️  [Agent] 無法判定執行者，將標示「{UNKNOWN_AGENT_LABEL}」；可加 --agent 或設定 AGENT_ID。")
    else:
        print(f"   🤖 [Agent] 執行者：{get_agent_label(agent_id)}")

    if args.no_stage:
        print("   📦 [Git] 略過自動暫存（--no-stage）。")
    elif not run_git_add(paths=args.stage_list, exclude=args.exclude):
        return 1

    staged_files = get_staged_file_list()
    if not staged_files:
        print("   ⚠️ [Git] 沒有已暫存的變更，請先 git add。")
        return 0
    print(f"   📋 [Git] Staged files ({len(staged_files)}):")
    for f in staged_files[:15]:
        print(f"      - {f}")
    if len(staged_files) > 15:
        print(f"      ... and {len(staged_files) - 15} more")

    if not args.allow_sensitive:
        hits = find_sensitive(staged_files)
        if hits:
            print("   ❌ [Security] 暫存區含疑似敏感檔案，已中止：", *hits, sep="\n      - ", file=sys.stderr)
            print("   ➜ 確認無誤請加 --allow-sensitive；否則 `git reset HEAD -- <path>` 移出暫存。", file=sys.stderr)
            return 1

    branch_issue = repo_health.protected_branch_issue(git("branch", "--show-current").stdout.decode().strip())
    if branch_issue and (args.message_file or args.auto_quick) and not (args.dry_run or args.no_push):
        print(f"   ❌ [Branch] {branch_issue}", file=sys.stderr)
        return 1
    rules_warning = repo_health.claude_without_rules_warning(staged_files)
    if rules_warning:
        print(f"   ⚠️ [Rules] {rules_warning}")

    dep_issues = [] if args.allow_missing_deps else find_dependency_issues(staged_files)
    if dep_issues and (args.message_file or args.auto_quick):
        print("   ❌ [Deps] 發現未記錄或未同步的套件依賴／規則索引，已中止：", *dep_issues, sep="\n      - ", file=sys.stderr)
        print("   ➜ 請先同步更新 pyproject.toml 與 .claude/rules/python-environment.md 並暫存，或加 --allow-missing-deps 略過。", file=sys.stderr)
        return 1

    category = args.category or infer_category(staged_files)
    how = "--category 指定" if args.category else "依 staged 路徑自動判定"
    print(f"   🏷️  [Category] 類別：{category}（{how}）")

    if args.message_file:
        return finalize_commit(
            args.message_file,
            no_push=args.no_push,
            dry_run=args.dry_run,
            skip_mdlint=args.skip_mdlint,
        )

    if args.auto_quick:
        reasons = check_auto_quick_guard(staged_files, category)
        if reasons and not args.allow_guarded:
            print("   🛑 [Auto-Quick] 已阻擋，請改走完整模板：", file=sys.stderr)
            for r in reasons:
                print(f"      - {r}", file=sys.stderr)
            print("   ➜ 確認屬純格式修正時，可加 --allow-guarded 解除。", file=sys.stderr)
            return 1
        if len(staged_files) > AUTO_QUICK_FILE_SOFT_LIMIT:
            print(f"   ⚠️ [Auto-Quick] 暫存 {len(staged_files)} 檔，超過建議上限 {AUTO_QUICK_FILE_SOFT_LIMIT}。")
        message = build_quick_commit_message(
            staged_files,
            category,
            agent=agent_id,
            status=args.status,
            next_step=args.next_step,
            blocker=args.blocker,
        )
        MESSAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        MESSAGE_FILE.write_text(message, encoding="utf-8")
        return finalize_commit(
            MESSAGE_FILE,
            no_push=args.no_push,
            dry_run=args.dry_run,
            skip_mdlint=args.skip_mdlint,
        )

    if not SPEC_PATH.exists():
        print(f"   ❌ [Contract] 找不到規格書：{SPEC_PATH}", file=sys.stderr)
        return 1

    if dep_issues:
        print("\n   ⚠️  [Deps] 發現未記錄或未同步的套件依賴／規則索引：", *dep_issues, sep="\n      - ")
        print("   ➜ 提交時將會攔截，請先同步更新 pyproject.toml 與 .claude/rules/python-environment.md 並重新暫存（或加 --allow-missing-deps）。\n")

    print(build_agent_directive(
        category=category,
        agent_label=get_agent_label(agent_id),
        stats=get_git_stats(),
        diff=get_git_diff(),
        spec=SPEC_PATH.read_text(encoding="utf-8"),
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
