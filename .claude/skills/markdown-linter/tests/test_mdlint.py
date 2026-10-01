import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import mdlint as m  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[4]
needs_npx = pytest.mark.skipif(shutil.which("npx") is None, reason="需要 Node.js（npx）")


def test_to_lint_args_filters_and_relativizes(tmp_path):
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("", encoding="utf-8")
    args = m.to_lint_args([str(tmp_path / "a.md"), str(tmp_path / "b.py"), str(tmp_path / "gone.md")], tmp_path)
    assert args == ["a.md"]


def test_build_command_uses_pinned_package_and_literal_paths():
    cmd = m.build_command("npx", ["docs/a.md"], fix=True)
    assert cmd == ["npx", "--yes", m.LINTER_PACKAGE, "--fix", ":docs/a.md"]
    assert m.build_command("npx", [m.DEFAULT_GLOB], fix=False)[-1] == m.DEFAULT_GLOB


def test_missing_npx_fails_closed(monkeypatch, tmp_path):
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")
    monkeypatch.setattr(m.shutil, "which", lambda _: None)
    assert m.lint([str(tmp_path / "a.md")], root=tmp_path) == m.EXIT_UNAVAILABLE


def test_no_markdown_targets_is_ok(tmp_path):
    assert m.lint([str(tmp_path / "x.py")], root=tmp_path) == 0


def test_config_exists_at_repo_root():
    assert (REPO_ROOT / m.CONFIG_NAME).is_file()


@needs_npx
def test_detects_and_fixes_errors(tmp_path):
    (tmp_path / m.CONFIG_NAME).write_text((REPO_ROOT / m.CONFIG_NAME).read_text(encoding="utf-8"), encoding="utf-8")
    bad = tmp_path / "bad.md"
    bad.write_text("# 標題\n文字緊接標題\n\n```\ncode\n```\n", encoding="utf-8")
    assert m.lint([str(bad)], root=tmp_path) == 1
    m.lint([str(bad)], fix=True, root=tmp_path)
    assert "# 標題\n\n文字" in bad.read_text(encoding="utf-8")


@needs_npx
def test_repo_markdown_is_clean():
    assert m.lint(root=REPO_ROOT) == 0
