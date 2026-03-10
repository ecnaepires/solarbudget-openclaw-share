from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


TOKEN_MUNICIPIO = "{municipio}"
TOKEN_PDFS = "{pdfs}"
TOKEN_MUNICIPIO_PREFIX = "{municipio_prefix}"


@dataclass(frozen=True)
class ExtractPreset:
    key: str
    label: str
    cmd: list[str]
    workdir: str
    description: str = ""
    requires_municipio: bool = False
    requires_pdfs: bool = False
    default_municipio: str = ""


def get_presets(default_workdir: str | Path) -> dict[str, ExtractPreset]:
    workdir = str(Path(default_workdir).expanduser().resolve())
    return {
        "run_full_study_default": ExtractPreset(
            key="run_full_study_default",
            label="Full Study (run_full_study.py)",
            cmd=[
                "python",
                "run_full_study.py",
                TOKEN_MUNICIPIO,
                TOKEN_PDFS,
                "--save-intermediate",
                "--save-dimensionamento-summary",
            ],
            workdir=workdir,
            description="Executa estudo completo do municipio e gera outputs de dimensionamento.",
            requires_municipio=True,
            requires_pdfs=True,
            default_municipio="Palhoca",
        ),
        "run_batch_municipio_default": ExtractPreset(
            key="run_batch_municipio_default",
            label="Batch Municipio (run_batch_municipio.py)",
            cmd=[
                "python",
                "run_batch_municipio.py",
                TOKEN_MUNICIPIO_PREFIX,
                TOKEN_PDFS,
            ],
            workdir=workdir,
            description="Extracao em lote para varios PDFs e gera arquivo master CSV/TSV.",
            requires_municipio=True,
            requires_pdfs=True,
            default_municipio="Palhoca",
        ),
    }


def resolve_preset_command(
    preset: ExtractPreset,
    municipio: str = "",
    pdf_paths: list[str] | None = None,
) -> list[str]:
    pdfs = [str(Path(path)) for path in (pdf_paths or []) if str(path).strip()]
    resolved: list[str] = []

    for part in preset.cmd:
        if part == TOKEN_MUNICIPIO or part == TOKEN_MUNICIPIO_PREFIX:
            value = municipio.strip() or preset.default_municipio.strip() or "MUNICIPIO"
            resolved.append(value)
            continue
        if part == TOKEN_PDFS:
            if pdfs:
                resolved.extend(pdfs)
            continue
        resolved.append(part)
    return resolved
