"""Fin-Commit 安全性與 Python 依賴／規則同步檢查模組（DepGuard）。

包含：
1. 敏感機密檔案偵測（find_sensitive）
2. 規則文件索引同步檢查（find_rule_sync_issues）
3. Python AST 語法樹 imports 與 pyproject.toml 依賴比對（find_dependency_issues）
4. pyproject.toml 與實際安裝環境（.venv）比對（find_env_issues，SessionStart 唯讀警告）
"""

import ast
import fnmatch
import importlib.metadata
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Sequence, Set

try:
    REPO_ROOT = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
except Exception:
    REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

SENSITIVE_PATTERNS = [
    ".env*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "credentials.json",
    "client_secret*.json",
    "service_account*.json",
    "id_rsa*",
    "id_ed25519*",
]

TOML_BLOCK_RE = re.compile(r"```toml\s*\n(.*?)\n```", re.DOTALL)
REQ_PKG_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)")
DEPS_BLOCK_RE = re.compile(r"dependencies\s*=\s*\[(.*?)\]", re.DOTALL)
ITEM_PKG_RE = re.compile(r'["\']([A-Za-z0-9_.\-]+)')


def path_matches(path_str: str, pattern: str) -> bool:
    p = Path(path_str)
    if fnmatch.fnmatch(p.name, pattern):
        return True
    return any(fnmatch.fnmatch(part, pattern) for part in p.parts)


def find_sensitive(files: Sequence[str]) -> List[str]:
    hits = []
    for f in files:
        for pat in SENSITIVE_PATTERNS:
            if path_matches(f, pat) or "/credentials/" in f.replace("\\", "/"):
                hits.append(f"{f}（符合敏感檔規則 `{pat}`）")
                break
    return hits


def normalize_pkg_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _extract_deps_from_toml(text: str) -> Set[str]:
    m = DEPS_BLOCK_RE.search(text)
    if not m:
        return set()
    block = m.group(1)
    lines = [l.split("#")[0] for l in block.splitlines()]
    clean_block = "\n".join(lines)
    return {normalize_pkg_name(pkg) for pkg in ITEM_PKG_RE.findall(clean_block)}


def parse_pyproject_deps(path: Path) -> Set[str]:
    if not path.is_file():
        return set()
    return _extract_deps_from_toml(path.read_text(encoding="utf-8", errors="replace"))


def parse_rule_toml_deps(path: Path) -> Set[str]:
    if not path.is_file():
        return set()
    m = TOML_BLOCK_RE.search(path.read_text(encoding="utf-8", errors="replace"))
    return _extract_deps_from_toml(m.group(1)) if m else set()


def _local_module_names(repo_root: Path) -> Set[str]:
    names: Set[str] = set()
    skip_dirs = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules"}
    for p in repo_root.rglob("*.py"):
        if any(part in skip_dirs for part in p.parts):
            continue
        names.add(p.stem)
        if p.parent != repo_root:
            names.add(p.parent.name)
    return names


def find_rule_sync_issues(repo_root: Path = REPO_ROOT) -> List[str]:
    """Verify that .claude/rules/*.md are indexed in both CLAUDE.md and .agent/rules/AGENT.md."""
    issues: List[str] = []
    claude_rules = repo_root / ".claude" / "rules"
    agent_rules = repo_root / ".agent" / "rules"
    agent_md = agent_rules / "AGENT.md"
    claude_md = repo_root / "CLAUDE.md"

    if agent_rules.is_dir():
        extra_agent_files = [p.name for p in sorted(agent_rules.glob("*.md")) if p.name != "AGENT.md"]
        if extra_agent_files:
            issues.append(f".agent/rules/ 僅應保留 AGENT.md 單一入口，請將規則移至 .claude/rules/：{', '.join(extra_agent_files)}")

    if claude_rules.is_dir():
        rule_files = sorted(claude_rules.glob("*.md"))
        if claude_md.is_file():
            claude_text = claude_md.read_text(encoding="utf-8", errors="replace")
            for rf in rule_files:
                if rf.name not in claude_text:
                    issues.append(f".claude/rules/{rf.name} 尚未加入 CLAUDE.md 索引中")
        if agent_md.is_file():
            agent_text = agent_md.read_text(encoding="utf-8", errors="replace")
            for rf in rule_files:
                if rf.name not in agent_text:
                    issues.append(f".claude/rules/{rf.name} 尚未加入 .agent/rules/AGENT.md 索引中")
    return issues


