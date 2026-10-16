from decimal import Decimal
import unittest

from imaks_kg.eval.source_diagnostics import parse_threshold_fields


class NumericDiagnosticTests(unittest.TestCase):
    def test_both_label_orders_and_nominal_tolerance(self):
        expected = dict(critLo=Decimal('-3.2'), warnLo=Decimal('1'), nominal=Decimal('5.1'),
                        warnHi=Decimal('8'), critHi=Decimal('10'))
        self.assertEqual(parse_threshold_fields(
            '-3.2°C (CRIT_LO), 1°C (WARN_LO), 5.1±0.2°C (NOMINAL), '
            '8°C (WARN_HI), 10°C (CRIT_HI)'), expected)
        self.assertEqual(parse_threshold_fields(
            'CRIT_LO=-3.2°C, WARN_LOW=1°C, nominal=5.1±0.2°C, '
            'WARN_HI=8°C, CRIT_HI=10°C'), expected)

    def test_unlabeled_numbers_are_not_guessed(self):
        self.assertEqual(parse_threshold_fields('range 1 to 9; inspect after 7 seconds'), {})


if __name__ == '__main__':
    unittest.main()
