"""workflow_map.py：解析登記表觸發欄、合併 repo 現況、輸出完整頁面。只讀 repo，不連網。"""
import importlib.util
import json
import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "workflow_map.py"
spec = importlib.util.spec_from_file_location("workflow_map", SCRIPT)
wm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wm)


@pytest.mark.parametrize("text,when,dow,time", [
    ("每日 08:50", "每日 08:50", [1, 2, 3, 4, 5, 6, 0], "08:50"),
    ("平日 17:23", "平日 17:23", [1, 2, 3, 4, 5], "17:23"),
    ("週五 16:30", "週五 16:30", [5], "16:30"),
    ("週二至週六 08:50", "週二至週六 08:50", [2, 3, 4, 5, 6], "08:50"),
    ("週六至週二 08:50", "週六至週二 08:50", [6, 0, 1, 2], "08:50"),
    ("每月 23 日 09:30", "每月 23 日 09:30", [], "月"),
])
def test_parse_trigger(text, when, dow, time):
    assert wm.parse_trigger(text) == (when, dow, time)


def test_parse_trigger_unknown():
    assert wm.parse_trigger("開新工作階段") is None


def test_parse_registry_rows_and_pending():
    text = ("| ID | a | b | c | d |\n| S1 | x | GitHub Actions | 平日 17:00 | `s.md` |\n"
            "| C1 | x | Claude | 每日 08:50 | `c.md` |\n\n## 3. 待驗證\n\n- 第一項，說明\n- 第二項\n\n## 4. 異動\n- 不算\n")
    rows, pending = wm.parse_registry(text)
    assert [r["id"] for r in rows] == ["S1", "C1"]
    assert pending == ["第一項，說明", "第二項"]


def test_build_real_repo(tmp_path):
    out = tmp_path / "map.html"
    res = wm.build(wm.ROOT, out)
    page = out.read_text(encoding="utf-8")
    assert "@@" not in page, "模板標記沒有被取代"
    data = json.loads((wm.REF / "workflow-map-data.json").read_text(encoding="utf-8"))
    assert res["wf_count"] == len(data["WF"]) >= 9
    for w in data["WF"]:
        assert f'id:"{w["id"]}"' in page or f'"id": "{w["id"]}"' in page
    assert len(re.findall(r'class="dg" id="seq-', page)) == len(data["SEQ"])
    assert isinstance(res["drift"], list)


def test_page_has_no_drive_ids():
    """資料檔與模板不放 Drive／試算表 ID（只留鍵名與 Artifact 網址）。"""
    for name in ("workflow-map-data.json", "workflow-map-template.html"):
        text = (wm.REF / name).read_text(encoding="utf-8")
        assert not re.search(r"\b1[A-Za-z0-9_-]{43}\b", text), f"{name} 含疑似 Drive ID"


def test_drift_detects_unmodeled_spec(tmp_path):
    root = tmp_path
    (root / ".claude/workflows").mkdir(parents=True)
    (root / ".claude/skills/new-skill").mkdir(parents=True)
    (root / ".claude/skills/new-skill/SKILL.md").write_text("x", encoding="utf-8")
    (root / ".github/workflows").mkdir(parents=True)
    (root / ".claude/workflows/schedule-registry.md").write_text(
        "| C9 | x | Claude | 平日 10:00 | `new.md` |\n", encoding="utf-8")
    (root / ".claude/workflows/new.md").write_text("# new", encoding="utf-8")
    data = {"SKILLS": {}, "WF": [], "SEQ": []}
    _, skills, _, drift = wm.merge(data, root)
    joined = "\n".join(drift)
    assert "C9" in joined and "new.md" in joined and "new-skill" in joined
    assert "new-skill" in skills
