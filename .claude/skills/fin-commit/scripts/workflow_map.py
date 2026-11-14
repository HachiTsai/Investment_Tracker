#!/usr/bin/env python3
"""工作流對應地圖產生器：讀 repo 現況，輸出單檔 HTML（供 Claude 雲端排程發布成 Artifact）。

規格：.claude/workflows/workflow-map.md（SSOT）。只用標準函式庫，只讀 repo 內檔案，不連網。

資料分兩層：
- 即時層（每次從 repo 讀）：排程登記表的觸發時間與待驗證清單、.github/workflows 的 cron、
  .claude/skills 與 .claude/workflows 的檔案清單、各規格檔提到的技能名稱。
- 策展層（references/workflow-map-data.json）：每個工作流讀寫什麼、產出什麼、序列圖，
  這些 repo 裡沒有結構化來源，由人維護；新工作流或新技能出現時，本腳本回報「地圖尚未涵蓋」。

用法：
    python3 .claude/skills/fin-commit/scripts/workflow_map.py build OUT.html [--factory FACTORY.html] [--strict]
輸出（stdout）：JSON，含 out、sha、wf_count、drift（地圖與 repo 不一致的項目）。
--strict：drift 非空時退出碼 1。
"""
import argparse
import datetime
import html
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
REF = Path(__file__).resolve().parents[1] / "references"
SKILL_FALLBACK_LABEL = "（未命名）"


# ---------- 即時層：解析 repo ----------

def parse_registry(text):
    """回傳 (rows, pending)。rows 為 {id, trigger}；pending 為第 3 節待驗證的條列文字。"""
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and re.fullmatch(r"[SC]\d+|CI", cells[0]):
            rows.append({"id": cells[0], "trigger": cells[3], "platform": cells[2]})
    pending = []
    m = re.search(r"^## 3\.[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    if m:
        for line in m.group(1).splitlines():
            if line.startswith("- "):
                pending.append(line[2:].strip())
    return rows, pending


_DAYS = {"日": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}


def parse_trigger(text):
    """把登記表的觸發欄轉成 (when, dow, time)；看不懂回 None。"""
    m = re.search(r"每月\s*(\d+)\s*日\s*(\d{2}:\d{2})", text)
    if m:
        return f"每月 {m.group(1)} 日 {m.group(2)}", [], "月"
    m = re.search(r"週([一二三四五六日])至週([一二三四五六日])\s*(\d{2}:\d{2})", text)
    if m:
        a, z, hhmm = _DAYS[m.group(1)], _DAYS[m.group(2)], m.group(3)
        days = []
        d = a
        while True:
            days.append(d)
            if d == z:
                break
            d = (d + 1) % 7
        return f"週{m.group(1)}至週{m.group(2)} {hhmm}", days, hhmm
    m = re.search(r"(每日|平日|週[一二三四五六日])\s*(\d{2}:\d{2})", text)
    if not m:
        return None
    day, hhmm = m.groups()
    days = {"每日": [1, 2, 3, 4, 5, 6, 0], "平日": [1, 2, 3, 4, 5]}.get(day) or [_DAYS[day[1]]]
    return f"{day} {hhmm}", days, hhmm


def scan_yml(root):
    """回傳 {檔名: [cron...]}（只列有 schedule 的）。"""
    out = {}
    for p in sorted((root / ".github" / "workflows").glob("*.yml")):
        crons = re.findall(r"""-\s*cron:\s*["']([^"']+)["']""", p.read_text(encoding="utf-8"))
        if crons:
            out[p.name] = crons
    return out


def scan_skills(root):
    d = root / ".claude" / "skills"
    return sorted(p.parent.name for p in d.glob("*/SKILL.md"))


def scan_specs(root):
    d = root / ".claude" / "workflows"
    return sorted(p.name for p in d.glob("*.md") if p.name != "schedule-registry.md")


def git_sha(root):
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True,
                              text=True, timeout=10).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


# ---------- 合併與比對 ----------

