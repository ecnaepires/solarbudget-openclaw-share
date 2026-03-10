import math


def mw_to_kwp(mwp: float) -> float:
    if mwp < 0:
        raise ValueError("mwp must be >= 0")
    return mwp * 1000


def apply_dc_ac_ratio(ac_kwp: float, dc_ac_ratio: float) -> float:
    if dc_ac_ratio <= 0:
        raise ValueError("dc_ac_ratio must be > 0")
    return ac_kwp * dc_ac_ratio


def calculate_module_count(total_kwp_dc: float, module_wp: float) -> int:
    if module_wp <= 0:
        raise ValueError("module_wp must be > 0")
    module_kwp = module_wp / 1000
    return math.ceil(total_kwp_dc / module_kwp)


def calculate_inverter_quantity(total_kwp_ac: float, inverter_kw: float) -> int:
    if inverter_kw <= 0:
        raise ValueError("inverter_kw must be > 0")
    return math.ceil(total_kwp_ac / inverter_kw)


def calculate_strings(module_count: int, modules_per_string: int) -> int:
    if modules_per_string <= 0:
        raise ValueError("modules_per_string must be > 0")
    return math.ceil(module_count / modules_per_string)


def calculate_combiners(strings: int, strings_per_combiner: int) -> int:
    if strings_per_combiner <= 0:
        raise ValueError("strings_per_combiner must be > 0")
    return math.ceil(strings / strings_per_combiner)


def string_voltage_vmp(modules_per_string: int, module_vmp: float) -> float:
    if module_vmp < 0:
        raise ValueError("module_vmp must be >= 0")
    return modules_per_string * module_vmp


def adjust_voltage_for_temperature(
    voltage_at_stc: float,
    temp_coeff_pct_per_c: float,
    temperature_c: float,
    stc_temp_c: float = 25.0,
) -> float:
    factor = 1 + (temp_coeff_pct_per_c / 100.0) * (temperature_c - stc_temp_c)
    return voltage_at_stc * factor


def string_voltage(modules_per_string: int, module_voltage: float) -> float:
    if module_voltage < 0:
        raise ValueError("module_voltage must be >= 0")
    return modules_per_string * module_voltage


def calculate_scale_factor(project_mwp: float, reference_mwp: float) -> float:
    if reference_mwp <= 0:
        raise ValueError("reference_mwp must be greater than zero")
    return project_mwp / reference_mwp


def scale_value(value: float, scale_factor: float, scalable: bool = True) -> float:
    return value * scale_factor if scalable else value
