"""卡片與模型載入模組 (Patrol Cards & Watchdog)。

負責動態發現 models/ 下的標的、讀取卡片 YAML/JSONL 規格與時效性監控。
"""

import datetime
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_yaml_simple(path: Path) -> Dict[str, Any]:
    """YAML 讀取器：優先使用 PyYAML，備援簡易巢狀解析器。"""
    try:
        import yaml  # type: ignore

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except ImportError:
        pass

    content = path.read_text(encoding="utf-8")
    result: Dict[str, Any] = {}
    current_section: Optional[Dict[str, Any]] = None

    for line in content.splitlines():
        if "#" in line:
            line = line.split("#", 1)[0]
        stripped = line.strip()
        if not stripped:
            continue

        indent = len(line) - len(line.lstrip())
        if ":" in stripped:
            k, v = stripped.split(":", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")

            parsed_v: Any = v
            if v.isdigit():
                parsed_v = int(v)
            elif re.match(r"^-?\d+\.\d+$", v):
                parsed_v = float(v)
            elif v.lower() in ("true", "false"):
                parsed_v = v.lower() == "true"
            elif v == "":
                parsed_v = {}

            if indent == 0:
                if isinstance(parsed_v, dict):
                    result[k] = {}
                    current_section = result[k]
                else:
                    result[k] = parsed_v
                    current_section = None
            else:
                if current_section is not None:
                    current_section[k] = parsed_v
                else:
                    result[k] = parsed_v

    return result


def discover_tickers(models_root: Path, filter_tickers: Optional[List[str]] = None) -> List[str]:
    """動態掃描 models/*/ 目錄，獲取包含 cards/ 或 ticker.yml 的標的列表。"""
    tickers = []
    if not models_root.exists():
        return tickers

    for entry in sorted(models_root.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            cards_dir = entry / "cards"
            if (cards_dir / "ticker.yml").exists() or cards_dir.exists():
                if not filter_tickers or entry.name in filter_tickers:
                    tickers.append(entry.name)
    return tickers


def load_cards(models_root: Path, ticker: str) -> Dict[str, Any]:
    """載入特定標的之卡片集（ticker.yml, loop_*.yml, interlock_*.yml, constituents.jsonl）。"""
    model_dir = models_root / ticker
    cards_dir = model_dir / "cards"
    profile_dir = model_dir / "profile"

    data: Dict[str, Any] = {
        "ticker_id": ticker,
        "ticker": {},
        "loops": [],
        "interlocks": [],
        "constituents": [],
        "sources": load_yaml_simple(profile_dir / "sources.yml") if (profile_dir / "sources.yml").exists() else {},
        "files_mtime": {},
    }

    if not cards_dir.exists():
        return data

    for f in sorted(cards_dir.iterdir()):
        if f.is_file():
            data["files_mtime"][f.name] = datetime.datetime.fromtimestamp(
                f.stat().st_mtime, tz=datetime.timezone.utc
            ).strftime("%Y-%m-%d")

        if f.name == "ticker.yml":
            data["ticker"] = load_yaml_simple(f)
        elif f.name.startswith("loop_") and f.suffix in (".yml", ".yaml"):
            data["loops"].append(load_yaml_simple(f))
        elif f.name.startswith("interlock_") and f.suffix in (".yml", ".yaml"):
            data["interlocks"].append(load_yaml_simple(f))
        elif f.name == "constituents.jsonl":
            try:
                with open(f, "r", encoding="utf-8") as jf:
                    for line in jf:
                        line = line.strip()
                        if line:
                            data["constituents"].append(json.loads(line))
            except Exception:
                pass

    return data


def check_watchdog(cards_data: Dict[str, Any], max_stale_days: int = 5) -> Dict[str, Any]:
    """數據心跳檢查（Watchdog）：檢查標的卡片與成分股資料庫之更新時效性。"""
    files_mtime = cards_data.get("files_mtime", {})
    ticker_info = cards_data.get("ticker", {})
    fail_safe = ticker_info.get("fail_safe", {})
    try:
        stale_limit = int(fail_safe.get("max_stale_days", max_stale_days))
    except Exception:
        stale_limit = max_stale_days

    today = datetime.date.today()
    most_recent_date: Optional[datetime.date] = None

    for _, mtime_str in files_mtime.items():
        try:
            m_date = datetime.date.fromisoformat(mtime_str)
            if most_recent_date is None or m_date > most_recent_date:
                most_recent_date = m_date
        except Exception:
            continue

    if most_recent_date is None:
        return {
            "status": "UNKNOWN",
            "is_stale": False,
            "label": "無時間戳記",
            "days_ago": 0,
        }

    days_ago = (today - most_recent_date).days
    is_stale = days_ago > stale_limit

    if is_stale:
        return {
            "status": "STALE",
            "is_stale": True,
            "label": f"⚠️ 過期 ({most_recent_date.isoformat()}, {days_ago}日前)",
            "days_ago": days_ago,
        }
    return {
        "status": "HEALTHY",
        "is_stale": False,
        "label": f"✅ 正常 ({most_recent_date.isoformat()})",
        "days_ago": days_ago,
    }
