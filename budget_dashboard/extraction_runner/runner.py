from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from budget.contract_schema import CONTRACT_SCHEMA_VERSION, REQUIRED_CONTRACT_COLUMNS
from config import MAX_EXTRACTION_LOG_FILES


def _normalize_cmd(cmd: str | Iterable[str]) -> list[str]:
    if isinstance(cmd, str):
        stripped = cmd.strip()
        if not stripped:
            raise ValueError("cmd cannot be empty")
        return shlex.split(stripped, posix=False)

    normalized = [str(part).strip() for part in cmd if str(part).strip()]
    if not normalized:
        raise ValueError("cmd cannot be empty")
    return normalized


def _slugify(value: str, fallback: str = "na") -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or fallback


def build_run_id(
    municipio: str,
    adapter: str,
    timestamp: datetime | None = None,
) -> str:
    ts = (timestamp or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
    return f"{ts}_{_slugify(municipio)}_{_slugify(adapter)}"


def _resolve_log_path(
    log_path: str | Path | None,
    log_dir: str | Path | None,
    run_id: str | None,
) -> Path | None:
    if log_path is not None:
        path = Path(log_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    if log_dir is None:
        return None

    folder = Path(log_dir).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    stem = run_id or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return folder / f"{stem}_extractor.log"


def _write_log_file(log_file: Path, payload: dict) -> None:
    lines = [
        "=== EXTRACTOR CLI RUN ===",
        f"started_at: {payload.get('started_at')}",
        f"ended_at: {payload.get('ended_at')}",
        f"duration_sec: {payload.get('duration_sec')}",
        f"workdir: {payload.get('workdir')}",
        f"command: {' '.join(payload.get('command', []))}",
        f"returncode: {payload.get('returncode')}",
        f"success: {payload.get('success')}",
        f"timed_out: {payload.get('timed_out')}",
        "",
        "=== STDOUT ===",
        payload.get("stdout", "") or "",
        "",
        "=== STDERR ===",
        payload.get("stderr", "") or "",
        "",
    ]
    log_file.write_text("\n".join(lines), encoding="utf-8")


def _rotate_log_files(log_dir: Path, keep: int = MAX_EXTRACTION_LOG_FILES) -> None:
    """Delete oldest log files when the folder exceeds `keep` entries."""
    log_files = sorted(
        (f for f in log_dir.iterdir() if f.is_file() and f.suffix == ".log"),
        key=lambda f: f.stat().st_mtime,
    )
    for old_file in log_files[:-keep] if len(log_files) > keep else []:
        try:
            old_file.unlink()
        except OSError:
            pass


def tail_log_lines(log_path: str | Path, max_lines: int = 200) -> str:
    path = Path(log_path).expanduser().resolve()
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-int(max_lines) :])


def run_extractor_cli(
    cmd: str | Iterable[str],
    workdir: str | Path,
    timeout_sec: int = 3600,
    log_path: str | Path | None = None,
    log_dir: str | Path | None = None,
    run_id: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict:
    """Run extraction CLI as a black-box command and capture full logs."""
    command = _normalize_cmd(cmd)
    cwd = Path(workdir).expanduser().resolve()
    if not cwd.exists():
        raise FileNotFoundError(f"workdir not found: {cwd}")

    started_at = datetime.now()
    t0 = time.time()
    result_payload = {
        "command": command,
        "workdir": str(cwd),
        "started_at": started_at.isoformat(),
        "ended_at": None,
        "duration_sec": None,
        "returncode": None,
        "success": False,
        "timed_out": False,
        "stdout": "",
        "stderr": "",
        "combined_log": "",
        "log_path": None,
    }

    env = os.environ.copy()
    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items()})

    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=int(timeout_sec),
            shell=False,
            check=False,
            env=env,
        )
        result_payload["returncode"] = int(completed.returncode)
        result_payload["stdout"] = completed.stdout or ""
        result_payload["stderr"] = completed.stderr or ""
        result_payload["success"] = completed.returncode == 0
    except subprocess.TimeoutExpired as exc:
        result_payload["timed_out"] = True
        result_payload["stderr"] = f"Command timed out after {timeout_sec}s: {exc}"
    except Exception as exc:
        result_payload["stderr"] = str(exc)
    finally:
        ended_at = datetime.now()
        result_payload["ended_at"] = ended_at.isoformat()
        result_payload["duration_sec"] = round(time.time() - t0, 3)
        stdout = result_payload["stdout"].strip()
        stderr = result_payload["stderr"].strip()
        if stdout and stderr:
            result_payload["combined_log"] = f"{stdout}\n\n{stderr}"
        elif stdout:
            result_payload["combined_log"] = stdout
        else:
            result_payload["combined_log"] = stderr

        final_log_path = _resolve_log_path(log_path=log_path, log_dir=log_dir, run_id=run_id)
        if final_log_path is not None:
            _write_log_file(final_log_path, result_payload)
            result_payload["log_path"] = str(final_log_path)
            _rotate_log_files(final_log_path.parent)

    return result_payload


