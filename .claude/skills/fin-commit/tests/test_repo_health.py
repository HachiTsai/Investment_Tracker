import importlib.util
import subprocess
from pathlib import Path

_spec = importlib.util.spec_from_file_location("it_repo_health", Path(__file__).parent.parent / "scripts" / "repo_health.py")
rh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rh)


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _make_pair(tmp_path):
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    a, b = tmp_path / "a", tmp_path / "b"
    _git(tmp_path, "clone", "-q", str(bare), str(a))
    (a / "f.txt").write_text("1", encoding="utf-8")
    _git(a, "add", ".")
    _git(a, "commit", "-qm", "init")
    _git(a, "push", "-q", "-u", "origin", "main")
    _git(tmp_path, "clone", "-q", str(bare), str(b))
    return a, b


def _push_more(a, name="g.txt"):
    (a / name).write_text("2", encoding="utf-8")
    _git(a, "add", ".")
    _git(a, "commit", "-qm", "more")
    _git(a, "push", "-q")


def test_sync_fast_forwards_clean_repo(tmp_path):
    a, b = _make_pair(tmp_path)
    _push_more(a)
    rows = rh.sync_repo(b)
    assert any(s == rh.OK and k == "快轉" for s, k, _ in rows)
    assert (b / "g.txt").exists()


def test_sync_skips_dirty_repo(tmp_path):
    a, b = _make_pair(tmp_path)
    _push_more(a)
    (b / "f.txt").write_text("local", encoding="utf-8")
    rows = rh.sync_repo(b)
    assert any(k == "略過" for _, k, _ in rows)
    assert (b / "f.txt").read_text(encoding="utf-8") == "local"
    assert not (b / "g.txt").exists()


def test_sync_reports_divergence_without_merging(tmp_path):
    a, b = _make_pair(tmp_path)
    _push_more(a)
    (b / "h.txt").write_text("x", encoding="utf-8")
    _git(b, "add", ".")
    _git(b, "commit", "-qm", "local")
    rows = rh.sync_repo(b)
    assert any(s == rh.FAIL and k == "分叉" for s, k, _ in rows)
    assert not (b / "g.txt").exists()


def test_sync_flags_merged_feature_branch(tmp_path):
    a, b = _make_pair(tmp_path)
    _git(b, "checkout", "-q", "-b", "feat")
    rows = rh.sync_repo(b)
    assert any(k == "分支已併入" for _, k, _ in rows)


def test_check_installed_flags_missing_package(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\nrequires-python=">=3.11"\ndependencies=["no-such-pkg-xyz==1.0"]\n', encoding="utf-8")
    rows = rh.check_installed(tmp_path)
    assert any(s == rh.FAIL and "no-such-pkg-xyz" in d for s, _, d in rows)


def test_guards():
    assert rh.protected_branch_issue("main")
    assert rh.protected_branch_issue("feat") is None
    assert rh.claude_without_rules_warning([".claude/skills/a/x.py"])
    assert rh.claude_without_rules_warning([".claude/skills/a/x.py", ".claude/rules/r.md"]) is None


def test_patrol_uses_repo_own_env_check(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    rows = rh.patrol_repo(tmp_path, installed_check=lambda: ["foo 缺少"])
    assert any(k == "環境比對" and "foo" in d for _, k, d in rows)
    rows = rh.patrol_repo(tmp_path, installed_check=lambda: [])
    assert any(s == rh.OK and k == "環境比對" for s, k, _ in rows)
