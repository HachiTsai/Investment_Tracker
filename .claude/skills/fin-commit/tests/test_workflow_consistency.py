"""排程規格一致性檢查：登記表、.github/workflows 的 cron、各 .claude/workflows/*.md 規格互相對得上。

每次 PR 的 CI 都會跑，任何一邊改了另一邊沒跟上就失敗（2026-11-06 Hachi 同意）。只讀 repo 內檔案，不連網。
檢查項目：
1. 登記表的 GitHub Actions 列：yml 存在、cron 與 yml 一致、台北時間由 cron 推得（UTC+8）。
2. 有 schedule 的 yml 都登記在表上。
3. 規格檔存在；規格檔「排程頻率」寫的時間與登記表一致。
4. 登記表第 2 節的雲端 prompt 與規格檔內的 prompt 逐字一致，且指向的規格檔存在。
5. 規格檔引用的 `.claude/skills/...` 腳本與 references 路徑都存在。
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
WF = ROOT / ".claude" / "workflows"
GHA = ROOT / ".github" / "workflows"
REGISTRY = WF / "schedule-registry.md"


def _rows():
    rows = []
    for line in REGISTRY.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and re.fullmatch(r"[SC]\d+|CI", cells[0]):
            rows.append(dict(id=cells[0], platform=cells[2], trigger=cells[3], spec=cells[4]))
    return rows


ROWS = _rows()
GHA_ROWS = [r for r in ROWS if "GitHub Actions" in r["platform"]]


def _yml_crons(path):
    return re.findall(r"""-\s*cron:\s*["']([^"']+)["']""", path.read_text(encoding="utf-8"))


def _taipei(cron):
    minute, hour = cron.split()[:2]
    return f"{(int(hour) + 8) % 24:02d}:{int(minute):02d}"


def _hhmm(text):
    return re.findall(r"\b(\d{2}:\d{2})\b", text)


def test_registry_has_rows():
    assert len(GHA_ROWS) >= 3 and any(r["id"].startswith("C") for r in ROWS)


@pytest.mark.parametrize("row", GHA_ROWS, ids=lambda r: r["id"])
def test_gha_row_matches_yml(row):
    yml = re.search(r"`([\w.-]+\.yml)`", row["platform"]).group(1)
    cron = re.search(r"cron `([^`]+)`", row["platform"]).group(1)
    path = GHA / yml
    assert path.exists(), f"{row['id']}：找不到 {yml}"
    assert cron in _yml_crons(path), f"{row['id']}：登記表 cron `{cron}` 與 {yml} 的 {_yml_crons(path)} 不一致"
    assert _taipei(cron) in _hhmm(row["trigger"]), f"{row['id']}：cron `{cron}` 是台北 {_taipei(cron)}，登記表寫「{row['trigger']}」"


def test_every_scheduled_yml_is_registered():
    registered = {re.search(r"`([\w.-]+\.yml)`", r["platform"]).group(1) for r in GHA_ROWS}
    for path in GHA.glob("*.yml"):
        if _yml_crons(path):
            assert path.name in registered, f"{path.name} 有 schedule 但不在 schedule-registry.md"


def _spec_files(row):
    return [WF / m for m in re.findall(r"`([\w.-]+\.md)`", row["spec"])]


@pytest.mark.parametrize("row", [r for r in ROWS if r["id"] != "CI"], ids=lambda r: r["id"])
def test_spec_exists_and_states_same_time(row):
    specs = _spec_files(row)
    assert specs, f"{row['id']}：規格欄沒有 .md 檔名"
    for spec in specs:
        assert spec.exists(), f"{row['id']}：找不到 {spec.name}"
        freq = [l for l in spec.read_text(encoding="utf-8").splitlines() if "排程頻率" in l]
        assert freq, f"{spec.name} 沒有「排程頻率」"
        want = _hhmm(row["trigger"])
        assert set(want) <= set(_hhmm(freq[0])), f"{spec.name} 的排程頻率「{freq[0].strip()}」與登記表 {row['id']}（{row['trigger']}）不一致"


def _prompts():
    text = REGISTRY.read_text(encoding="utf-8")
    return re.findall(r"^- ([SC]\d+)(?:（備用）)?：`([^`]+)`", text, flags=re.M)


def test_cloud_prompts_match_spec():
    prompts = _prompts()
    assert prompts
    for rid, prompt in prompts:
        name = re.search(r"\.claude/workflows/([\w.-]+\.md)", prompt).group(1)
        spec = WF / name
        assert spec.exists(), f"{rid}：prompt 指向的 {name} 不存在"
        assert prompt in spec.read_text(encoding="utf-8"), f"{rid}：登記表 prompt 與 {name} 內的 prompt 不一致"


@pytest.mark.parametrize("spec", sorted(WF.glob("*.md")), ids=lambda p: p.name)
def test_referenced_skill_paths_exist(spec):
    missing = []
    for ref in re.findall(r"(\.claude/skills/[\w./-]+\.(?:py|md|html|json))", spec.read_text(encoding="utf-8")):
        if not (ROOT / ref).exists():
            missing.append(ref)
    assert not missing, f"{spec.name} 引用了不存在的路徑：{missing}"