def _sorted_unique_files(paths: list[Path]) -> list[Path]:
    unique_map: dict[str, Path] = {}
    for path in paths:
        if path.is_file():
            unique_map[str(path.resolve())] = path.resolve()
    return sorted(
        unique_map.values(),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def find_outputs(output_dir: str | Path) -> dict:
    """
    Locate stable extractor outputs (master.csv / outputs.xlsx) in a folder tree.
    """
    root = Path(output_dir).expanduser().resolve()
    payload = {
        "output_dir": str(root),
        "exists": root.exists(),
        "master_csv": None,
        "outputs_xlsx": None,
        "all_candidates": [],
        "preferred_contract": None,
    }
    if not root.exists():
        return payload

    csv_patterns = [
        "**/master.csv",
        "**/*_master.csv",
        "**/*master*.csv",
        "**/*filtered_flat*.csv",
        "**/*dimensionamento*.csv",
    ]
    xlsx_patterns = [
        "**/outputs.xlsx",
        "**/output.xlsx",
        "**/*master*.xlsx",
        "**/*filtered_flat*.xlsx",
        "**/*dimensionamento*.xlsx",
    ]

    csv_candidates: list[Path] = []
    for pattern in csv_patterns:
        csv_candidates.extend(root.glob(pattern))
    xlsx_candidates: list[Path] = []
    for pattern in xlsx_patterns:
        xlsx_candidates.extend(root.glob(pattern))

    csv_sorted = _sorted_unique_files(csv_candidates)
    xlsx_sorted = _sorted_unique_files(xlsx_candidates)
    all_candidates = _sorted_unique_files(csv_sorted + xlsx_sorted)

    payload["master_csv"] = str(csv_sorted[0]) if csv_sorted else None
    payload["outputs_xlsx"] = str(xlsx_sorted[0]) if xlsx_sorted else None
    payload["all_candidates"] = [str(path) for path in all_candidates]
    payload["preferred_contract"] = payload["master_csv"] or payload["outputs_xlsx"]
    return payload


def contract_meta_path(contract_path: str | Path) -> Path:
    path = Path(contract_path).expanduser().resolve()
    return path.with_name(f"{path.stem}.meta.json")


def _read_contract_preview(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, encoding="utf-8-sig")
    if suffix in {".xlsx", ".xls"}:
        workbook = pd.ExcelFile(path)
        target_sheet = "displayed_data" if "displayed_data" in workbook.sheet_names else workbook.sheet_names[0]
        return pd.read_excel(workbook, sheet_name=target_sheet)
    raise ValueError(f"Unsupported contract format: {suffix}")


def _month_count(df: pd.DataFrame) -> int:
    reference_col = None
    for candidate in ["referencia", "reference_date", "data_referencia"]:
        if candidate in df.columns:
            reference_col = candidate
            break
    if reference_col is None:
        return 0
    return int(df[reference_col].astype(str).str.strip().replace("", pd.NA).dropna().nunique())


def _uc_count(df: pd.DataFrame) -> int:
    if "uc" in df.columns:
        return int(df["uc"].astype(str).str.strip().replace("", pd.NA).dropna().nunique())
    return 0


def build_contract_metadata(
    contract_path: str | Path,
    source_master_path: str | Path,
    run_id: str = "",
    adapter: str = "",
    required_columns: list[str] | None = None,
    schema_version: str = CONTRACT_SCHEMA_VERSION,
    generated_at: datetime | None = None,
) -> dict:
    contract_file = Path(contract_path).expanduser().resolve()
    source_file = Path(source_master_path).expanduser().resolve()
    df = _read_contract_preview(contract_file)
    required = list(required_columns or REQUIRED_CONTRACT_COLUMNS)
    actual = [str(col) for col in df.columns]
    missing = [col for col in required if col not in actual]

    return {
        "schema_version": schema_version,
        "generated_at": (generated_at or datetime.now()).isoformat(),
        "run_id": run_id or "",
        "adapter": adapter or "",
        "source_master_path": str(source_file),
        "required_columns": required,
        "actual_columns": actual,
        "missing_columns": missing,
        "row_count": int(len(df)),
        "uc_count": _uc_count(df),
        "months_count": _month_count(df),
    }


def write_contract_metadata(meta_path: str | Path, metadata: dict) -> str:
    path = Path(meta_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def load_contract_metadata(meta_path: str | Path) -> dict | None:
    path = Path(meta_path).expanduser().resolve()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def copy_contract_file(
    source_file: str | Path,
    target_file: str | Path,
    run_id: str = "",
    adapter: str = "",
    required_columns: list[str] | None = None,
    schema_version: str = CONTRACT_SCHEMA_VERSION,
    generated_at: datetime | None = None,
) -> dict:
    source = Path(source_file).expanduser().resolve()
    target = Path(target_file).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Source contract file not found: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)

    metadata = build_contract_metadata(
        contract_path=target,
        source_master_path=source,
        run_id=run_id,
        adapter=adapter,
        required_columns=required_columns,
        schema_version=schema_version,
        generated_at=generated_at,
    )
    meta_path = contract_meta_path(target)
    write_contract_metadata(meta_path, metadata)
    return {
        "contract_path": str(target),
        "meta_path": str(meta_path),
        "metadata": metadata,
    }


def ensure_contract_master(
    output_dir: str | Path,
    contract_master_path: str | Path,
    run_id: str = "",
    adapter: str = "",
    required_columns: list[str] | None = None,
    schema_version: str = CONTRACT_SCHEMA_VERSION,
) -> dict:
    found = find_outputs(output_dir)
    source = found.get("preferred_contract")
    if not source:
        raise FileNotFoundError(
            f"No output contract candidate found under {Path(output_dir).expanduser().resolve()}"
        )
    copied = copy_contract_file(
        source_file=source,
        target_file=contract_master_path,
        run_id=run_id,
        adapter=adapter,
        required_columns=required_columns,
        schema_version=schema_version,
    )
    return {
        "source_contract": source,
        "contract_master_path": copied["contract_path"],
        "contract_meta_path": copied["meta_path"],
        "contract_meta": copied["metadata"],
        "found_outputs": found,
    }


def _parse_run_id(run_id: str) -> tuple[str, str]:
    parts = str(run_id).split("_")
    if len(parts) >= 4:
        municipio = "_".join(parts[2:-1])
        adapter = parts[-1]
        return municipio, adapter
    return "", ""


def scan_run_history(outputs_root: str | Path, limit: int = 300) -> list[dict]:
    root = Path(outputs_root).expanduser().resolve()
    if not root.exists():
        return []

    reserved = {"contract", "logs"}
    run_dirs = [path for path in root.iterdir() if path.is_dir() and path.name not in reserved]
    run_dirs = sorted(run_dirs, key=lambda item: item.stat().st_mtime, reverse=True)[: int(limit)]

    rows: list[dict] = []
    for run_dir in run_dirs:
        run_id = run_dir.name
        contract_path = run_dir / "contract_master.csv"
        meta_path = run_dir / "contract_master.meta.json"
        meta = load_contract_metadata(meta_path)

        municipio_fallback, adapter_fallback = _parse_run_id(run_id)
        status = "ok" if contract_path.exists() else "missing_contract"
        row_count = None
        generated_at = None
        adapter = adapter_fallback
        municipio = municipio_fallback

        if meta:
            generated_at = meta.get("generated_at")
            adapter = meta.get("adapter") or adapter
            row_count = meta.get("row_count")
            status = "ok" if not meta.get("missing_columns") else "schema_warning"
        elif contract_path.exists():
            status = "meta_missing"

        rows.append(
            {
                "run_id": run_id,
                "timestamp": generated_at or datetime.fromtimestamp(run_dir.stat().st_mtime).isoformat(),
                "municipio": municipio,
                "adapter": adapter,
                "status": status,
                "row_count": row_count,
                "contract_path": str(contract_path) if contract_path.exists() else "",
                "meta_path": str(meta_path) if meta_path.exists() else "",
            }
        )

    return rows
