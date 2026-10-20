#!/usr/bin/env python3
"""REPO管家 committer：跨 repo 的巡檢、提交前檢查與提交。僅用標準函式庫（需 Python 3.11+）。

子命令：
  sync   [--repo NAME] [--fetch-only]  安全拉取：fetch 後只做 fast-forward；有未提交變更、分叉、已併入 main 的分支一律不動，只回報
  patrol [--repo NAME] [--json]   巡檢實際環境（系統工具、各 repo 的 git 狀態、Python 版本、pyproject 與已安裝套件）
  check  REPO                     對該 repo 暫存區做提交前檢查（敏感檔、受保護分支、import 與 pyproject、規則檔同步）
  commit REPO --message-file F    check 通過後 git commit -F，預設 push（--no-push 可略過）
規則見 rules/*.json。
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULES = HERE / "rules"
OK, WARN, FAIL = "OK", "WARN", "FAIL"


def load(name: str) -> dict:
    return json.loads((RULES / name).read_text(encoding="utf-8"))


def run(cmd, cwd=None, timeout=60):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def vtuple(s: str):
    return tuple(int(x) for x in re.findall(r"\d+", s)[:3])


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def req_name(spec: str) -> str:
    return norm(re.split(r"[<>=!~;\[ ]", spec.strip(), maxsplit=1)[0])


def repo_path(cfg: dict, name: str) -> Path:
    return Path(cfg["workdir"]) / name


def venv_python(repo: Path, venv: str | None) -> str | None:
    if not venv:
        return sys.executable
    base = Path(venv).expanduser() if venv.startswith("~") else repo / venv
    py = base / "bin" / "python"
    return str(py) if py.exists() else None


# ---------- pyproject / 規則檔 ----------
def pyproject_info(repo: Path):
    p = repo / "pyproject.toml"
    if not p.exists():
        return None
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    return data.get("project", {})


def toml_block_deps(rule_file: Path):
    """取規則檔內 ```toml 區塊的 dependencies 與 requires-python。"""
    m = re.search(r"```toml\n(.*?)```", rule_file.read_text(encoding="utf-8"), re.S)
    if not m:
        return None
    try:
        return tomllib.loads(m.group(1)).get("project", {})
    except tomllib.TOMLDecodeError:
        return None


def check_pyproject(name: str, rc: dict, repo: Path, installed: dict | None):
    out = []
    proj = pyproject_info(repo)
    if proj is None:
        out.append((OK if not rc["pyproject"] else FAIL, "pyproject.toml", "不存在" + ("（此 repo 不使用）" if not rc["pyproject"] else "")))
        return out
    deps = proj.get("dependencies", [])
    out.append((OK, "pyproject.toml", f"{len(deps)} 個直接依賴，requires-python {proj.get('requires-python', '?')}"))
    # 規則檔 toml 區塊與 pyproject 同步
    if rc.get("rule_file"):
        rf = repo / rc["rule_file"]
        if not rf.exists():
            out.append((WARN, "規則檔同步", f"找不到 {rc['rule_file']}"))
        else:
            blk = toml_block_deps(rf)
            if blk is None:
                out.append((WARN, "規則檔同步", "規則檔內沒有可解析的 toml 區塊"))
            else:
                a, b = set(deps), set(blk.get("dependencies", []))
                if a == b and blk.get("requires-python") == proj.get("requires-python"):
                    out.append((OK, "規則檔同步", "pyproject 與規則檔 toml 區塊一致"))
                else:
                    diff = sorted(a ^ b)[:6]
                    out.append((FAIL, "規則檔同步", f"不一致：{diff}"))
    # 已安裝套件對照
    if installed is None:
        out.append((WARN, "已安裝套件", "找不到 venv，無法比對（見 setup.sh 的 py_env）"))
    else:
        miss, bad = [], []
        for spec in deps:
            n = req_name(spec)
            if n not in installed:
                miss.append(n)
                continue
            m = re.search(r"==\s*([\w.]+)", spec) or re.search(r">=\s*([\w.]+)", spec)
            if m:
                want = vtuple(m.group(1))
                have = vtuple(installed[n])
                if ("==" in spec and have != want) or (">=" in spec and "==" not in spec and have < want):
                    bad.append(f"{n} 需 {m.group(0)} 實裝 {installed[n]}")
        if miss:
            out.append((FAIL, "已安裝套件", f"缺少 {len(miss)} 個：{', '.join(miss[:8])}"))
        if bad:
            out.append((WARN, "套件版本", f"{len(bad)} 個不符：{'; '.join(bad[:5])}"))
        if not miss and not bad:
            out.append((OK, "已安裝套件", "皆已安裝且版本符合"))
    return out


def installed_pkgs(py: str):
    code = "import importlib.metadata as m,json;print(json.dumps({d.metadata['Name'].lower().replace('_','-').replace('.','-'):d.version for d in m.distributions()}))"
    rc, o = run([py, "-I", "-c", code])
    try:
        return json.loads(o.splitlines()[-1]) if rc == 0 else None
    except (json.JSONDecodeError, IndexError):
        return None


# ---------- patrol ----------
def patrol_tools():
    res = []
    for t in load("tools.json")["tools"]:
        rc, o = run(t["cmd"])
        if rc != 0:
            res.append((FAIL if t["required"] else WARN, t["name"], "未安裝"))
            continue
        ver = re.search(r"\d+(\.\d+)+", o)
        v = ver.group(0) if ver else "?"
        if t.get("min") and ver and vtuple(v) < vtuple(t["min"]):
            res.append((FAIL if t["required"] else WARN, t["name"], f"{v} < 最低 {t['min']}"))
        else:
            res.append((OK, t["name"], v))
    return res


def patrol_repo(name: str, rc: dict, cfg: dict):
    repo = repo_path(cfg, name)
    if not (repo / ".git").exists():
        return [(FAIL, "clone", f"{repo} 不存在（執行 setup.sh）")]
    out = []
    _, br = run(["git", "branch", "--show-current"], repo)
    _, st = run(["git", "status", "--porcelain"], repo)
    out.append((OK if not st else WARN, "git", f"分支 {br or '(detached)'}，{'乾淨' if not st else str(len(st.splitlines())) + ' 個未提交變更'}"))
    code, ab = run(["git", "rev-list", "--left-right", "--count", "@{u}...HEAD"], repo)
    if code == 0:
        behind, ahead = ab.split()
        out.append((OK if behind == "0" else WARN, "同步", f"落後 {behind}、領先 {ahead}"))
    cm = repo / rc["committer"]
    out.append((OK if cm.exists() else WARN, "committer", rc["committer"] + ("" if cm.exists() else " 不存在")))
    py = venv_python(repo, rc.get("venv"))
    installed = None
    if py:
        _, pv = run([py, "-c", "import sys;print('.'.join(map(str,sys.version_info[:3])))"])
        want = rc["python"]
        out.append((OK if pv.startswith(want) else WARN, "python", f"{pv}（預期 {want}）"))
        installed = installed_pkgs(py)
    else:
        out.append((WARN, "python", f"找不到 venv：{rc.get('venv')}"))
    out += check_pyproject(name, rc, repo, installed)
    if rc.get("native_env_check") and cm.exists():
        code, o = run([py or sys.executable, str(cm), "--check-env"], repo)
        tail = " / ".join(o.splitlines()[-3:])[:200] or "無輸出"
        out.append((OK if code == 0 and "WARN" not in o.upper() and "不一致" not in o else WARN, "repo 內建 --check-env", tail))
    if (repo / "package.json").exists():
        nm = (repo / "node_modules").exists()
        out.append((OK if nm else WARN, "node_modules", "已安裝" if nm else "未安裝（bun/npm install）"))
    return out


def cmd_patrol(a):
    cfg = load("repos.json")
    report = {"tools": patrol_tools(), "repos": {}}
    for n, rc in cfg["repos"].items():
        if a.repo and n != a.repo:
            continue
        report["repos"][n] = patrol_repo(n, rc, cfg)
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("== 系統工具")
        for s, k, d in report["tools"]:
            print(f"  [{s:4}] {k}: {d}")
        for n, rows in report["repos"].items():
            print(f"== {n}")
            for s, k, d in rows:
                print(f"  [{s:4}] {k}: {d}")
    fails = sum(1 for rows in [report["tools"], *report["repos"].values()] for r in rows if r[0] == FAIL)
    warns = sum(1 for rows in [report["tools"], *report["repos"].values()] for r in rows if r[0] == WARN)
    print(f"\n總計 FAIL {fails}、WARN {warns}")
    return 1 if fails else 0



# ---------- sync（安全 git pull）----------
def git_out(repo: Path, *args, timeout=60):
    return run(["git", *args], repo, timeout)


def sync_path(repo: Path, default: str = "main", fetch_only: bool = False):
    """fetch 後只做 --ff-only 快轉；絕不 rebase、reset、force，也不覆蓋未提交變更。"""
    if not (repo / ".git").exists():
        return [(FAIL, "repo", f"{repo} 不存在（先 clone）")]
    code, o = git_out(repo, "fetch", "--prune", "origin", timeout=180)
    if code != 0:
        return [(FAIL, "fetch", o.splitlines()[-1][:160] if o else "失敗")]
    rows = []
    _, br = git_out(repo, "branch", "--show-current")
    if not br:
        return [(WARN, "分支", "detached HEAD，不拉取")]
    _, st = git_out(repo, "status", "--porcelain")
    dirty = bool(st)
    code, up = git_out(repo, "rev-parse", "--abbrev-ref", "@{u}")
    if code == 0:
        _, ab = git_out(repo, "rev-list", "--left-right", "--count", "@{u}...HEAD")
        behind, ahead = (int(x) for x in ab.split())
        if behind == 0 and ahead == 0:
            rows.append((OK, "同步", f"{br} 已是最新（{up}）"))
        elif behind and ahead:
            rows.append((FAIL, "分叉", f"{br} 與 {up} 分叉（落後 {behind}、領先 {ahead}）：請人工處理，不自動合併"))
        elif ahead:
            rows.append((WARN, "未推送", f"{br} 領先 {up} {ahead} 個 commit"))
        elif dirty:
            rows.append((WARN, "略過", f"有未提交變更，不拉取（落後 {behind} 個 commit）"))
        elif fetch_only:
            rows.append((WARN, "落後", f"{br} 落後 {up} {behind} 個 commit（--fetch-only 未快轉）"))
        else:
            code, o = git_out(repo, "merge", "--ff-only", "@{u}")
            rows.append((OK, "快轉", f"{br} 已快轉 {behind} 個 commit") if code == 0 else (FAIL, "快轉", o.splitlines()[-1][:160]))
    else:
        rows.append((WARN, "upstream", f"{br} 沒有 upstream（首次推送請用 git push -u）"))
    if br != default and git_out(repo, "rev-parse", "--verify", "-q", f"origin/{default}")[0] == 0:
        if git_out(repo, "merge-base", "--is-ancestor", "HEAD", f"origin/{default}")[0] == 0:
            rows.append((WARN, "分支已併入", f"{br} 已併入 {default}：請切回 {default} 並重新建分支，不要在舊分支上續做"))
        else:
            _, n = git_out(repo, "rev-list", "--count", f"HEAD..origin/{default}")
            if n != "0":
                rows.append((WARN, "落後 main", f"落後 origin/{default} {n} 個 commit：開 PR 前先 merge origin/{default}（不用 rebase）"))
    return rows


def cmd_sync(a):
    cfg = load("repos.json")
    bad = False
    for n, rc in cfg["repos"].items():
        if a.repo and n != a.repo:
            continue
        print(f"== {n}")
        rows = sync_path(repo_path(cfg, n), rc.get("default_branch", "main"), a.fetch_only)
        bad |= show(rows)
    return 1 if bad else 0


# ---------- check / commit ----------
def staged(repo: Path):
    _, o = run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"], repo)
    return [f for f in o.splitlines() if f]


def local_modules(repo: Path):
    _, o = run(["git", "ls-files", "*.py"], repo)
    mods = set()
    for f in o.splitlines():
        parts = Path(f).parts
        mods.add(Path(f).stem)
        mods.update(parts[:-1])
    return mods


def missing_imports(repo: Path, files, declared: set[str], alias: dict):
    local = local_modules(repo)
    bad = {}
    for f in files:
        if not f.endswith(".py"):
            continue
        try:
            tree = ast.parse((repo / f).read_text(encoding="utf-8"))
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            mods = [x.name for x in node.names] if isinstance(node, ast.Import) else \
                   [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else []
            for m in mods:
                top = m.split(".")[0]
                if top in sys.stdlib_module_names or top in local or alias.get(top) == "":
                    continue
                if norm(alias.get(top, top)) not in declared:
                    bad.setdefault(top, set()).add(f)
    return bad


def check_repo(name: str, cfg: dict):
    rc, rules = cfg["repos"][name], load("commit.json")
    repo = repo_path(cfg, name)
    res = []
    _, br = run(["git", "branch", "--show-current"], repo)
    res.append((FAIL, "分支", f"禁止在 {br} 直接提交，請改用功能分支並開 PR") if br in rules["protected_branches"] else (OK, "分支", br))
    files = staged(repo)
    if not files:
        res.append((FAIL, "暫存區", "沒有已暫存的檔案（先 git add）"))
        return res
    res.append((OK, "暫存區", f"{len(files)} 個檔案"))
    hits = [f for f in files if any(fnmatch.fnmatch(f, p) or fnmatch.fnmatch(Path(f).name, p) for p in rules["sensitive_patterns"])]
    res.append((FAIL, "敏感檔", f"包含：{hits}") if hits else (OK, "敏感檔", "無"))
    scan = rules.get("rules_scan")
    if scan:
        trig = [f for f in files if any(f.startswith(t) for t in scan["trigger_paths"])]
        touched = any(f.startswith(r) or f == r for f in files for r in scan["rule_paths"])
        if trig and not touched:
            res.append((WARN, "rules 掃描", f"改了 .claude/（{trig[0]} 等 {len(trig)} 個）但未動規則檔：請掃描 rules/CLAUDE.md/AGENT.md，條列並詢問使用者，或明寫「已掃描，無需更新」"))
        else:
            res.append((OK, "rules 掃描", "無 .claude/ 變更需掃描" if not trig else "規則檔已一併變更"))
    proj = pyproject_info(repo)
    if rc["pyproject"] and proj is not None:
        declared = {req_name(d) for d in proj.get("dependencies", [])}
        bad = missing_imports(repo, files, declared, rules["import_to_dist"])
        if bad:
            res.append((FAIL, "pyproject 依賴", "未登記：" + "; ".join(f"{k}（{sorted(v)[0]}）" for k, v in bad.items())))
        else:
            res.append((OK, "pyproject 依賴", "staged .py 的 import 皆已登記"))
        if "pyproject.toml" in files or (rc.get("rule_file") and rc["rule_file"] in files):
            res += [r for r in check_pyproject(name, rc, repo, None) if r[1] == "規則檔同步"]
    return res


def show(rows):
    for s, k, d in rows:
        print(f"[{s:4}] {k}: {d}")
    return any(r[0] == FAIL for r in rows)


def cmd_check(a):
    return 1 if show(check_repo(a.repo, load("repos.json"))) else 0


def cmd_commit(a):
    cfg = load("repos.json")
    repo = repo_path(cfg, a.repo)
    if show(check_repo(a.repo, cfg)) and not a.force_check:
        print("檢查未通過，已中止（未提交）。")
        return 1
    msg = Path(a.message_file)
    text = msg.read_text(encoding="utf-8").rstrip()
    footer = [f for f in load("commit.json")["message_footer"] if f not in text]
    if footer:
        msg = HERE / ".commit_msg_tmp"
        msg.write_text(text + "\n\n" + "\n".join(footer) + "\n", encoding="utf-8")
    code, o = run(["git", "commit", "-F", str(msg)], repo)
    print(o)
    if code != 0:
        return code
    if a.no_push:
        return 0
    _, br = run(["git", "branch", "--show-current"], repo)
    code, o = run(["git", "push", "-u", "origin", br], repo, timeout=180)
    print(o)
    return code


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("patrol")
    p.add_argument("--repo")
    p.add_argument("--json", action="store_true")
    p.set_defaults(f=cmd_patrol)
    p = sp.add_parser("sync")
    p.add_argument("--repo")
    p.add_argument("--fetch-only", action="store_true")
    p.set_defaults(f=cmd_sync)
    p = sp.add_parser("check")
    p.add_argument("repo")
    p.set_defaults(f=cmd_check)
    p = sp.add_parser("commit")
    p.add_argument("repo")
    p.add_argument("--message-file", required=True)
    p.add_argument("--no-push", action="store_true")
    p.add_argument("--force-check", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(f=cmd_commit)
    a = ap.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
