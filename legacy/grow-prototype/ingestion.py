# Agency OS — Ingestion & Normalization Core
import dataclasses
import hashlib
import typing

@dataclasses.dataclass
class NormalizedLineItem:
    sku: str
    quantity: int
    price: float  # Price net of tax, before discount
    cogs: float = 0.0  # Unit Cost of Goods Sold

@dataclasses.dataclass
class NormalizedOrder:
    order_id: str
    tenant_id: str
    gross_revenue: float  # Total gross sales net of tax, before discount
    discounts: float      # Total discounts applied
    shipping: float       # Shipping fee charged to customer
    tax: float            # Tax collected
    refunds: float        # Total refunded amount (for reverse logistics)
    line_items: typing.List[NormalizedLineItem]
    customer_email: str
    customer_phone: str
    created_at: str


class OmnichannelIngestionAdapter:
    """Ingests raw payloads from multiple platforms and normalizes them."""

    def __init__(self, tenant_id: str, pii_salt: str = "default_salt"):
        self.tenant_id = tenant_id
        self.pii_salt = pii_salt

    def mask_pii(self, value: str) -> str:
        """Utility to hash PII using SHA-256 with salt."""
        if not value:
            return ""
        salted = f"{value}{self.pii_salt}".encode("utf-8")
        return hashlib.sha256(salted).hexdigest()

    def normalize_shopify(self, payload: typing.Dict[str, typing.Any]) -> NormalizedOrder:
        """Normalizes Shopify Order webhook payload.
        
        Reference payload layout: Shopify API order object.
        """
        # Extract financial variables
        total_tax = float(payload.get("total_tax", 0.0))
        total_discounts = float(payload.get("total_discounts", 0.0))
        
        # Shopify total_price includes tax & shipping, and is net of discount.
        # Gross Revenue = Total Line Items Price (excluding shipping/tax and before discounts in some setups)
        # For our formula: Gross_Revenue (net of tax, before discount)
        # Shopify subtotal_price is total of line items net of discounts, excluding tax/shipping.
        subtotal_price = float(payload.get("subtotal_price", 0.0))
        gross_revenue = subtotal_price + total_discounts
        
        shipping = 0.0

        shipping_lines = payload.get("shipping_lines", [])
        if shipping_lines:
            shipping = sum(float(line.get("price", 0.0)) for line in shipping_lines)

        refunds = 0.0
        refund_lines = payload.get("refunds", [])
        if refund_lines:
            refunds = sum(float(r.get("total_duties_set", {}).get("shop_money", {}).get("amount", 0.0)) or
                          sum(float(line.get("subtotal", 0.0)) for line in r.get("refund_line_items", []))
                          for r in refund_lines)

        # Map line items
        line_items = []
        for item in payload.get("line_items", []):
            line_items.append(NormalizedLineItem(
                sku=item.get("sku", "UNKNOWN_SKU"),
                quantity=int(item.get("quantity", 1)),
                price=float(item.get("price", 0.0))
            ))

        customer = payload.get("customer", {})
        email = customer.get("email", "")
        phone = customer.get("phone", "")

        return NormalizedOrder(
            order_id=str(payload.get("id")),
            tenant_id=self.tenant_id,
            gross_revenue=gross_revenue,
            discounts=total_discounts,
            shipping=shipping,
            tax=total_tax,
            refunds=refunds,
            line_items=line_items,
            customer_email=self.mask_pii(email),
            customer_phone=self.mask_pii(phone),
            created_at=payload.get("created_at")
        )

    def normalize_woocommerce(self, payload: typing.Dict[str, typing.Any]) -> NormalizedOrder:
        """Normalizes WooCommerce Order REST API payload."""
        total_tax = float(payload.get("total_tax", 0.0))
        # Woo total is net of discount, including shipping and tax.
        total_discounts = float(payload.get("discount_total", 0.0))
        shipping = float(payload.get("shipping_total", 0.0))
        
        # Woo line items list price is net of discount.
        # Gross Revenue = subtotal (price before discounts) net of tax.
        # WooCommerce stores subtotal in line items.
        line_items = []
        gross_revenue = 0.0
        for item in payload.get("line_items", []):
            qty = int(item.get("quantity", 1))
            price_net = float(item.get("subtotal", 0.0)) / qty if qty > 0 else 0.0
            gross_revenue += float(item.get("subtotal", 0.0))
            
            line_items.append(NormalizedLineItem(
                sku=item.get("sku", "UNKNOWN_SKU"),
                quantity=qty,
                price=price_net
            ))

        refunds = sum(float(r.get("total", 0.0)) for r in payload.get("refunds", []))

        billing = payload.get("billing", {})
        email = billing.get("email", "")
        phone = billing.get("phone", "")

        return NormalizedOrder(
            order_id=str(payload.get("id")),
            tenant_id=self.tenant_id,
            gross_revenue=gross_revenue,
            discounts=total_discounts,
            shipping=shipping,
            tax=total_tax,
            refunds=abs(refunds),
            line_items=line_items,
            customer_email=self.mask_pii(email),
            customer_phone=self.mask_pii(phone),
            created_at=payload.get("date_created")
        )
