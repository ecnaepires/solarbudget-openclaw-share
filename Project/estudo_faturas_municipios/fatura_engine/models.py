from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class UCMonthRecord:
    uc: str
    referencia: str
    grupo_tensao: str
    subgrupo: str
    categoria: str
    tipo_fornecimento: str
    origem: str
    nome: str
    endereco: str
    classificacao_uc: str = ""

    # Energy (kWh)
    kwh_b3_ip: Optional[float] = None
    kwh_a4_fp_te: Optional[float] = None
    kwh_a4_p_te: Optional[float] = None
    kwh_total_te: Optional[float] = None  # A4: fp+p; B3/IP: TE (or fallback)

    # Optional (economics)
    demanda_item: Optional[float] = None
    dif_demanda: Optional[float] = None
    demanda_contratada_kw: Optional[float] = None
    demanda_hp_kw: Optional[float] = None
    demanda_fhp_kw: Optional[float] = None
    consumo_hp_kwh: Optional[float] = None
    consumo_fhp_kwh: Optional[float] = None
    total_fatura_rs: Optional[float] = None
    itens_fatura_json: str = ""
    itens_fatura_total_valor_rs: Optional[float] = None
    itens_fatura_energia_valor_rs: Optional[float] = None
    itens_fatura_energia_kwh: Optional[float] = None
    itens_fatura_preco_medio_rs_kwh: Optional[float] = None
    itens_fatura_preco_all_in_fhp_rs_kwh: Optional[float] = None
    itens_fatura_preco_all_in_hp_rs_kwh: Optional[float] = None
    itens_fatura_preco_all_in_blended_rs_kwh: Optional[float] = None

    # Trace
    pdf_source: str = ""
    page_first_seen: int = -1
    audit_header_page: int = -1
    audit_itens_page: int = -1
    audit_historico_page: int = -1
    audit_kwh_source: str = ""
    provider_layout: str = ""
    needs_review: bool = False
    template: str = ""