def merge(data, root):
    """回傳 (wf, skills, pending, drift)。不改動傳入的 data。"""
    drift = []
    wf = json.loads(json.dumps(data["WF"]))
    skills = dict(data["SKILLS"])
    reg_path = root / ".claude" / "workflows" / "schedule-registry.md"
    rows, pending_raw = parse_registry(reg_path.read_text(encoding="utf-8"))
    by_id = {w["id"]: w for w in wf}

    for r in rows:
        w = by_id.get(r["id"])
        if not w:
            drift.append(f"登記表有 {r['id']}，地圖資料沒有這個工作流")
            continue
        parsed = parse_trigger(r["trigger"])
        if parsed:
            w["when"], w["dow"], w["time"] = parsed
        else:
            drift.append(f"{r['id']} 的觸發欄「{r['trigger']}」解析不出時間，沿用地圖資料的時間")
    reg_ids = {r["id"] for r in rows}
    for w in wf:
        if w["plat"] != "man" and w["id"] not in reg_ids:
            drift.append(f"地圖有 {w['id']}，登記表沒有（可能已停用或改名）")

    known_specs = {Path(w["spec"]).name for w in wf if w.get("spec", "").startswith(".claude/workflows/")}
    for name in scan_specs(root):
        if name not in known_specs:
            drift.append(f"工作流規格 {name} 還沒出現在地圖")
    for w in wf:
        spec = w.get("spec", "")
        if spec.startswith(".claude/workflows/") and not (root / spec).exists():
            drift.append(f"{w['id']} 的規格檔 {spec} 已不存在")

    known_yml = {Path(w["yml"]).name for w in wf if w.get("yml", "").endswith(".yml")}
    crons = scan_yml(root)
    for w in wf:
        yml = Path(w.get("yml", "")).name
        if yml in crons:
            w["trigger"] = [re.sub(r"(cron <code>)[^<]*(</code>)", lambda m: m.group(1) + crons[yml][0] + m.group(2), t)
                            for t in w["trigger"]]
    for name in scan_yml(root):
        if name not in known_yml:
            drift.append(f"workflow {name} 有排程，地圖沒有對應項目")

    for s in scan_skills(root):
        if s not in skills:
            skills[s] = SKILL_FALLBACK_LABEL
            drift.append(f"技能 {s} 還沒出現在地圖")
    for s in list(skills):
        if s not in scan_skills(root):
            drift.append(f"地圖列有技能 {s}，repo 已找不到")

    for w in wf:
        spec = root / w.get("spec", "")
        if not spec.is_file() or spec.name == "schedule-registry.md" or w["plat"] == "man" and w["id"] == "H0":
            continue
        text = spec.read_text(encoding="utf-8")
        listed = {s[0] for s in w["skills"]}
        for s in skills:
            if s in text and s not in listed:
                drift.append(f"{w['id']} 規格提到技能 {s}，地圖沒列")

        # 規格寫了外部觸發（Apps Script），觸發欄也要列，否則工廠與地圖看不到這條路徑
        if "Apps Script" in text and not any("Apps Script" in x for x in w["trigger"]):
            drift.append(f"{w['id']} 規格提到 Apps Script 外部觸發，地圖的觸發欄沒列")

    pending = []
    for line in pending_raw:
        title = re.split(r"[，；。,;]", line, maxsplit=1)[0][:28]
        body = html.escape(line)
        body = re.sub(r"`([^`]+)`", r"<code>\1</code>", body)
        pending.append([html.escape(title), body])
    return wf, skills, pending, drift


# ---------- 輸出 ----------

def _js(obj):
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def render(template, wf, skills, pending, seqs, foot):
    by_id = {w["id"]: w for w in wf}
    blocks = []
    for s in seqs:
        title = s["title"]
        w = by_id.get(s["id"])
        if w:
            title = re.sub(r"（[^（）]*）$", "", title) + f"（{w['when']}）"
        blocks.append(f'  <div class="dg" id="seq-{html.escape(s["id"])}"><h3>{html.escape(title)}</h3>\n'
                      f'<pre class="seqsrc" hidden>\n{html.escape(s["src"], quote=False)}</pre></div>')
    data_js = (f"const SKILLS={_js(skills)};\nconst WF={_js(wf)};\nconst PENDING={_js(pending)};\n")
    out = template.replace("/*@@DATA@@*/", data_js).replace("<!--@@SEQ@@-->", "\n".join(blocks))
    return out.replace("@@FOOT@@", foot)


