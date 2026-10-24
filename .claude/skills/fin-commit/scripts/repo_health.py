#!/usr/bin/env python3
"""committer 的 --sync / --patrol 輔助模組：安全拉取與環境巡檢。僅用標準函式庫（需 Python 3.11+）。

--sync    fetch 後只做 fast-forward；有未提交變更、分叉、已併入 main 的分支一律不動，只回報
--patrol  巡檢系統工具、git 狀態、Python 版本與 pyproject 宣告的套件是否已安裝
"""
from __future__ import annotations

import importlib.metadata
import re
import subprocess
import sys
import tomllib
from pathlib import Path

OK, WARN, FAIL = "OK", "WARN", "FAIL"
ICON = {OK: "✅", WARN: "⚠️ ", FAIL: "❌"}
# (名稱, 指令, 必要, 最低版本)
TOOLS = [
    ("git", ["git", "--version"], True, "2.30"),
    ("python3", ["python3", "--version"], True, "3.12"),
    ("uv", ["uv", "--version"], False, None),
    ("gh", ["gh", "--version"], False, None),
]


def _run(cmd, cwd=None, timeout=60):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def _vtuple(s: str):
    return tuple(int(x) for x in re.findall(r"\d+", s)[:3])


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _req_name(spec: str) -> str:
    return _norm(re.split(r"[<>=!~;\[ ]", spec.strip(), maxsplit=1)[0])


def sync_repo(repo: Path = Path("."), default: str = "main", fetch_only: bool = False):
    """fetch 後只做 --ff-only 快轉；絕不 rebase、reset、force，也不覆蓋未提交變更。"""
    code, o = _run(["git", "fetch", "--prune", "origin"], repo, timeout=180)
    if code != 0:
        return [(FAIL, "fetch", o.splitlines()[-1][:160] if o else "失敗")]
    _, br = _run(["git", "branch", "--show-current"], repo)
    if not br:
        return [(WARN, "分支", "detached HEAD，不拉取")]
    _, st = _run(["git", "status", "--porcelain"], repo)
    rows = []
    code, up = _run(["git", "rev-parse", "--abbrev-ref", "@{u}"], repo)
    if code == 0:
        _, ab = _run(["git", "rev-list", "--left-right", "--count", "@{u}...HEAD"], repo)
        behind, ahead = (int(x) for x in ab.split())
        if behind == 0 and ahead == 0:
            rows.append((OK, "同步", f"{br} 已是最新（{up}）"))
        elif behind and ahead:
            rows.append((FAIL, "分叉", f"{br} 與 {up} 分叉（落後 {behind}、領先 {ahead}）：請人工處理，不自動合併"))
        elif ahead:
            rows.append((WARN, "未推送", f"{br} 領先 {up} {ahead} 個 commit"))
        elif st:
            rows.append((WARN, "略過", f"有未提交變更，不拉取（落後 {behind} 個 commit）"))
        elif fetch_only:
            rows.append((WARN, "落後", f"{br} 落後 {up} {behind} 個 commit（--fetch-only 未快轉）"))
        else:
            code, o = _run(["git", "merge", "--ff-only", "@{u}"], repo)
            rows.append((OK, "快轉", f"{br} 已快轉 {behind} 個 commit") if code == 0 else (FAIL, "快轉", o.splitlines()[-1][:160]))
    else:
        rows.append((WARN, "upstream", f"{br} 沒有 upstream（首次推送請用 git push -u）"))
    if br != default and _run(["git", "rev-parse", "--verify", "-q", f"origin/{default}"], repo)[0] == 0:
        if _run(["git", "merge-base", "--is-ancestor", "HEAD", f"origin/{default}"], repo)[0] == 0:
            rows.append((WARN, "分支已併入", f"{br} 已併入 {default}：請切回 {default} 並重新建分支，不要在舊分支上續做"))
        else:
            _, n = _run(["git", "rev-list", "--count", f"HEAD..origin/{default}"], repo)
            if n != "0":
                rows.append((WARN, "落後 main", f"落後 origin/{default} {n} 個 commit：開 PR 前先 merge origin/{default}（不用 rebase）"))
    return rows + check_handoff(repo, default=default)


_IDLE_VALUES = {"", "無", "無（已完成）", "none", "n/a", "-", "（l1 快速提交未指定）"}


