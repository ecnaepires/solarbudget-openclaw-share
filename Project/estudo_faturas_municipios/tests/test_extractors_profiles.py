import unittest
from dataclasses import asdict

import pandas as pd

from fatura_engine.models import UCMonthRecord
import fatura_engine.extractors as ex


def _finalize_single_record(rec: UCMonthRecord, layout: str) -> pd.Series:
    rec.provider_layout = layout
    rec.template = layout
    df = pd.DataFrame([asdict(rec)])
    out = ex._finalize_extracted_df(df)
    return out.iloc[0]


class ExtractorProfileTests(unittest.TestCase):
    def test_celesc_b3_itens_te_is_source_of_truth(self):
        text = """
UC: 1234567890
Referencia: 09/2025
Grupo / Subgrupo Tensao:B-B3
Classificacao / Modalidade Tarifaria / Tipo de Fornecimento: PODER PUBLICO-TRIFASICO Municipio:
Nome: MUNICIPIO TESTE Endereco: RUA A, 10 Etapa:
Itens da Fatura
Consumo TE 4240 0,309625 1312,81
Energia Unico Apurado 9999
"""
        self.assertEqual(ex.detect_layout("RELACAO DE UCs DA COLETIVA\nITENS DA FATURA\nUC: 123"), "CELESC_COLETIVA")
        rec = ex.extract_from_uc_block(text, 0, "celesc.pdf")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.categoria, "B3")
        self.assertEqual(rec.referencia, "09/2025")
        self.assertEqual(rec.kwh_total_te, 4240.0)
        self.assertTrue(rec.audit_kwh_source.startswith("ITENS_CONSUMO_TE"))

        row = _finalize_single_record(rec, "CELESC_COLETIVA")
        self.assertFalse(bool(row["needs_review"]))

    def test_celesc_b3_fallback_when_no_itens(self):
        text = """
UC: 1234567891
Referencia: 09/2025
Grupo / Subgrupo Tensao:B-B3
Classificacao / Modalidade Tarifaria / Tipo de Fornecimento: PODER PUBLICO-TRIFASICO Municipio:
Nome: MUNICIPIO TESTE Endereco: RUA B, 20 Etapa:
Consumo TE 3210,00
"""
        rec = ex.extract_from_uc_block(text, 0, "celesc.pdf")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.categoria, "B3")
        self.assertEqual(rec.referencia, "09/2025")
        self.assertEqual(rec.kwh_total_te, 3210.0)
        self.assertTrue(rec.audit_kwh_source.startswith("TEXTO_CONSUMO_TE"))

        row = _finalize_single_record(rec, "CELESC_COLETIVA")
        self.assertTrue(bool(row["needs_review"]))

    def test_celesc_ip_itens_te(self):
        text = """
UC: 1234567892
Referencia: 09/2025
Grupo / Subgrupo Tensao:B-B4A
Classificacao / Modalidade Tarifaria / Tipo de Fornecimento: ILUMINACAO PUBLICA-TRIFASICO Municipio:
Nome: MUNICIPIO TESTE Endereco: AV C, 30 Etapa:
Itens da Fatura
Consumo IP TE 1234 0,200000 246,80
"""
        rec = ex.extract_from_uc_block(text, 0, "celesc.pdf")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.categoria, "IP")
        self.assertEqual(rec.referencia, "09/2025")
        self.assertEqual(rec.kwh_total_te, 1234.0)
        self.assertTrue(rec.audit_kwh_source.startswith("ITENS_CONSUMO_TE"))

        row = _finalize_single_record(rec, "CELESC_COLETIVA")
        self.assertFalse(bool(row["needs_review"]))

    def test_enel_a4_historico_parsing_normalizes_to_13_months(self):
        layout_text = """
DOCUMENTO AUXILIAR DA NOTA FISCAL
ITENS de Fatura Unid Quant
MÊS/ANO
"""
        self.assertEqual(ex.detect_layout(layout_text), "ENEL_A4")

        hist_text = """
HISTORICO DO FATURAMENTO
SET/25 10 11 2545 2660
AGO/25 9 10 171 181
"""
        rows = ex.parse_a4_historico(hist_text)
        self.assertEqual(len(rows), 13)
        by_ref = {r["referencia"]: r for r in rows}
        self.assertEqual(by_ref["09/2025"]["consumo_fhp_kwh"], 2660.0)

        rec = UCMonthRecord(
            uc="5550001",
            referencia="09/2025",
            grupo_tensao="A",
            subgrupo="A4",
            categoria="A4",
            tipo_fornecimento="TRIFÁSICO",
            origem="",
            nome="ENEL TEST",
            endereco="RUA X",
            kwh_total_te=5205.0,
            audit_kwh_source="HISTORICO_A4",
        )
        row = _finalize_single_record(rec, "ENEL_A4")
        self.assertFalse(bool(row["needs_review"]))

    def test_elektro_cci_parsing_and_historico_expansion(self):
        text = """
47430001
MUNICIPIO DE ILHABELA
Data de Emissao: 11/09/2025
Setembro/2025
CCI* Descricao do Produto Quantidade
0601 CONSUMO TE 4.240,00 0,309625 1.312,81
4240 2600 3160 5160 4960 7200 8160 0 0 0 0 0 0
SET/25 AGO/25 JUL/25 JUN/25 MAI/25 ABR/25 MAR/25 FEV/25 JAN/25 DEZ/24 NOV/24 OUT/24 SET/24
GBELEKTRO1
"""
        self.assertEqual(ex.detect_layout(text), "NEOENERGIA_ELEKTRO")
        rec = ex._extract_elektro_record_from_block(text, 0, "elektro.pdf")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.categoria, "B3")
        self.assertEqual(rec.referencia, "09/2025")
        self.assertEqual(rec.kwh_total_te, 4240.0)
        self.assertTrue(rec.audit_kwh_source.startswith("TEXTO_CONSUMO_TE"))

        expanded = ex.expand_b3_ip_record_from_block(text, rec)
        self.assertEqual(len(expanded), 13)
        map_kwh = {r.referencia: r.kwh_total_te for r in expanded}
        self.assertEqual(map_kwh["09/2025"], 4240.0)
        self.assertEqual(map_kwh["08/2025"], 2600.0)
        self.assertEqual(map_kwh["03/2025"], 8160.0)

        row = _finalize_single_record(rec, "NEOENERGIA_ELEKTRO")
        self.assertTrue(bool(row["needs_review"]))

    def test_generic_layout_marks_review(self):
        self.assertEqual(ex.detect_layout("FATURA XYZ SEM MARCADORES CONHECIDOS"), "GENERIC")
        rec = UCMonthRecord(
            uc="999",
            referencia="09/2025",
            grupo_tensao="",
            subgrupo="",
            categoria="OUTROS",
            tipo_fornecimento="",
            origem="",
            nome="GENERIC",
            endereco="RUA Z",
            kwh_total_te=100.0,
            audit_kwh_source="GENERIC_KWH",
        )
        row = _finalize_single_record(rec, "GENERIC")
        self.assertTrue(bool(row["needs_review"]))

    def test_missing_referencia_marks_review(self):
        rec = UCMonthRecord(
            uc="777",
            referencia="",
            grupo_tensao="B",
            subgrupo="B3",
            categoria="B3",
            tipo_fornecimento="TRIFÁSICO",
            origem="",
            nome="MISSING REF",
            endereco="RUA M",
            kwh_total_te=300.0,
            kwh_b3_ip=300.0,
            audit_kwh_source="ITENS_CONSUMO_TE",
        )
        row = _finalize_single_record(rec, "CELESC_COLETIVA")
        self.assertTrue(bool(row["needs_review"]))

    def test_ocr_broken_numbers_with_dot_decimal(self):
        text = """
12345000
MUNICIPIO TESTE
Data de Emissao: 11/09/2025
Setembro/2025
CCI* Descricao do Produto Quantidade
0601 CONSUMO TE 1.700 0,300000 510,00
1700 1500 1400 1300 1200 1100 1000 900 800 700 600 500 400
SET/25 AGO/25 JUL/25 JUN/25 MAI/25 ABR/25 MAR/25 FEV/25 JAN/25 DEZ/24 NOV/24 OUT/24 SET/24
GBELEKTRO1
"""
        self.assertEqual(ex.detect_layout(text), "NEOENERGIA_ELEKTRO")
        rec = ex._extract_elektro_record_from_block(text, 0, "ocr.pdf")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.referencia, "09/2025")
        self.assertEqual(rec.kwh_total_te, 1700.0)
        self.assertTrue(rec.audit_kwh_source.startswith("TEXTO_CONSUMO_TE"))

    def test_generic_cascade_supports_installacao_mes_ano_and_energia_ativa(self):
        text = """
Instalacao: 1234567
Mes/Ano: 01/2025
Subgrupo: B3
Classe de Consumo: Comercial
Modalidade Tarifaria: Convencional
Energia Ativa 1.234,00
Demanda Registrada 45,00
Valor Total: R$ 987,65
"""
        rec = ex.extract_from_uc_block(text, 0, "generic.pdf")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.uc, "0001234567")
        self.assertEqual(rec.referencia, "01/2025")
        self.assertEqual(rec.categoria, "B3")
        self.assertEqual(rec.kwh_total_te, 1234.0)
        self.assertEqual(rec.demanda_item, 45.0)
        self.assertEqual(rec.total_fatura_rs, 987.65)
        self.assertTrue(rec.audit_kwh_source.startswith("TEXTO_CONSUMO_TE"))

    def test_detect_layout_recognizes_new_utilities(self):
        self.assertEqual(
            ex.detect_layout("CPFL PAULISTA\nItens da Fatura\nDescricao do Faturamento"),
            "CPFL",
        )
        self.assertEqual(
            ex.detect_layout("CEMIG DISTRIBUICAO S.A\nConta de Energia\nItens de Fatura"),
            "CEMIG",
        )
        self.assertEqual(
            ex.detect_layout("COPEL\nCompanhia Paranaense\nDescricao do Faturamento"),
            "COPEL",
        )
        self.assertEqual(
            ex.detect_layout("Equatorial Energia\nFatura\nDescricao do Faturamento"),
            "EQUATORIAL",
        )
        self.assertEqual(
            ex.detect_layout("Energisa\nFatura\nDescricao do Faturamento"),
            "ENERGISA",
        )
        self.assertEqual(
            ex.detect_layout("Light Servicos de Eletricidade S.A."),
            "LIGHT",
        )
        self.assertEqual(
            ex.detect_layout("Neoenergia Coelba\nFatura"),
            "COELBA",
        )


if __name__ == "__main__":
    unittest.main()
