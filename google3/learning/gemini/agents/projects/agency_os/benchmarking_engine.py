"""Agency OS — Privacy-Preserving Cross-Tenant Benchmarking Engine.

Aggregates advertising performance statistics (POAS, CVR, CPC) across tenants
within identical categories, strictly blocking output if category size is < 5.
"""

import dataclasses
import typing

@dataclasses.dataclass
class TenantBenchmarkRecord:
    tenant_id: str
    category: str
    poas: float
    cvr: float
    cpc: float


class BenchmarkingEngine:
    """Computes category aggregates ensuring tenant data anonymity."""

    def __init__(self):
        pass

    def calculate_category_benchmark(
        self,
        records: typing.List[TenantBenchmarkRecord],
        category: str
    ) -> typing.Dict[str, float]:
        """Calculates benchmark metrics for a category if safe.

        Args:
            records: Master list of all tenant performance records.
            category: Target business vertical (e.g. 'Fashion').

        Returns:
            Dictionary containing average performance statistics.

        Raises:
            ValueError: If fewer than 5 unique tenants exist in the category.
        """
        # Filter records for the target category
        category_records = [r for r in records if r.category.lower() == category.lower()]

        # Identify unique tenants
        unique_tenants = {r.tenant_id for r in category_records}
        tenant_count = len(unique_tenants)

        # Enforce N >= 5 privacy threshold constraint
        if tenant_count < 5:
            raise ValueError(
                f"Privacy violation: category '{category}' only has {tenant_count} "
                "active tenants. Minimum threshold is 5."
            )

        # Calculate averages
        sum_poas = sum(r.poas for r in category_records)
        sum_cvr = sum(r.cvr for r in category_records)
        sum_cpc = sum(r.cpc for r in category_records)
        total_records = len(category_records)

        return {
            "avg_poas": sum_poas / total_records,
            "avg_cvr": sum_cvr / total_records,
            "avg_cpc": sum_cpc / total_records,
            "active_tenants_count": float(tenant_count)
        }
