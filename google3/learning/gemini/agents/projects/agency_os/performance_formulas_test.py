# Financial formulas unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import performance_formulas

class PerformanceFormulasTest(absltest.TestCase):

    def test_calculate_cm1(self):
        self.assertEqual(performance_formulas.calculate_cm1(100.0, 40.0), 60.0)

    def test_calculate_cm2(self):
        cm2 = performance_formulas.calculate_cm2(
            cm1=60.0,
            fulfillment=10.0,
            payment_gateway=2.0,
            cod_remittance=3.0,
            refunds=5.0
        )
        self.assertEqual(cm2, 40.0)

    def test_calculate_cm3(self):
        cm3 = performance_formulas.calculate_cm3(
            cm2=40.0,
            allocated_infra=2.0,
            allocated_labour=10.0,
            allocated_support=3.0,
            allocated_acquisition=5.0
        )
        self.assertEqual(cm3, 20.0)

    def test_calculate_net_ad_spend(self):
        # Default 18% tax divisor
        net_spend = performance_formulas.calculate_net_ad_spend(118.0)
        self.assertAlmostEqual(net_spend, 100.0)

        # Custom divisor
        net_spend_custom = performance_formulas.calculate_net_ad_spend(110.0, tax_divisor=1.10)
        self.assertAlmostEqual(net_spend_custom, 100.0)

        with self.assertRaises(ValueError):
            performance_formulas.calculate_net_ad_spend(100.0, tax_divisor=0)

    def test_calculate_poas(self):
        poas = performance_formulas.calculate_poas(20.0, 100.0)
        self.assertEqual(poas, 0.2)

        # Zero ad spend edge case
        poas_zero = performance_formulas.calculate_poas(20.0, 0.0)
        self.assertEqual(poas_zero, 0.0)

if __name__ == "__main__":
    absltest.main()