def _note_handoff_rows(repo: Path):
    """掃描 architecture/*.md 中標記為『草稿』或『修訂中』的待試作筆記。"""
    arch_dir = repo / "architecture"
    if not arch_dir.is_dir():
        return []
    rows = []
    for md in sorted(arch_dir.glob("*.md")):
        try:
            txt = md.read_text(encoding="utf-8")
        except OSError:
            continue
        if not txt.startswith("---\n"):
            continue
        end = txt.find("\n---\n", 4)
        if end == -1:
            continue
        fm = txt[4:end]
        m_st = re.search(r"^status:\s*(.+)$", fm, re.MULTILINE)
        status = m_st.group(1).strip() if m_st else ""
        if status not in ("草稿", "修訂中"):
            continue
        body = txt[end + 5:]
        m_sum = re.search(r"^##\s+摘要\s*\n+([^\n#]+)", body, re.MULTILINE)
        summary = m_sum.group(1).strip() if m_sum else ""
        if len(summary) > 65:
            summary = summary[:65] + "…"
        rel = f"architecture/{md.name}"
        rows.append((WARN, "待辦筆記", f"{rel} [{status}]" + (f"：{summary}" if summary else "")))
    return rows


def _session_sync_handoff_rows(repo: Path, default: str = "main"):
    """檢查最新 commit 的 Session-Sync 下一步／阻塞，以及遠端尚未合併的 origin/claude/* 分支。"""
    rows = []
    code, msg = _run(["git", "log", "-1", "--format=%B"], repo)
    if code == 0 and "## Session-Sync" in msg:
        sec = msg.split("## Session-Sync", 1)[1]
        field = lambda k: (re.search(rf"-\s*\*\*{k}\*\*:\s*(.+)", sec) or [None, ""])[1].strip()
        agent = field("執行者") or "未知"
        nxt = field("下一步")
        blk = field("阻塞")
        has_nxt = nxt.lower() not in _IDLE_VALUES and "未指定" not in nxt
        has_blk = blk.lower() not in _IDLE_VALUES and "未指定" not in blk
        if has_nxt or has_blk:
            detail = f"[{agent}] {nxt}" if has_nxt else f"[{agent}]"
            if has_blk:
                detail += f"（阻塞：{blk}）"
            rows.append((WARN, "交接下一步", detail))
    _, cur_br = _run(["git", "branch", "--show-current"], repo)
    code, refs = _run(["git", "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin/claude/"], repo)
    c_main, main_ts = _run(["git", "log", "-1", "--format=%ct", f"origin/{default}"], repo)
    if code == 0 and refs and c_main == 0 and main_ts.isdigit():
        for ref in refs.splitlines():
            short_br = ref.removeprefix("origin/")
            if short_br == cur_br:
                continue
            c2, cnt = _run(["git", "rev-list", "--count", f"origin/{default}..{ref}"], repo)
            c3, br_ts = _run(["git", "log", "-1", "--format=%ct", ref], repo)
            if c2 == 0 and cnt.isdigit() and int(cnt) > 0 and c3 == 0 and br_ts.isdigit() and int(br_ts) >= int(main_ts):
                _, subj = _run(["git", "log", "-1", "--format=%s", ref], repo)
                rows.append((WARN, "未合併分支", f"{ref}（領先 {default} {cnt} 個 commit：{subj[:50]}）"))
    return rows


def check_handoff(repo: Path = Path("."), default: str = "main"):
    """跨 Agent（Claude 雲端 ⇄ Antigravity）雙向交接雷達：掃描草稿／修訂中筆記、最新 Session-Sync 下一步與未合併雲端分支。"""
    return _note_handoff_rows(repo) + _session_sync_handoff_rows(repo, default=default)


def patrol_tools():
    rows = []
    for name, cmd, required, minimum in TOOLS:
        code, o = _run(cmd)
        if code != 0:
            rows.append((FAIL if required else WARN, name, "未安裝"))
            continue
        m = re.search(r"\d+(\.\d+)+", o)
        v = m.group(0) if m else "?"
        if minimum and m and _vtuple(v) < _vtuple(minimum):
            rows.append((FAIL if required else WARN, name, f"{v} < 最低 {minimum}"))
        else:
            rows.append((OK, name, v))
    return rows


