from pathlib import Path


TEMPLATE_PATH = Path("template.xlsx")
OUTPUT_PATH = Path("output.xlsx")
EXCEL_MAP_PATH = Path("excel_map.yaml")

CATALOG_DIR = Path("catalog")
OUTPUTS_DIR = Path("outputs")
ASSETS_DIR = Path("assets")
AUDIT_LOG_PATH = OUTPUTS_DIR / "audit_log.csv"
DATA_DIR = Path("data")
INPUTS_PDFS_DIR = DATA_DIR / "inputs_pdfs"
EXTRACTION_OUTPUTS_DIR = DATA_DIR / "outputs_extraction"
EXTRACTION_LOGS_DIR = EXTRACTION_OUTPUTS_DIR / "logs"
EXTRACTION_CONTRACT_DIR = EXTRACTION_OUTPUTS_DIR / "contract"
EXTRACTION_CONTRACT_MASTER_PATH = EXTRACTION_CONTRACT_DIR / "contract_master.csv"

MODULES_CSV_PATH = CATALOG_DIR / "modules.csv"
INVERTERS_CSV_PATH = CATALOG_DIR / "inverters.csv"
BOS_COSTS_CSV_PATH = CATALOG_DIR / "bos_costs.csv"
PRICING_VERSIONS_CSV_PATH = CATALOG_DIR / "pricing_versions.csv"
LOCATIONS_CSV_PATH = CATALOG_DIR / "municipios_ibge.csv"

DC_AC_RATIO_MIN = 1.05
DC_AC_RATIO_MAX = 1.40

STC_TEMP_C = 25.0
BRAZIL_MIN_AMBIENT_C = 0.0
BRAZIL_MAX_AMBIENT_C = 45.0
DEFAULT_HOT_CELL_DELTA_C = 20.0

# Dimensioning defaults
DEFAULT_HSP = 4.9
DEFAULT_PR = 0.80
DEFAULT_CAPEX_BRL_PER_MWP = 8_500_000.0
DEFAULT_MONTHS_TO_USE = 13
DEFAULT_FUSION_EXPECTED_MONTHS = 13

# Log rotation
MAX_EXTRACTION_LOG_FILES = 20

# Cell address map for the dimensionamento Excel template sheet.
# Update these if the template layout changes — do not hardcode addresses elsewhere.
DIMENSIONAMENTO_CELL_MAP: dict[str, str] = {
    "consumo_b3": "D5",
    "consumo_b4a": "D13",
    "consumo_a4_hp": "D24",
    "consumo_a4_fhp": "D32",
    "kwp_b3": "D9",
    "kwp_b4a": "D17",
    "kwp_a4_hp": "D29",
    "kwp_a4_fhp": "D36",
    "total_kwp": "N8",
    "hsp": "D6",
    "performance_ratio": "D7",
    "days_per_month": "D8",
    "a4_hp_factor": "D25",
    "capex_brl_per_mwp": "N19",
    "investment_brl": "N24",
    "energy_cost_month": "N16",
    "payback_months": "N26",
}

# Estimated cost benchmark rates used in export analytics
# Update these when tariff baselines change — they are NOT used in final budget calculations
DEFAULT_ENERGY_RATE_BRL_KWH = 0.85
DEFAULT_DEMAND_RATE_BRL_KW = 42.0
DEFAULT_PEAK_THRESHOLD_PCT = 25.0
