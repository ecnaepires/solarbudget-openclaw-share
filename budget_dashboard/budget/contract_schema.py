from __future__ import annotations

from dataclasses import dataclass


CONTRACT_SCHEMA_VERSION = "v1"
REQUIRED_CONTRACT_COLUMNS = [
    "uc",
    "referencia",
    "kwh_total_te",
]


def get_required_columns_for_adapter(adapter_name: str | None = None) -> list[str]:
    """Return required columns, optionally adjusted for the adapter.

    When adapter is 'auto' or None, skip strict schema validation
    since the adapter will resolve column aliases dynamically.
    """
    if adapter_name in (None, "", "auto"):
        return []  # Skip pre-adaptation validation
    try:
        from adapters import get_adapter
        from adapters.config_adapter import ConfigDrivenAdapter

        adapter = get_adapter(adapter_name)
        if isinstance(adapter, ConfigDrivenAdapter):
            # For config-driven adapters, required columns are the aliases
            # of fields marked as required in the config
            required = []
            for field_name, mapping in adapter.config.column_mappings.items():
                if mapping.required:
                    required.extend(mapping.aliases[:1])  # Use first alias as canonical
            return required if required else REQUIRED_CONTRACT_COLUMNS
    except Exception:
        pass
    return REQUIRED_CONTRACT_COLUMNS


@dataclass
class ContractSchemaError(Exception):
    missing_columns: list[str]
    actual_columns: list[str]
    required_columns: list[str]
    contract_path: str = ""
    schema_version: str = CONTRACT_SCHEMA_VERSION

    def __str__(self) -> str:
        missing = ", ".join(self.missing_columns) if self.missing_columns else "-"
        return (
            f"Contract schema validation failed (schema={self.schema_version}). "
            f"Missing columns: {missing}. Contract: {self.contract_path or '-'}"
        )