def check_installed(repo: Path = Path(".")):
    """比對 pyproject 直接依賴與目前直譯器已安裝的套件與版本（只警告，不安裝）。"""
    p = repo / "pyproject.toml"
    if not p.exists():
        return [(OK, "pyproject.toml", "不存在（此 REPO 不使用）")]
    proj = tomllib.loads(p.read_text(encoding="utf-8")).get("project", {})
    deps = proj.get("dependencies", [])
    rows = [(OK, "pyproject.toml", f"{len(deps)} 個直接依賴，requires-python {proj.get('requires-python', '?')}")]
    want_py = re.search(r"\d+(\.\d+)*", proj.get("requires-python", ""))
    if want_py and _vtuple(".".join(map(str, sys.version_info[:3]))) < _vtuple(want_py.group(0)):
        rows.append((WARN, "python", f"目前 {sys.version.split()[0]} < requires-python {proj['requires-python']}"))
    miss, bad = [], []
    for spec in deps:
        n = _req_name(spec)
        try:
            have = importlib.metadata.version(n)
        except importlib.metadata.PackageNotFoundError:
            miss.append(n)
            continue
        m = re.search(r"(==|>=)\s*([\w.]+)", spec)
        if m and (_vtuple(have) != _vtuple(m.group(2)) if m.group(1) == "==" else _vtuple(have) < _vtuple(m.group(2))):
            bad.append(f"{n} 需 {m.group(1)}{m.group(2)} 實裝 {have}")
    if miss:
        rows.append((FAIL, "已安裝套件", f"缺少 {len(miss)} 個：{', '.join(miss[:8])}（請用 uv sync 或 uv add 對齊）"))
    if bad:
        rows.append((WARN, "套件版本", f"{len(bad)} 個不符：{'; '.join(bad[:5])}"))
    if not miss and not bad:
        rows.append((OK, "已安裝套件", "皆已安裝且版本符合"))
    return rows


def patrol_repo(repo: Path = Path("."), installed_check=None):
    """installed_check：REPO 已有自己的環境比對（回傳問題清單）時傳入，避免重複實作。"""
    _, br = _run(["git", "branch", "--show-current"], repo)
    _, st = _run(["git", "status", "--porcelain"], repo)
    rows = [(OK if not st else WARN, "git", f"分支 {br or '(detached)'}，{'乾淨' if not st else str(len(st.splitlines())) + ' 個未提交變更'}")]
    code, ab = _run(["git", "rev-list", "--left-right", "--count", "@{u}...HEAD"], repo)
    if code == 0:
        behind, ahead = ab.split()
        rows.append((OK if behind == "0" else WARN, "同步", f"落後 {behind}、領先 {ahead}（先 fetch 才準；可用 --sync）"))
    if (repo / "package.json").exists():
        nm = (repo / "node_modules").exists()
        rows.append((OK if nm else WARN, "node_modules", "已安裝" if nm else "未安裝（bun/npm install）"))
    if installed_check is None:
        return patrol_tools() + rows + check_installed(repo) + check_handoff(repo)
    issues = installed_check()
    env = [(WARN, "環境比對", i) for i in issues] if issues else [(OK, "環境比對", "pyproject.toml 與安裝環境一致")]
    return patrol_tools() + rows + env + check_handoff(repo)


def protected_branch_issue(branch: str, protected=("main",)):
    return f"目前在受保護分支 {branch}：請先建立工作分支再提交（禁止直接 push main）" if branch in protected else None


def claude_without_rules_warning(files):
    """變更 .claude/ 卻沒有同步動到 rules 或索引時提醒（只警告）。"""
    touched = [f for f in files if f.startswith(".claude/") and not f.startswith(".claude/rules/")]
    ruled = any(f.startswith(".claude/rules/") or f in ("CLAUDE.md", ".agent/rules/AGENT.md") for f in files)
    return "變更了 .claude/ 但沒有動到 rules／索引：請確認已掃描 rules 是否需要更新" if touched and not ruled else None


def print_report(rows) -> int:
    for level, label, msg in rows:
        print(f"{ICON[level]} {label}：{msg}")
    return 1 if any(level == FAIL for level, _, _ in rows) else 0
