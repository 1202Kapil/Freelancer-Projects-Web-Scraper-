"""Data models for SuperValue catalogue items, branches, and collection batches."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional


@dataclass
class Branch:
    id: str
    name: str
    url: str
    address: Optional[str] = None
    postcode: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    shopping_online: bool = True
    service_notes: Optional[str] = None
    opening_hours: dict = field(default_factory=dict)

    @classmethod
    def model_validate(cls, data: dict) -> Branch:
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Promotion:
    on_special: bool = False
    previous_price_nzd: Optional[Decimal] = None
    savings_nzd: Optional[Decimal] = None
    multibuy_quantity: Optional[int] = None
    multibuy_price_nzd: Optional[Decimal] = None
    description: Optional[str] = None


@dataclass
class Product:
    branch_id: str
    branch_name: str
    name: str
    product_id: Optional[str] = None
    product_key: Optional[str] = None
    identity_quality: str = "source_id"  # 'source_id', 'url', 'name_fallback'
    brand: Optional[str] = None
    category_paths: list[list[str]] = field(default_factory=list)
    price_nzd: Optional[Decimal] = None
    pricing_unit: Optional[str] = None
    unit_price_nzd: Optional[Decimal] = None
    unit_price_basis: Optional[str] = None
    promotion: Optional[Promotion] = None
    availability: str = "in_stock"  # 'in_stock', 'out_of_stock'
    image_url: Optional[str] = None
    product_url: Optional[str] = None
    description: Optional[str] = None
    gtin: Optional[str] = None
    sku: Optional[str] = None
    attributes: dict[str, Any] = field(default_factory=dict)
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict matching internal JSON schema."""
        d = {
            "branch_id": self.branch_id,
            "branch_name": self.branch_name,
            "name": self.name,
            "product_id": self.product_id,
            "product_key": self.product_key,
            "identity_quality": self.identity_quality,
            "brand": self.brand,
            "category_paths": self.category_paths,
            "price_nzd": str(self.price_nzd) if self.price_nzd is not None else None,
            "pricing_unit": self.pricing_unit,
            "unit_price_nzd": str(self.unit_price_nzd) if self.unit_price_nzd is not None else None,
            "unit_price_basis": self.unit_price_basis,
            "promotion": self.promotion.__dict__ if self.promotion else None,
            "availability": self.availability,
            "image_url": self.image_url,
            "product_url": self.product_url,
            "description": self.description,
            "gtin": self.gtin,
            "sku": self.sku,
            "attributes": self.attributes,
            "scraped_at": self.scraped_at.isoformat() if hasattr(self.scraped_at, "isoformat") else str(self.scraped_at),
        }
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def model_validate(cls, data: dict) -> Product:
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        # Map contract alias names to canonical model fields if not already set
        if not filtered.get("name") and (data.get("clean_name") or data.get("raw_name")):
            filtered["name"] = data.get("clean_name") or data.get("raw_name")
        if not filtered.get("branch_id"):
            if data.get("branch_id"):
                filtered["branch_id"] = data["branch_id"]
            elif isinstance(data.get("raw_row"), dict) and data["raw_row"].get("branch_id"):
                filtered["branch_id"] = data["raw_row"]["branch_id"]
            else:
                filtered["branch_id"] = "unknown"
        if not filtered.get("branch_name"):
            filtered["branch_name"] = data.get("branch_name") or filtered.get("branch_id", "").title()
        if not filtered.get("product_id") and data.get("source_product_id"):
            filtered["product_id"] = data["source_product_id"]
        if not filtered.get("price_nzd") and data.get("current_price_cents"):
            filtered["price_nzd"] = Decimal(str(data["current_price_cents"])) / Decimal(100)
        if not filtered.get("gtin") and data.get("barcode"):
            filtered["gtin"] = data["barcode"]
        if not filtered.get("sku") and data.get("retailer_sku"):
            filtered["sku"] = data["retailer_sku"]
        if not filtered.get("description") and isinstance(data.get("raw_row"), dict) and data["raw_row"].get("description"):
            filtered["description"] = data["raw_row"]["description"]
        if "price_nzd" in filtered and filtered["price_nzd"] is not None:
            filtered["price_nzd"] = Decimal(str(filtered["price_nzd"]))
        if "unit_price_nzd" in filtered and filtered["unit_price_nzd"] is not None:
            filtered["unit_price_nzd"] = Decimal(str(filtered["unit_price_nzd"]))
        if "promotion" in filtered and isinstance(filtered["promotion"], dict):
            filtered["promotion"] = Promotion(**filtered["promotion"])
        if "scraped_at" in filtered and isinstance(filtered["scraped_at"], str):
            try:
                filtered["scraped_at"] = datetime.fromisoformat(filtered["scraped_at"])
            except Exception:
                filtered["scraped_at"] = datetime.now(timezone.utc)
        return cls(**filtered)

    def model_dump(self, mode: str = "python", exclude_none: bool = False) -> dict[str, Any]:
        """Support serialization and audits."""
        d = self.to_dict()
        if mode == "json":
            for k in ("price_nzd", "unit_price_nzd"):
                if k in d and d[k] is not None:
                    d[k] = str(d[k])
        if exclude_none:
            d = {k: v for k, v in d.items() if v is not None}
        return d

    def to_pico_contract(self) -> dict[str, Any]:
        """Convert SuperValue internal model to exact PICO Scraper Data Contract."""
        # Convert Decimal prices to integer cents (never floats)
        current_cents = int(round(float(self.price_nzd) * 100)) if self.price_nzd is not None else None

        comp_cents = None
        multibuy_qty = None
        multibuy_cents = None
        promo_text = None
        promo_type = None
        promo_meta = {}

        if self.promotion:
            if self.promotion.previous_price_nzd is not None:
                comp_cents = int(round(float(self.promotion.previous_price_nzd) * 100))
                promo_type = "special"
                if self.promotion.savings_nzd is not None:
                    promo_meta["savings_cents"] = int(round(float(self.promotion.savings_nzd) * 100))
                    promo_text = f"Save ${(float(self.promotion.savings_nzd)):.2f}"
                else:
                    promo_text = "Special"

            if self.promotion.multibuy_quantity and self.promotion.multibuy_price_nzd:
                multibuy_qty = self.promotion.multibuy_quantity
                multibuy_cents = int(round(float(self.promotion.multibuy_price_nzd) * 100))
                promo_type = "multibuy_fixed_price"
                promo_text = f"{multibuy_qty} for ${float(self.promotion.multibuy_price_nzd):.2f}"
                promo_meta["multibuy"] = {
                    "quantity": multibuy_qty,
                    "price_cents": multibuy_cents,
                }

        unit_cents = int(round(float(self.unit_price_nzd) * 100)) if self.unit_price_nzd is not None else None

        # Build clean category path string e.g. "Bakery > Bread > Bread, Buns, Rolls"
        cat_path_str = None
        if self.category_paths:
            primary_path = self.category_paths[0]
            cat_path_str = " > ".join(primary_path)

        # Stock status standard: in_stock / out_of_stock
        st = "in_stock"
        if self.availability == "out_of_stock":
            st = "out_of_stock"

        rec = {
            "source_product_id": self.product_id or (self.sku or ""),
            "retailer_sku": self.sku or self.product_id or "",
            "barcode": self.gtin,
            "raw_name": self.name,
            "clean_name": self.name,
            "brand": self.brand,
            "category_path": cat_path_str,
            "size": self.pricing_unit,
            "current_price_cents": current_cents,
            "comparison_price_cents": comp_cents,
            "unit_price_cents": unit_cents,
            "unit_label": self.unit_price_basis,
            "stock_status": st,
            "promo_text": promo_text,
            "promo_type": promo_type,
            "card_required": None,
            "required_loyalty_program_code": None,
            "source_promotion_id": None,
            "multibuy_quantity": multibuy_qty,
            "multibuy_price_cents": multibuy_cents,
            "promo_metadata": promo_meta or None,
            "product_url": self.product_url,
            "image_url": self.image_url,
            "observed_at": self.scraped_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "raw_row": {
                "branch_id": self.branch_id,
                "identity_quality": self.identity_quality,
                "description": self.description,
                "attributes": self.attributes,
            },
        }

        # Clean top-level nulls/empty keys
        out = {}
        for k, v in rec.items():
            if v is not None and v != "":
                out[k] = v
            elif k == "raw_row":
                out[k] = v
        return out


@dataclass
class PageResult:
    products: list[Product] = field(default_factory=list)
    reported_count: Optional[int] = None
    issues: list[str] = field(default_factory=list)
