#!/usr/bin/env python3
"""markdown-linter：以 markdownlint-cli2 檢查（或修正）REPO 內的 Markdown。

用法：
  mdlint.py                 檢查全部 *.md
  mdlint.py PATH ...        只檢查指定檔案
  mdlint.py --fix [PATH]    自動修正可修的問題，再回報剩餘問題

規則設定在 REPO 根目錄的 .markdownlint-cli2.jsonc；CI 也呼叫本腳本，確保本機與 CI 結果一致。
回傳碼：0 無問題、1 有 lint 錯誤、2 無法執行（缺 Node.js）。
"""

import argparse
import io
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

if sys.platform == "win32" and hasattr(sys.stdout, "buffer") and "pytest" not in sys.modules:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

#: 固定版本，避免規則隨上游更新而在本機與 CI 間漂移；升級時只改這裡
LINTER_PACKAGE = "markdownlint-cli2@0.23.3"
CONFIG_NAME = ".markdownlint-cli2.jsonc"
DEFAULT_GLOB = "**/*.md"
EXIT_UNAVAILABLE = 2


def repo_root() -> Path:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, check=True)
        top = out.stdout.decode("utf-8").strip()
        if top:
            return Path(top)
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.cwd()


def to_lint_args(paths: List[str], root: Path) -> List[str]:
    """轉成相對 root 的 POSIX 路徑；只保留 .md，不存在的檔案略過（例如已刪除的檔案）。"""
    args = []
    for raw in paths:
        p = Path(raw)
        p = p if p.is_absolute() else (Path.cwd() / p)
        if p.suffix.lower() != ".md" or not p.exists():
            continue
        try:
            args.append(p.resolve().relative_to(root.resolve()).as_posix())
        except ValueError:
            args.append(p.resolve().as_posix())
    return args


def build_command(npx: str, targets: List[str], fix: bool) -> List[str]:
    cmd = [npx, "--yes", LINTER_PACKAGE]
    if fix:
        cmd.append("--fix")
    # 以 : 開頭表示字面路徑而非 glob，避免檔名中的特殊字元被當成萬用字元
    return cmd + [f":{t}" if t != DEFAULT_GLOB else t for t in targets]


def lint(paths: Optional[List[str]] = None, fix: bool = False, root: Optional[Path] = None) -> int:
    root = root or repo_root()
    if paths:
        targets = to_lint_args(paths, root)
        if not targets:
            print("   ✅ [MDLint] 沒有需要檢查的 Markdown 檔案。")
            return 0
    else:
        targets = [DEFAULT_GLOB]

    npx = shutil.which("npx")
    if not npx:
        print(
            "   ❌ [MDLint] 找不到 npx，無法執行 markdownlint。\n"
            "      請安裝 Node.js（https://nodejs.org/，內含 npx）後重試。",
            file=sys.stderr,
        )
        return EXIT_UNAVAILABLE

    result = subprocess.run(build_command(npx, targets, fix), cwd=root, capture_output=True)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    issues = [l for l in output.splitlines() if " error MD" in l or " warning MD" in l]
    if result.returncode == 0:
        print(f"   ✅ [MDLint] Markdown 檢查通過（{LINTER_PACKAGE}）。")
        return 0
    if not issues:
        # 非 lint 問題的失敗（例如網路無法下載套件），原樣輸出以利排查
        print(output, file=sys.stderr)
        print("   ❌ [MDLint] markdownlint 執行失敗。", file=sys.stderr)
        return EXIT_UNAVAILABLE
    print(f"   ❌ [MDLint] {len(issues)} 個 Markdown 問題：", file=sys.stderr)
    for line in issues:
        print(f"      {line}", file=sys.stderr)
    print("   💡 可先執行 mdlint.py --fix 自動修正，剩下的再手動處理。", file=sys.stderr)
    return 1


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Markdown lint（markdownlint-cli2）")
    p.add_argument("paths", nargs="*", help="要檢查的檔案；省略時檢查全部 *.md")
    p.add_argument("--fix", action="store_true", help="自動修正可修的問題")
    args = p.parse_args(argv)
    return lint(args.paths or None, fix=args.fix)


if __name__ == "__main__":
    sys.exit(main())
