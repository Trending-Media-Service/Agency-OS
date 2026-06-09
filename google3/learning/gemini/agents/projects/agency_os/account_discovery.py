"""Agency OS — Multi-Tenant Account Discovery & Auto-Linking Engine.

Discovers sub-accounts in Google Ads MCC manager hierarchies and GMC MCA merchant
structures, heuristics-linking them to storefront domains under verification gates.
"""

import re
import typing

@typing.final
class AdAccount(typing.NamedTuple):
    account_id: str
    name: str
    domain: str


@typing.final
class MerchantProfile(typing.NamedTuple):
    merchant_id: str
    name: str
    domain: str


@typing.final
class StorefrontProfile(typing.NamedTuple):
    store_id: str
    name: str
    website_url: str


@typing.final
class AutoLinkedProfile(typing.NamedTuple):
    tenant_id: str
    store_id: str
    ad_account_id: str
    merchant_id: str
    status: str  # Always PENDING_VERIFICATION


class AccountDiscoveryEngine:
    """Traverses advertising MCC/MCA managers and links storefront channels."""

    def __init__(self):
        pass

    def traverse_mcc(
        self,
        mcc_node: typing.Dict[str, typing.Any]
    ) -> typing.List[AdAccount]:
        """Recursively traverses manager hierarchies to find leaf ad accounts.

        Args:
            mcc_node: Tree dictionary node with 'id', 'name', 'type'
              ('MANAGER' or 'LEAF'), and 'children' list of nodes.

        Returns:
            List of AdAccount named tuples found.
        """
        results = []
        if mcc_node.get("type") == "LEAF":
            results.append(
                AdAccount(
                    account_id=mcc_node["id"],
                    name=mcc_node["name"],
                    domain=mcc_node.get("domain", "")
                )
            )
        else:
            for child in mcc_node.get("children", []):
                results.extend(self.traverse_mcc(child))
        return results

    def discover_mca_merchants(
        self,
        mca_node: typing.Dict[str, typing.Any]
    ) -> typing.List[MerchantProfile]:
        """Traverses Multi-Client Account structures to map sub-merchants.

        Args:
            mca_node: Node structure containing 'id', 'name', and 'sub_accounts'
              list of dicts.

        Returns:
            List of MerchantProfile profiles.
        """
        results = []
        for sub in mca_node.get("sub_accounts", []):
            results.append(
                MerchantProfile(
                    merchant_id=sub["id"],
                    name=sub["name"],
                    domain=sub.get("domain", "")
                )
            )
        return results

    def _extract_domain(self, url: str) -> str:
        """Extracts bare domain from url string (e.g. https://foo.com/ -> foo.com)."""
        clean = re.sub(r"^https?://(www\.)?", "", url.lower())
        return clean.split("/")[0].strip()

    def auto_link_properties(
        self,
        tenant_id: str,
        storefronts: typing.List[StorefrontProfile],
        ads_accounts: typing.List[AdAccount],
        merchants: typing.List[MerchantProfile]
    ) -> typing.List[AutoLinkedProfile]:
        """Matches properties using website domains and fuzzy string brand names.

        Args:
            tenant_id: Current brand tenant ID.
            storefronts: Connected storefront platforms list.
            ads_accounts: List of discovered ad accounts.
            merchants: List of GMC merchant profiles.

        Returns:
            List of linked properties flagged as PENDING_VERIFICATION.
        """
        linked = []

        for store in storefronts:
            store_domain = self._extract_domain(store.website_url)
            store_name_clean = re.sub(
                r"[^a-zA-Z0-9]", "", store.name.lower()
            )

            matched_ads_id = ""
            matched_merchant_id = ""

            # 1. Match Ad Accounts
            for ads in ads_accounts:
                ads_domain_clean = ads.domain.lower().strip()
                # Match by domain exact match
                if ads_domain_clean and ads_domain_clean == store_domain:
                    matched_ads_id = ads.account_id
                    break
                # Fallback: Match by name similarity
                ads_name_clean = re.sub(r"[^a-zA-Z0-9]", "", ads.name.lower())
                if (
                    store_name_clean in ads_name_clean
                    or ads_name_clean in store_name_clean
                ):
                    matched_ads_id = ads.account_id
                    break

            # 2. Match GMC Merchants
            for mer in merchants:
                mer_domain_clean = mer.domain.lower().strip()
                if mer_domain_clean and mer_domain_clean == store_domain:
                    matched_merchant_id = mer.merchant_id
                    break
                mer_name_clean = re.sub(r"[^a-zA-Z0-9]", "", mer.name.lower())
                if (
                    store_name_clean in mer_name_clean
                    or mer_name_clean in store_name_clean
                ):
                    matched_merchant_id = mer.merchant_id
                    break

            # Yield profile if at least one advertising channel matched
            if matched_ads_id or matched_merchant_id:
                linked.append(
                    AutoLinkedProfile(
                        tenant_id=tenant_id,
                        store_id=store.store_id,
                        ad_account_id=matched_ads_id,
                        merchant_id=matched_merchant_id,
                        status="PENDING_VERIFICATION"
                    )
                )

        return linked
