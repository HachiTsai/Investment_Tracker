"""Fin-Commit Git 底層操作與 Markdown 檢查模組（GitOps）。

包含：
1. Git 命令執行（git）
2. 暫存區檔案、diff 與統計資訊獲取（get_staged_file_list, get_git_diff, get_git_stats）
3. 暫存操作與排除機制（run_git_add）
4. commit-msg hook 安裝（install_hook）
5. 暫存區 Markdown Lint 檢查（lint_staged_markdown）
"""

import subprocess
import sys
from pathlib import Path
from typing import List, Optional

SKILL_DIR = Path(__file__).resolve().parent.parent
MDLINT_DIR = SKILL_DIR.parent / "markdown-linter" / "scripts"


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.quotePath=false", *args], capture_output=True, check=check)


def get_staged_file_list() -> List[str]:
    """已暫存檔案清單；強制 core.quotePath=false，避免中文路徑被跳脫。"""
    try:
        out = git("diff", "--staged", "--name-only").stdout.decode("utf-8", errors="replace")
        return [line.strip() for line in out.splitlines() if line.strip()]
    except subprocess.CalledProcessError:
        return []


def get_git_diff() -> str:
    try:
        return git("diff", "--staged").stdout.decode("utf-8", errors="replace")
    except subprocess.CalledProcessError:
        return ""


def get_git_stats() -> str:
    try:
        return git("diff", "--staged", "--stat").stdout.decode("utf-8", errors="replace")
    except subprocess.CalledProcessError:
        return "N/A"


def run_git_add(paths: Optional[List[str]] = None, exclude: Optional[List[str]] = None) -> bool:
    """paths：清空暫存後只 add 指定路徑；exclude：git add . 後排除；皆無：git add .。"""
    try:
        if paths:
            print("   🧹 [Git] 清空暫存區後只暫存指定路徑...")
            subprocess.run(["git", "reset", "-q", "HEAD"], check=False)
            print(f"   📦 [Git] git add -- {' '.join(paths)}")
            subprocess.run(["git", "add", "--", *paths], check=True)
            return True
        print("   📦 [Git] git add .")
        subprocess.run(["git", "add", "."], check=True)
        if exclude:
            print(f"   🚫 [Git] 排除：{' '.join(exclude)}")
            subprocess.run(["git", "reset", "-q", "HEAD", "--", *exclude], check=False)
        return True
    except subprocess.CalledProcessError as e:
        print(f"   ❌ [Git] 暫存失敗：{e}", file=sys.stderr)
        return False


def install_hook() -> int:
    """安裝 commit-msg hook：任何 git commit 都經過 validate_message。"""
    hooks_dir = Path(git("rev-parse", "--git-path", "hooks").stdout.decode().strip())
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook = hooks_dir / "commit-msg"
    committer_path = Path(__file__).resolve().parent / "committer.py"
    hook.write_text(f'#!/bin/sh\nexec python3 "{committer_path}" --check "$1"\n', encoding="utf-8")
    hook.chmod(0o755)
    print(f"   ✅ [Hook] 已安裝 commit-msg hook：{hook}")
    return 0


def lint_staged_markdown(staged_files: List[str]) -> int:
    """暫存區內的 .md 必須通過 markdown-linter；回傳 0 表示通過或無 .md。"""
    md_files = [f for f in staged_files if f.lower().endswith(".md")]
    if not md_files:
        return 0
    sys.path.insert(0, str(MDLINT_DIR))
    try:
        import mdlint
    except ImportError:
        print("   ❌ [MDLint] 找不到 markdown-linter skill（.claude/skills/markdown-linter/）", file=sys.stderr)
        return 1
    print(f"   🔍 [MDLint] 檢查暫存區 {len(md_files)} 個 Markdown 檔案...")
    return mdlint.lint(md_files)
