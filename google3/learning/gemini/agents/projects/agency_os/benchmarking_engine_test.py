# Benchmarking Engine unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import benchmarking_engine

class BenchmarkingEngineTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.engine = benchmarking_engine.BenchmarkingEngine()
        # 5 distinct tenants in Fashion
        self.valid_records = [
            benchmarking_engine.TenantBenchmarkRecord("t1", "Fashion", poas=1.2, cvr=0.02, cpc=0.8),
            benchmarking_engine.TenantBenchmarkRecord("t2", "Fashion", poas=1.4, cvr=0.03, cpc=0.9),
            benchmarking_engine.TenantBenchmarkRecord("t3", "Fashion", poas=1.1, cvr=0.015, cpc=0.7),
            benchmarking_engine.TenantBenchmarkRecord("t4", "Fashion", poas=1.5, cvr=0.035, cpc=1.0),
            benchmarking_engine.TenantBenchmarkRecord("t5", "Fashion", poas=1.3, cvr=0.025, cpc=0.85)
        ]

    def test_calculate_benchmark_success(self):
        benchmark = self.engine.calculate_category_benchmark(self.valid_records, "Fashion")
        
        # Averages:
        # POAS = (1.2 + 1.4 + 1.1 + 1.5 + 1.3) / 5 = 1.3
        # CVR = (0.02 + 0.03 + 0.015 + 0.035 + 0.025) / 5 = 0.025
        # CPC = (0.8 + 0.9 + 0.7 + 1.0 + 0.85) / 5 = 0.85
        self.assertEqual(benchmark["active_tenants_count"], 5.0)
        self.assertEqual(benchmark["avg_poas"], 1.3)
        self.assertEqual(benchmark["avg_cvr"], 0.025)
        self.assertEqual(benchmark["avg_cpc"], 0.85)

    def test_calculate_benchmark_privacy_violation_raises(self):
        # Only 4 distinct tenants in Fashion
        invalid_records = self.valid_records[:-1] # slice last out
        
        with self.assertRaises(ValueError) as context:
            self.engine.calculate_category_benchmark(invalid_records, "Fashion")
            
        self.assertIn("Privacy violation: category 'Fashion' only has 4 active tenants", str(context.exception))

if __name__ == "__main__":
    absltest.main()
