import csv
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple

from config import AUDIT_LOG_PATH, OUTPUTS_DIR


def ensure_output_dirs() -> None:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def _slugify(text: str) -> str:
    raw = text.strip().lower()
    raw = re.sub(r"[^a-z0-9]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    return raw or "project"


def build_output_paths(
    project_name: str,
    version_id: str,
    scenario_name: str,
    timestamp: datetime | None = None,
) -> Tuple[Path, Path, str]:
    ensure_output_dirs()
    ts = timestamp or datetime.now()
    stamp = ts.strftime("%Y%m%d_%H%M%S")
    stem = f"{_slugify(project_name)}_{_slugify(version_id)}_{_slugify(scenario_name)}_{stamp}"
    xlsx_path = OUTPUTS_DIR / f"{stem}.xlsx"
    json_path = OUTPUTS_DIR / f"{stem}.json"
    return xlsx_path, json_path, stamp


def save_snapshot(snapshot_path: Path, payload: Dict) -> None:
    with snapshot_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)


def append_audit_log(
    timestamp_iso: str,
    project_name: str,
    version_id: str,
    scenario_name: str,
    excel_path: Path,
    snapshot_path: Path,
) -> None:
    ensure_output_dirs()
    audit_exists = AUDIT_LOG_PATH.exists()
    username = os.getenv("USERNAME") or os.getenv("USER") or ""

    with AUDIT_LOG_PATH.open("a", encoding="utf-8", newline="") as file:
        fieldnames = [
            "timestamp",
            "user",
            "project",
            "version",
            "scenario_name",
            "excel_file",
            "snapshot_file",
        ]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        if not audit_exists:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": timestamp_iso,
                "user": username,
                "project": project_name,
                "version": version_id,
                "scenario_name": scenario_name,
                "excel_file": str(excel_path),
                "snapshot_file": str(snapshot_path),
            }
        )
