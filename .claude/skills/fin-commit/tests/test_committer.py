import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import committer as c  # noqa: E402

REINVEST_MSG = """reinvest(00882): 股息 158,344 再投入 10 張 @15.08

## 核心變更

- 記錄 8/11 股息再投入

## 變更理由

- 7 月除息股利全數再投入，維持複利

## 交易明細

- **日期**: 2026-08-11
- **數量**: 10,000 股（10 張）
- **價格**: 15.08
- **金額**: 150,800 TWD
- **手續費**: 215
- **理由**: 股利再投入
- **來源**: Core/Transactions Tx_ID ad364a04

## 驗證

- 10,000 × 15.08 = 150,800，與 Core 一致

## 目標影響

- 持股 290 張 → 300 張

## Session-Sync

- **執行者**: Claude
- **類別**: 交易紀錄
- **狀態**: 已記錄
- **下一步**: 無
- **阻塞**: 無
"""


def test_valid_trade_message_passes_without_warnings():
    errors, warnings = c.validate_message(REINVEST_MSG)
    assert errors == []
    assert warnings == []


def test_trade_without_detail_section_is_blocked():
    msg = "buy(00882): 買進 2 張\n\n## 核心變更\n\n- 買進\n"
    errors, _ = c.validate_message(msg)
    assert any("交易明細" in e for e in errors)


def test_amount_mismatch_and_bad_date_are_blocked():
    msg = REINVEST_MSG.replace("150,800 TWD", "150,000 TWD").replace("2026-08-11\n", "2026/8/11\n")
    errors, _ = c.validate_message(msg)
    assert any("金額不符" in e for e in errors)
    assert any("日期格式" in e for e in errors)


def test_sell_requires_pnl():
    msg = REINVEST_MSG.replace("reinvest(00882)", "sell(00882)")
    errors, _ = c.validate_message(msg)
    assert any("損益" in e for e in errors)


def test_div_requires_dividend_section():
    errors, _ = c.validate_message("div(00882): 7 月除息入帳\n\n## 核心變更\n\n- x\n")
    assert any("股利明細" in e for e in errors)


def test_non_trade_message_only_warns_on_missing_sections():
    errors, warnings = c.validate_message("docs(claude): 更新說明\n")
    assert errors == []
    assert any("核心變更" in w for w in warnings)


def test_header_rules():
    assert c.validate_message("feat: x")[0]
    assert any("未知的 type" in e for e in c.validate_message("feat(x): y")[0])
    assert any("句號" in e for e in c.validate_message("docs(x): 更新。")[0])
    assert any("空一行" in e for e in c.validate_message("docs(x): 更新\nbody")[0])
    assert c.validate_message("Merge pull request #1 from x") == ([], [])


def test_infer_category_priority():
    assert c.infer_category(["portfolio/transactions/2026.md", "CLAUDE.md"]) == c.CATEGORY_TRADE
    assert c.infer_category(["portfolio/snapshots/2026-10-01.md"]) == c.CATEGORY_PORTFOLIO
    assert c.infer_category(["research/00882_配息.md"]) == c.CATEGORY_RESEARCH
    assert c.infer_category(["CLAUDE.md"]) == c.CATEGORY_IT
    assert c.infer_category(["architecture/資產配置.md"]) == c.CATEGORY_ARCH
    assert c.infer_category(["trends/AI電力需求.md"]) == c.CATEGORY_TREND
    assert c.infer_category(["trends/a.md", "research/b.md"]) == c.CATEGORY_RESEARCH


def test_infer_scope():
    assert c.infer_scope(["research/00882_配息.md"]) == "00882"
    assert c.infer_scope(["portfolio/snapshots/2026-10-01.md"]) == "portfolio"
    assert c.infer_scope([".claude/skills/fin-commit/SKILL.md", ".claude/skills/fin-commit/x.py"]) == "fin-commit"
    assert c.infer_scope(["CLAUDE.md"]) == "claude"
    assert c.infer_scope(["README.md"]) == "project"
    assert c.infer_scope(["trends/AI電力需求.md"]) == "trends"
    assert c.infer_scope(["architecture/資產配置.md"]) == "architecture"


def test_infer_commit_type_for_thinking_docs():
    assert c.infer_commit_type(["architecture/資產配置.md"]) == "arch"
    assert c.infer_commit_type(["trends/AI電力需求.md"]) == "trend"
    assert c.infer_commit_type(["research/00882_配息.md"]) == "research"
    assert c.infer_commit_type(["portfolio/snapshots/2026-10-01.md"]) == "snap"


