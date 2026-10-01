import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import notes as n  # noqa: E402

FORMAT_DOC = n.SKILL_DIR / "references" / "format-arch.md"


def example_note() -> str:
    """format-arch.md 裡的範例筆記，也是格式的標準答案。"""
    doc = FORMAT_DOC.read_text(encoding="utf-8")
    return re.search(r"```markdown\n(.*?)```", doc, re.S).group(1)


def write(root: Path, title: str, text: str) -> Path:
    path = root / "architecture" / f"{title}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def errors_of(root: Path, title: str, text: str):
    return n.check_note(write(root, title, text), n.load_vocabulary(), root)[0]


def test_vocabulary_loads():
    vocab = n.load_vocabulary()
    assert "目標" in vocab["domain"]
    assert vocab["status"] == ["草稿", "生效", "修訂中", "廢止"]
    assert "高股息" in vocab["tags"]


def test_format_doc_example_passes(tmp_path):
    assert errors_of(tmp_path, "股利目標模型", example_note()) == []


def test_new_then_check_has_only_placeholder_warning(tmp_path):
    rc = n.main(["--root", str(tmp_path), "new", "arch", "股息再投入規則",
                 "--domain", "股利", "--tags", "再投入,複利", "--tickers", "00882", "--date", "2026-10-01"])
    assert rc == 0
    path = tmp_path / "architecture" / "股息再投入規則.md"
    errors, warnings = n.check_note(path, n.load_vocabulary(), tmp_path)
    assert errors == []
    assert any(n.PLACEHOLDER in w for w in warnings)


def test_new_rejects_date_title_unknown_tag_and_duplicate(tmp_path, capsys):
    base = ["--root", str(tmp_path), "new", "arch"]
    assert n.main(base + ["2026-10-01-配置", "--domain", "配置", "--tags", "ETF"]) == 1
    assert n.main(base + ["配置原則", "--domain", "配置", "--tags", "人工智慧"]) == 1
    assert n.main(base + ["配置原則", "--domain", "配置", "--tags", "ETF"]) == 0
    assert n.main(base + ["配置原則", "--domain", "配置", "--tags", "ETF"]) == 1
    err = capsys.readouterr().err
    assert "日期" in err and "人工智慧" in err and "已存在" in err


def test_title_rules():
    assert n.check_title("股利目標模型") == []
    assert n.check_title("20261001配置")
    assert n.check_title("配置 原則")
    assert n.check_title("配置:原則")


def test_filename_must_match_title(tmp_path):
    errs = errors_of(tmp_path, "別的名字", example_note())
    assert any("不一致" in e for e in errs)


def test_controlled_vocabulary(tmp_path):
    text = example_note().replace("domain: 目標", "domain: 投資").replace("[股利, 高股息, 複利]", "[股利, AI]")
    errs = errors_of(tmp_path, "股利目標模型", text)
    assert any("domain" in e for e in errs)
    assert any("'AI'" in e for e in errs)


def test_version_must_match_changelog(tmp_path):
    errs = errors_of(tmp_path, "股利目標模型", example_note().replace("version: 1", "version: 2"))
    assert any("變更紀錄最新版本" in e for e in errs)


def test_missing_and_misordered_sections(tmp_path):
    text = example_note()
    errs = errors_of(tmp_path, "股利目標模型", text.replace("## 理由", "## 原因"))
    assert any("缺少段落" in e for e in errs)
    swapped = text.replace("## 摘要", "## TMP").replace("## 規則", "## 摘要").replace("## TMP", "## 規則")
    assert any("段落順序" in e for e in errors_of(tmp_path, "股利目標模型", swapped))


def test_field_formats(tmp_path):
    text = (example_note()
            .replace("created: 2026-10-01", "created: 2026/10/01")
            .replace("tickers: [00882]", "tickers: [TPE:00882]")
            .replace('related: ["[[股息再投入規則]]"]', "related: [股息再投入規則]")
            .replace("aliases:", "author: hachi\naliases:"))
    errs = errors_of(tmp_path, "股利目標模型", text)
    for keyword in ("created", "ticker", "related", "未定義的欄位 author"):
        assert any(keyword in e for e in errs), keyword


def test_wrong_directory(tmp_path):
    path = tmp_path / "research" / "股利目標模型.md"
    path.parent.mkdir()
    path.write_text(example_note(), encoding="utf-8")
    errs = n.check_note(path, n.load_vocabulary(), tmp_path)[0]
    assert any("architecture/" in e for e in errs)


def test_find_filters(tmp_path, capsys):
    write(tmp_path, "股利目標模型", example_note())
    n.main(["--root", str(tmp_path), "new", "arch", "單一標的集中度上限",
            "--domain", "風險", "--tags", "集中度", "--date", "2026-10-01"])
    capsys.readouterr()

    n.main(["--root", str(tmp_path), "find", "--ticker", "00882"])
    out = capsys.readouterr().out
    assert "股利目標模型" in out and "集中度" not in out and "共 1 篇" in out
    assert "以每年股利收入" in out  # 顯示摘要

    n.main(["--root", str(tmp_path), "find", "--status", "草稿"])
    assert "單一標的集中度上限" in capsys.readouterr().out

    n.main(["--root", str(tmp_path), "find", "--tag", "股利", "--tag", "集中度"])
    assert "找不到" in capsys.readouterr().out

    n.main(["--root", str(tmp_path), "find", "--text", "殖利率倒推"])
    assert "股利目標模型" in capsys.readouterr().out


def test_wikilink_list_with_comma_inside():
    assert n._parse_value('["[[A, B]]", "[[C]]"]') == ["[[A, B]]", "[[C]]"]


needs_npx = __import__("pytest").mark.skipif(
    __import__("shutil").which("npx") is None, reason="需要 Node.js（npx）")
REPO_ROOT = Path(__file__).resolve().parents[4]


def _with_lint_config(root: Path) -> None:
    (root / ".markdownlint-cli2.jsonc").write_text(
        (REPO_ROOT / ".markdownlint-cli2.jsonc").read_text(encoding="utf-8"), encoding="utf-8")


@needs_npx
def test_generated_and_example_notes_pass_markdown_lint(tmp_path):
    _with_lint_config(tmp_path)
    write(tmp_path, "股利目標模型", example_note())
    n.main(["--root", str(tmp_path), "new", "arch", "股息再投入規則",
            "--domain", "股利", "--tags", "再投入", "--date", "2026-10-01"])
    assert n.main(["--root", str(tmp_path), "check"]) == 0


@needs_npx
def test_check_fails_on_markdown_error(tmp_path):
    _with_lint_config(tmp_path)
    bad = example_note().replace("## 規則\n\n", "## 規則\n").replace("---\n\n## 摘要", "---\n\n# 股利目標模型\n\n## 摘要")
    write(tmp_path, "股利目標模型", bad)
    assert n.check_note(tmp_path / "architecture" / "股利目標模型.md", n.load_vocabulary(), tmp_path)[0] == []
    assert n.main(["--root", str(tmp_path), "check"]) == 1
