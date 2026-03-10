from __future__ import annotations

from typing import Any

import pandas as pd

from .base import BaseAdapter
from .celesc_adapter import CelescAdapter
from .cpfl_adapter import CpflAdapter
from .enel_adapter import EnelAdapter
from .config_adapter import ConfigDrivenAdapter
from .config_loader import (
    AdapterConfig,
    load_all_adapter_configs,
    save_adapter_config,
)


# Legacy Python adapters (take priority over YAML configs with same name)
_PYTHON_ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    "celesc": CelescAdapter,
    "enel": EnelAdapter,
    "cpfl": CpflAdapter,
}


def _build_merged_registry() -> dict[str, BaseAdapter | type[BaseAdapter]]:
    """Build registry merging YAML config adapters with Python class adapters.

    Python adapters override YAML configs when names collide.
    """
    registry: dict[str, BaseAdapter | type[BaseAdapter]] = {}

    # Load YAML-driven adapters first
    for name, config in load_all_adapter_configs().items():
        registry[name] = ConfigDrivenAdapter(config)

    # Python class adapters override YAML
    registry.update(_PYTHON_ADAPTER_REGISTRY)
    return registry


ADAPTER_REGISTRY = _build_merged_registry()


def reload_registry() -> None:
    """Reload the adapter registry (e.g. after saving a new YAML config)."""
    global ADAPTER_REGISTRY
    ADAPTER_REGISTRY = _build_merged_registry()


def list_adapters() -> list[str]:
    return sorted(ADAPTER_REGISTRY.keys())


def get_adapter(name: str) -> BaseAdapter:
    key = str(name or "").strip().lower()
    entry = ADAPTER_REGISTRY.get(key)
    if entry is None:
        supported = ", ".join(list_adapters())
        raise ValueError(f"Unsupported adapter '{name}'. Supported: {supported}")
    # Python class adapters need instantiation; ConfigDrivenAdapter instances are ready
    if isinstance(entry, type):
        return entry()
    return entry


def _score_text(text: str, keyword: str) -> float:
    value = str(text or "").lower()
    return 1.0 if keyword in value else 0.0


def detect_adapter(df: pd.DataFrame, outputs_info: dict | None = None) -> dict[str, Any]:
    adapter_names = list_adapters()
    if df is None or df.empty:
        return {
            "adapter": None,
            "is_confident": False,
            "confidence": 0.0,
            "reason": "DataFrame vazio",
            "scores": {name: 0.0 for name in adapter_names},
        }

    scores = {name: 0.0 for name in adapter_names}
    columns = [str(col).lower() for col in df.columns]
    columns_set = set(columns)
    text_columns = [col for col in ["origem", "source_file", "pdf_source", "fornecedor", "distribuidora"] if col in df.columns]

    # Score each adapter using its detection hints (from YAML config or defaults)
    for name in adapter_names:
        entry = ADAPTER_REGISTRY.get(name)
        config: AdapterConfig | None = None
        if isinstance(entry, ConfigDrivenAdapter):
            config = entry.config

        # Check column signature (boost if all signature columns present)
        if config and config.detection_hints.column_signature:
            signature = {s.lower() for s in config.detection_hints.column_signature}
            if signature.issubset(columns_set):
                scores[name] += config.detection_hints.signature_score_boost
        elif name == "celesc":
            # Legacy fallback for Python adapter
            if {"uc", "referencia", "kwh_total_te", "categoria"}.issubset(columns_set):
                scores[name] += 1.5

        # Score column name keyword matches
        joined_cols = " | ".join(columns)
        if config and config.detection_hints.column_keywords:
            for kw in config.detection_hints.column_keywords:
                scores[name] += _score_text(joined_cols, kw.lower()) * 1.5
        else:
            scores[name] += _score_text(joined_cols, name) * 1.5

        # Score content keyword matches
        for col in text_columns:
            sample = " | ".join(df[col].astype(str).head(300).tolist()).lower()
            if config and config.detection_hints.content_keywords:
                for kw in config.detection_hints.content_keywords:
                    scores[name] += _score_text(sample, kw.lower()) * 2.0
            else:
                scores[name] += _score_text(sample, name) * 2.0

    # Output filename hints
    if outputs_info:
        candidates = outputs_info.get("all_candidates") or []
        joined_candidates = " | ".join(str(item).lower() for item in candidates)
        for name in adapter_names:
            entry = ADAPTER_REGISTRY.get(name)
            config = entry.config if isinstance(entry, ConfigDrivenAdapter) else None
            keywords = config.detection_hints.content_keywords if config else [name]
            for kw in keywords:
                scores[name] += _score_text(joined_candidates, kw.lower()) * 1.0

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_name, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    gap = best_score - second_score
    is_confident = best_score >= 2.0 and gap >= 0.5

    reason = (
        f"Detectado por heuristica: score={best_score:.2f}, gap={gap:.2f}"
        if is_confident
        else "Heuristica sem confianca suficiente"
    )
    return {
        "adapter": best_name if is_confident else None,
        "is_confident": is_confident,
        "confidence": float(best_score),
        "reason": reason,
        "scores": scores,
    }


__all__ = [
    "BaseAdapter",
    "ConfigDrivenAdapter",
    "AdapterConfig",
    "get_adapter",
    "list_adapters",
    "detect_adapter",
    "reload_registry",
    "save_adapter_config",
    "load_all_adapter_configs",
]