def test_auto_quick_guard():
    assert c.check_auto_quick_guard(["portfolio/transactions/a.md"], c.CATEGORY_TRADE)
    assert c.check_auto_quick_guard(["CLAUDE.md"], c.CATEGORY_IT)
    assert c.check_auto_quick_guard([".claude/skills/fin-commit/SKILL.md"], c.CATEGORY_IT)
    assert c.check_auto_quick_guard(["research/a.md"], c.CATEGORY_RESEARCH) == []


def test_quick_message_is_valid():
    msg = c.build_quick_commit_message(["research/00882_配息.md"], c.CATEGORY_RESEARCH, agent="claude")
    assert msg.startswith("research(00882): ")
    assert c.validate_message(msg) == ([], [])
    assert c.L1_UNSPECIFIED in msg


def test_ensure_coauthor_line():
    signed = c.ensure_coauthor_line("docs(x): y\n")
    assert signed.endswith(c.COAUTHOR_LINE + "\n")
    assert c.ensure_coauthor_line(signed) == signed
    versioned = "docs(x): y\n\nCo-Authored-By: Claude Opus <noreply@anthropic.com>\n"
    assert c.ensure_coauthor_line(versioned) == versioned


def test_detect_agent(monkeypatch):
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.setenv("CLAUDECODE", "0")
    assert c.detect_agent() == c.UNKNOWN_AGENT
    monkeypatch.setenv("CLAUDECODE", "1")
    assert c.detect_agent() == "claude"
    monkeypatch.setenv("AGENT_ID", "Kimi")
    assert c.detect_agent() == "kimi"
    assert c.detect_agent("nobody") == c.UNKNOWN_AGENT


def test_spec_template_examples_are_consistent():
    spec = c.SPEC_PATH.read_text(encoding="utf-8")
    for t in c.TYPES:
        assert f"`{t}`" in spec, f"規格書缺少 type {t}"
    for category in c.CATEGORIES_REGISTRY:
        assert category in spec, f"規格書缺少類別 {category}"


def test_find_sensitive():
    assert c.find_sensitive(["main.py", "README.md"]) == []
    hits = c.find_sensitive([".env", "server.key", "credentials.json", "safe.py"])
    assert len(hits) == 3


def test_find_dependency_and_rule_sync_issues(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    pyproj = repo / "pyproject.toml"
    pyproj.write_text('[project]\nname = "test"\ndependencies = ["pytest>=8.0.0"]\n')

    rules_dir = repo / ".claude" / "rules"
    rules_dir.mkdir(parents=True)
    rule_env = rules_dir / "python-environment.md"
    rule_env.write_text('# Python Env\n```toml\n[project]\nname = "test"\ndependencies = ["pytest>=8.0.0"]\n```\n')

    app_py = repo / "app.py"
    app_py.write_text("import os\nimport pytest\n")

    # All in sync
    assert c.find_dependency_issues(["app.py"], repo_root=repo) == []

    # Unrecorded package imported
    app_py.write_text("import os\nimport unrecorded_pkg_xyz\n")
    issues = c.find_dependency_issues(["app.py"], repo_root=repo)
    assert any("unrecorded_pkg_xyz" in issue for issue in issues)

    # Missing from rule_env
    pyproj.write_text('[project]\nname = "test"\ndependencies = ["pytest>=8.0.0", "requests>=2.0.0"]\n')
    issues = c.find_dependency_issues([], repo_root=repo)
    assert any("requests" in issue and "未同步至 .claude/rules/python-environment.md" in issue for issue in issues)


def test_patrol_commit_message_and_inference():
    patrol_msg = """patrol(fleet): 🔵 全投資組合穩健複利 ｜ 50萬達成率 51.2% ｜ LPR 3.0% ｜ SCFI 3679

## 核心變更

- 投資組合每日例行巡檢完成
- 總體狀態：穩健複利

## 變更理由

- 港股盤後例行自動巡檢

## 驗證

- models/*/cards/ 求值正常

## Session-Sync

- **執行者**: Antigravity
- **類別**: 持股分析
- **狀態**: 正常
- **下一步**: 無
- **阻塞**: 無
"""
    errors, warnings = c.validate_message(patrol_msg)
    assert errors == []
    assert warnings == []
    assert c.infer_category(["reports/portfolio_briefing.md"]) == c.CATEGORY_PORTFOLIO
    assert c.infer_scope(["reports/portfolio_briefing.md"]) == "fleet"
    assert c.infer_commit_type(["reports/portfolio_briefing.md"]) == "patrol"


def test_find_env_issues_reports_missing_and_old(tmp_path):
    repo = tmp_path
    (repo / "pyproject.toml").write_text('[project]\ndependencies = [\n    "pytest>=0.0.1",\n    "no-such-pkg-xyz>=1.0",\n]\n', encoding="utf-8")
    issues = c.find_env_issues(repo_root=repo)
    assert any("no-such-pkg-xyz" in i for i in issues)
    assert not any(i.startswith("pytest") for i in issues)