def find_dependency_issues(files: Sequence[str], repo_root: Path = REPO_ROOT) -> List[str]:
    """Check staged .py imports against pyproject.toml, and sync with .claude/rules/python-environment.md."""
    issues: List[str] = find_rule_sync_issues(repo_root)
    pyproj_path = repo_root / "pyproject.toml"
    rule_path = repo_root / ".claude" / "rules" / "python-environment.md"
    has_pyproj, has_rule = pyproj_path.is_file(), rule_path.is_file()
    if not has_pyproj and not has_rule:
        return issues

    pyproj_pkgs = parse_pyproject_deps(pyproj_path)
    rule_pkgs = parse_rule_toml_deps(rule_path)
    declared = pyproj_pkgs | rule_pkgs

    if has_pyproj and has_rule:
        for pkg in sorted(pyproj_pkgs - rule_pkgs):
            issues.append(f"{pkg}（僅在 pyproject.toml，未同步至 .claude/rules/python-environment.md）")
        for pkg in sorted(rule_pkgs - pyproj_pkgs):
            issues.append(f"{pkg}（僅在 .claude/rules/python-environment.md，未同步至 pyproject.toml）")

    py_files = [f for f in files if Path(f).suffix.lower() == ".py" and (repo_root / f).is_file()]
    if not py_files:
        return issues

    local_mods = _local_module_names(repo_root)
    stdlib_mods = getattr(sys, "stdlib_module_names", set()) | {"__future__"}
    pkg_dists = importlib.metadata.packages_distributions()

    for f in py_files:
        try:
            tree = ast.parse((repo_root / f).read_text(encoding="utf-8", errors="replace"), filename=f)
        except SyntaxError:
            continue
        imported: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])

        for mod in sorted(imported):
            if mod in stdlib_mods or mod in local_mods:
                continue
            dists = pkg_dists.get(mod) or [mod]
            if any(normalize_pkg_name(d) in declared for d in dists):
                continue
            dist = dists[0]
            try:
                spec = f"{dist}=={importlib.metadata.version(dist)}"
            except importlib.metadata.PackageNotFoundError:
                spec = dist
            issues.append(f"{spec}（於 {f} 匯入 `{mod}`，未記錄於 pyproject.toml）")
    return issues


def _version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v.split("+")[0])[:3])


def find_env_issues(repo_root: Path = REPO_ROOT) -> List[str]:
    """Compare pyproject.toml dependencies with what is actually installed (.venv, else current interpreter)."""
    pyproj = repo_root / "pyproject.toml"
    if not pyproj.is_file():
        return []
    sites = sorted((repo_root / ".venv").glob("lib/python*/site-packages"))
    dists = (
        importlib.metadata.distributions(path=[str(s) for s in sites])
        if sites
        else importlib.metadata.distributions()
    )
    installed = {normalize_pkg_name(d.metadata["Name"]): d.version for d in dists if d.metadata["Name"]}
    m = DEPS_BLOCK_RE.search(pyproj.read_text(encoding="utf-8", errors="replace"))
    block = "\n".join(l.split("#")[0] for l in (m.group(1) if m else "").splitlines())
    issues: List[str] = []
    for spec in re.findall(r'"([^"]+)"', block):
        name = normalize_pkg_name(re.split(r"[<>=!~\[ ;]", spec)[0])
        floor = re.search(r">=\s*([\w.]+)", spec)
        if name not in installed:
            issues.append(f"{name}（pyproject.toml 已宣告，環境未安裝）")
        elif floor and _version_tuple(installed[name]) < _version_tuple(floor.group(1)):
            issues.append(f"{name}（已安裝 {installed[name]}，低於 pyproject.toml 要求 >={floor.group(1)}）")
    return issues
