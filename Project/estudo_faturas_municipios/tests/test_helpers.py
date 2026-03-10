import unittest

from fatura_engine.helpers import (
    date_to_ref,
    normalize_reference_token,
    normalize_uc,
    parse_ptbr_number,
    yyyymm_to_ref,
)


class HelpersTests(unittest.TestCase):
    def test_parse_ptbr_number_full_format(self):
        self.assertEqual(parse_ptbr_number("1.234,56"), 1234.56)

    def test_parse_ptbr_number_integer_with_thousand_separator(self):
        self.assertEqual(parse_ptbr_number("1.700"), 1700.0)

    def test_parse_ptbr_number_invalid_returns_none(self):
        self.assertIsNone(parse_ptbr_number("abc"))

    def test_yyyymm_to_ref(self):
        self.assertEqual(yyyymm_to_ref("202511"), "11/2025")

    def test_date_to_ref(self):
        self.assertEqual(date_to_ref("24/11/2025"), "11/2025")

    def test_normalize_uc_preserves_leading_zero_with_padding(self):
        self.assertEqual(normalize_uc("00123", target_len=10), "0000000123")

    def test_normalize_uc_strips_non_digits(self):
        self.assertEqual(normalize_uc("UC: 000123-4", target_len=6), "0001234")

    def test_normalize_reference_token_numeric(self):
        self.assertEqual(normalize_reference_token("1/25"), "01/2025")

    def test_normalize_reference_token_month_label(self):
        self.assertEqual(normalize_reference_token("Fev-2024"), "02/2024")

    def test_normalize_reference_token_compact_yyyymm(self):
        self.assertEqual(normalize_reference_token("202511"), "11/2025")


if __name__ == "__main__":
    unittest.main()
