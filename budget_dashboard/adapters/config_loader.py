from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


ADAPTER_CONFIGS_DIR = Path(__file__).parent / "adapter_configs"


@dataclass
class ColumnMapping:
    aliases: list[str]
    required: bool = False
    fallback: str | float | None = None
    fallback_mode: str | None = None  # "index", "today_first_of_month"
    parse_as: str | None = None  # "float"


@dataclass
class ClassRule:
    pattern: str | None = None
    value: str = "OUTROS"
    is_default: bool = False

    _compiled: re.Pattern | None = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self.pattern and not self.is_default:
            self._compiled = re.compile(self.pattern, re.IGNORECASE)

    def matches(self, text: str) -> bool:
        if self.is_default:
            return True
        if self._compiled is None:
            return False
        return bool(self._compiled.search(text))


@dataclass
class DetectionHints:
    column_keywords: list[str] = field(default_factory=list)
    content_keywords: list[str] = field(default_factory=list)
    column_signature: list[str] = field(default_factory=list)
    signature_score_boost: float = 1.5


@dataclass
class AdapterConfig:
    name: str
    description: str
    version: str = "1.0"
    column_mappings: dict[str, ColumnMapping] = field(default_factory=dict)
    consumer_class_rules: list[ClassRule] = field(default_factory=list)
    detection_hints: DetectionHints = field(default_factory=DetectionHints)


def _parse_column_mapping(raw: dict[str, Any]) -> ColumnMapping:
    return ColumnMapping(
        aliases=raw.get("aliases", []),
        required=bool(raw.get("required", False)),
        fallback=raw.get("fallback"),
        fallback_mode=raw.get("fallback_mode"),
        parse_as=raw.get("parse_as"),
    )


def _parse_class_rules(raw_list: list[dict[str, Any]]) -> list[ClassRule]:
    rules: list[ClassRule] = []
    for entry in raw_list:
        if "default" in entry:
            rules.append(ClassRule(value=str(entry["default"]), is_default=True))
        else:
            rules.append(ClassRule(
                pattern=entry.get("pattern"),
                value=entry.get("value", "OUTROS"),
            ))
    return rules


def _parse_detection_hints(raw: dict[str, Any]) -> DetectionHints:
    return DetectionHints(
        column_keywords=raw.get("column_keywords", []),
        content_keywords=raw.get("content_keywords", []),
        column_signature=raw.get("column_signature", []),
        signature_score_boost=float(raw.get("signature_score_boost", 1.5)),
    )


def parse_adapter_config(raw: dict[str, Any]) -> AdapterConfig:
    mappings = {}
    for field_name, mapping_raw in raw.get("column_mappings", {}).items():
        mappings[field_name] = _parse_column_mapping(mapping_raw)

    return AdapterConfig(
        name=raw["name"],
        description=raw.get("description", ""),
        version=raw.get("version", "1.0"),
        column_mappings=mappings,
        consumer_class_rules=_parse_class_rules(raw.get("consumer_class_rules", [])),
        detection_hints=_parse_detection_hints(raw.get("detection_hints", {})),
    )


def load_adapter_config(path: Path) -> AdapterConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not raw or not isinstance(raw, dict):
        raise ValueError(f"Invalid adapter config: {path}")
    return parse_adapter_config(raw)


def load_all_adapter_configs(
    configs_dir: Path | None = None,
) -> dict[str, AdapterConfig]:
    directory = configs_dir or ADAPTER_CONFIGS_DIR
    if not directory.exists():
        return {}

    configs: dict[str, AdapterConfig] = {}
    for yaml_path in sorted(directory.glob("*.yaml")):
        try:
            config = load_adapter_config(yaml_path)
            configs[config.name] = config
        except Exception:
            continue
    for yml_path in sorted(directory.glob("*.yml")):
        try:
            config = load_adapter_config(yml_path)
            if config.name not in configs:
                configs[config.name] = config
        except Exception:
            continue

    return configs


def save_adapter_config(config: AdapterConfig, configs_dir: Path | None = None) -> Path:
    directory = configs_dir or ADAPTER_CONFIGS_DIR
    directory.mkdir(parents=True, exist_ok=True)

    raw: dict[str, Any] = {
        "name": config.name,
        "description": config.description,
        "version": config.version,
        "column_mappings": {},
        "consumer_class_rules": [],
        "detection_hints": {
            "column_keywords": config.detection_hints.column_keywords,
            "content_keywords": config.detection_hints.content_keywords,
            "column_signature": config.detection_hints.column_signature,
            "signature_score_boost": config.detection_hints.signature_score_boost,
        },
    }

    for field_name, mapping in config.column_mappings.items():
        entry: dict[str, Any] = {"aliases": mapping.aliases}
        if mapping.required:
            entry["required"] = True
        if mapping.fallback is not None:
            entry["fallback"] = mapping.fallback
        if mapping.fallback_mode:
            entry["fallback_mode"] = mapping.fallback_mode
        if mapping.parse_as:
            entry["parse_as"] = mapping.parse_as
        raw["column_mappings"][field_name] = entry

    for rule in config.consumer_class_rules:
        if rule.is_default:
            raw["consumer_class_rules"].append({"default": rule.value})
        else:
            raw["consumer_class_rules"].append({
                "pattern": rule.pattern,
                "value": rule.value,
            })

    out_path = directory / f"{config.name}.yaml"
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.dump(raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return out_path
