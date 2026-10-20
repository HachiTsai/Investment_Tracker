import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("repo_committer", Path(__file__).parent.parent / "scripts" / "committer.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_req_name_and_norm():
    assert mod.req_name("Python_Dotenv==1.0") == "python-dotenv"
    assert mod.req_name("pkg[extra]>=2") == "pkg"


def test_vtuple():
    assert mod.vtuple("3.14.6") == (3, 14, 6)
    assert mod.vtuple("v22.1") == (22, 1)


def test_rules_load():
    for name in ("repos.json", "tools.json", "commit.json"):
        assert mod.load(name)


def test_check_pyproject_flags_missing_package(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\nrequires-python=">=3.11"\ndependencies=["foo==1.0","bar>=2"]\n', encoding="utf-8")
    rc = {"pyproject": True, "rule_file": None}
    rows = mod.check_pyproject("x", rc, tmp_path, {"foo": "1.0"})
    assert any(s == mod.FAIL and "bar" in d for s, _, d in rows)
    rows = mod.check_pyproject("x", rc, tmp_path, {"foo": "1.0", "bar": "2.1"})
    assert not any(s == mod.FAIL for s, _, _ in rows)


def _git(cwd, *args):
    import subprocess
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


def test_sync_fast_forwards_clean_repo(tmp_path):
    a, b = _make_pair(tmp_path)
    (a / "g.txt").write_text("2", encoding="utf-8")
    _git(a, "add", ".")
    _git(a, "commit", "-qm", "more")
    _git(a, "push", "-q")
    rows = mod.sync_path(b)
    assert any(s == mod.OK and k == "快轉" for s, k, _ in rows)
    assert (b / "g.txt").exists()


def test_sync_skips_dirty_repo(tmp_path):
    a, b = _make_pair(tmp_path)
    (a / "g.txt").write_text("2", encoding="utf-8")
    _git(a, "add", ".")
    _git(a, "commit", "-qm", "more")
    _git(a, "push", "-q")
    (b / "f.txt").write_text("local edit", encoding="utf-8")
    rows = mod.sync_path(b)
    assert any(k == "略過" for _, k, _ in rows)
    assert not (b / "g.txt").exists()


def test_sync_reports_divergence_without_merging(tmp_path):
    a, b = _make_pair(tmp_path)
    (a / "g.txt").write_text("2", encoding="utf-8")
    _git(a, "add", ".")
    _git(a, "commit", "-qm", "remote")
    _git(a, "push", "-q")
    (b / "h.txt").write_text("3", encoding="utf-8")
    _git(b, "add", ".")
    _git(b, "commit", "-qm", "local")
    rows = mod.sync_path(b)
    assert any(s == mod.FAIL and k == "分叉" for s, k, _ in rows)
    assert not (b / "g.txt").exists()


def test_sync_flags_merged_feature_branch(tmp_path):
    _, b = _make_pair(tmp_path)
    _git(b, "checkout", "-q", "-b", "feat")
    _git(b, "push", "-q", "-u", "origin", "feat")
    rows = mod.sync_path(b)
    assert any(k == "分支已併入" for _, k, _ in rows)
