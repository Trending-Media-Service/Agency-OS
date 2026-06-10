"""Agency OS — FeedX Merchant Center Alignment Engine.

Reconciles product data (price and availability) between the active e-commerce
storefront and the Google Merchant Center (GMC) feed to prevent feed suspension.
"""

import dataclasses
import typing

@dataclasses.dataclass
class GmcProduct:
    gmc_id: str
    title: str
    price: float
    availability: str  # e.g., 'in_stock', 'out_of_stock'
    link: str


@dataclasses.dataclass
class StoreProduct:
    sku: str
    title: str
    price: float
    availability: str  # e.g., 'in_stock', 'out_of_stock'


class FeedXAlignment:
    """Audits product details against GMC catalog."""

    def __init__(self):
        pass

    def reconcile_catalog(
        self,
        gmc_products: typing.List[GmcProduct],
        store_products: typing.List[StoreProduct]
    ) -> typing.List[typing.Dict[str, typing.Any]]:
        """Identifies catalog discrepancies between storefront and GMC.

        Args:
            gmc_products: Product details in the current GMC feed.
            store_products: Product details on the active live storefront.

        Returns:
            List of discrepancy reports.
        """
        store_map = {p.sku: p for p in store_products}
        mismatches = []

        for gmc_prod in gmc_products:
            # We assume GMC ID matches storefront SKU
            store_prod = store_map.get(gmc_prod.gmc_id)
            if not store_prod:
                mismatches.append({
                    "sku": gmc_prod.gmc_id,
                    "title": gmc_prod.title,
                    "error_type": "MISSING_IN_STORE",
                    "severity": "CRITICAL",
                    "details": "Product exists in GMC but not on live storefront."
                })
                continue

            price_diff = store_prod.price - gmc_prod.price
            avail_mismatch = store_prod.availability != gmc_prod.availability

            if abs(price_diff) > 0.01 or avail_mismatch:
                mismatches.append({
                    "sku": gmc_prod.gmc_id,
                    "title": gmc_prod.title,
                    "error_type": "DATA_MISMATCH",
                    "severity": "CRITICAL" if abs(price_diff) > 0.0 else "WARNING",
                    "details": {
                        "price_difference": price_diff,
                        "store_price": store_prod.price,
                        "gmc_price": gmc_prod.price,
                        "availability_mismatch": avail_mismatch,
                        "store_availability": store_prod.availability,
                        "gmc_availability": gmc_prod.availability
                    }
                })

        return mismatches