def build_factory(data, wf, skills, template, foot_note=""):
    """由策展資料與合併後的 wf 產生「工作流工廠」模擬頁（單檔 HTML）。"""
    f = data["FACTORY"]
    sk_names = [k[0] for k in f["SK"]]
    out_names = [o[0] for o in f["OUT"]]
    by_id = {w["id"]: w for w in wf}
    rows = []
    for rid in f["ROWS"]:
        ov = f["OVR"].get(rid, {})
        w = by_id.get(rid)
        base = w or by_id.get(ov.get("when_from", ""), {})
        plat = ov.get("plat") or (w or {}).get("plat", "man")
        name = ov.get("name") or (w or {}).get("name", rid)
        if "when" in ov:
            when = ov["when"]
        elif "when_from" in ov:
            when = base.get("when", "")
        else:
            when = (w or {}).get("when", "")
        if "skills" in ov:
            main, also = ov["skills"], ov.get("also", [])
        else:
            main = [s[0] for s in (w or {}).get("skills", []) if s[1]]
            also = [s[0] for s in (w or {}).get("skills", []) if not s[1]]
        for n in main + also:
            if n not in sk_names:
                raise ValueError(f"工廠頁沒有技能 {n}")
        outs = f["OUTS"].get(rid, [])
        for n in outs:
            if n not in out_names:
                raise ValueError(f"工廠頁沒有產出 {n}")
        rows.append([rid, plat, name, when, [sk_names.index(n) for n in main],
                     [sk_names.index(n) for n in also], [out_names.index(n) for n in outs], ov.get("cap", "")])
    sk = [[k[0], k[1], skills.get(k[0], SKILL_FALLBACK_LABEL)] for k in f["SK"]]
    js = f"var SK={_js(sk)};\nvar O={_js(f['OUT'])};\nvar W={_js(rows)};"
    return template.replace("/*@@FDATA@@*/", js)


def build(root, out_path, factory_path=None):
    data = json.loads((REF / "workflow-map-data.json").read_text(encoding="utf-8"))
    template = (REF / "workflow-map-template.html").read_text(encoding="utf-8")
    wf, skills, pending, drift = merge(data, root)
    sha = git_sha(root)
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    foot = (f"資料來源：排程登記表、工作流規格與 workflow yml，依 repo {sha} 於 {now}（台北）自動產生。"
            "圖中不含任何金鑰；Secrets 只列名稱。")
    if drift:
        foot += " 地圖與 repo 有 " + str(len(drift)) + " 處不一致：" + "；".join(html.escape(d) for d in drift[:6])
        if len(drift) > 6:
            foot += "…"
    page = render(template, wf, skills, pending, data["SEQ"], foot)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(page, encoding="utf-8")
    res = {"out": str(out_path), "sha": sha, "wf_count": len(wf), "drift": drift}
    if factory_path:
        tpl = (REF / "workflow-factory-template.html").read_text(encoding="utf-8")
        fpage = build_factory(data, wf, skills, tpl)
        Path(factory_path).parent.mkdir(parents=True, exist_ok=True)
        Path(factory_path).write_text(fpage, encoding="utf-8")
        res["factory_out"] = str(factory_path)
        res["factory_rows"] = len(data["FACTORY"]["ROWS"])
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="產生地圖 HTML")
    b.add_argument("out")
    b.add_argument("--factory", help="另外輸出工作流工廠模擬頁的路徑")
    b.add_argument("--strict", action="store_true", help="地圖與 repo 不一致時退出碼 1")
    a = ap.parse_args(argv)
    res = build(ROOT, a.out, a.factory)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 1 if (a.strict and res["drift"]) else 0


if __name__ == "__main__":
    sys.exit(main())
