import unittest

import pandas as pd

from fatura_engine.audit import build_audit_pdf_pages


class AuditTests(unittest.TestCase):
    def test_build_audit_pdf_pages_groups_by_uc_and_reference(self):
        df = pd.DataFrame(
            [
                {"uc": "123", "referencia": "01/2025", "pdf_source": "a.pdf", "page_first_seen": 3},
                {"uc": "123", "referencia": "01/2025", "pdf_source": "a.pdf", "page_first_seen": 1},
                {"uc": "123", "referencia": "01/2025", "pdf_source": "b.pdf", "page_first_seen": 2},
                {"uc": "123", "referencia": "02/2025", "pdf_source": "b.pdf", "page_first_seen": 4},
            ]
        )

        out = build_audit_pdf_pages(df, group_cols=["uc", "referencia"])
        by_key = {
            (row["uc"], row["referencia"]): row["audit_pdf_pages"]
            for _, row in out.iterrows()
        }

        self.assertEqual(by_key[("123", "01/2025")], "a: 1, 3 | b: 2")
        self.assertEqual(by_key[("123", "02/2025")], "b: 4")

    def test_build_audit_pdf_pages_empty_dataframe_contract(self):
        out = build_audit_pdf_pages(pd.DataFrame(), group_cols=["uc", "referencia"])
        self.assertEqual(list(out.columns), ["uc", "referencia", "audit_pdf_pages"])
        self.assertTrue(out.empty)


if __name__ == "__main__":
    unittest.main()

