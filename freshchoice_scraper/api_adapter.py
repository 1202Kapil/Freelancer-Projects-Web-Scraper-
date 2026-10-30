"""Generic verified API adapter for FreshChoice catalogue endpoints."""
from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional, Union
from urllib.parse import urlparse

from models import Branch, Product, PageResult


@dataclass
class APIConfig:
    url_template: str
    items_path: str = "items"
    total_path: Optional[str] = None
    page_start: int = 1
    allowed_hosts: list[str] = field(default_factory=list)
    fields: dict[str, str] = field(default_factory=dict)
    headers_from_env: dict[str, str] = field(default_factory=dict)


def read_api_config(source: Union[str, Path, dict]) -> APIConfig:
    """Read and construct APIConfig from a JSON configuration file or dictionary."""
    if isinstance(source, (str, Path)):
        p = Path(source)
        data = json.loads(p.read_text(encoding="utf-8"))
    elif isinstance(source, dict):
        data = source
    else:
        raise TypeError(f"Expected file path or dict for API config, got {type(source).__name__}")

    valid_fields = {f.name for f in APIConfig.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    return APIConfig(**filtered)


def lookup(data: Any, path: str) -> Any:
    """Lookup nested value using dot notation (e.g. 'data.items.0.id')."""
    if not path or not data:
        return None
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                idx = int(part)
                cur = cur[idx]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if cur is None:
            return None
    return cur


def api_url(cfg: APIConfig, branch: Branch, category_url: str, page: int) -> str:
    """Construct verified API URL ensuring host strictly matches the branch or allowed_hosts."""
    branch_host = urlparse(branch.url).netloc
    cat_slug = category_url.rstrip("/").split("/")[-1].split("?")[0]
    raw_url = cfg.url_template.format(host=branch_host, category_slug=cat_slug, page=page)
    parsed = urlparse(raw_url)

    if parsed.scheme != "https" or (parsed.netloc != branch_host and parsed.netloc not in cfg.allowed_hosts):
        raise ValueError(f"HTTPS branch host mismatch or unauthorized external host: {parsed.netloc}")

    return raw_url


def parse_api_page(payload: dict[str, Any], cfg: APIConfig, branch: Branch,
                   category_path: list[str], request_url: str) -> PageResult:
    """Parse JSON API response page into PageResult containing Products."""
    items = lookup(payload, cfg.items_path) or []
    total = lookup(payload, cfg.total_path) if cfg.total_path else len(items)

    products = []
    field_map = cfg.fields

    for item in items:
        pid = str(lookup(item, field_map.get("product_id", "id")) or "")
        name = str(lookup(item, field_map.get("name", "name")) or "")
        raw_price = lookup(item, field_map.get("price", "price"))
        price_nzd = Decimal(str(raw_price)) if raw_price is not None else None

        brand = lookup(item, field_map.get("brand", "brand"))
        if isinstance(brand, dict):
            brand = brand.get("name")
        brand = str(brand) if brand else None

        img = lookup(item, field_map.get("image_url", "image"))
        if img and str(img).startswith("/"):
            img = f"{branch.url.rstrip('/')}{img}"

        in_stock = lookup(item, field_map.get("availability", "in_stock"))
        if in_stock is False or str(in_stock).lower() in ("false", "out_of_stock"):
            avail = "out_of_stock"
        else:
            avail = "in_stock"

        p = Product(
            branch_id=branch.id,
            branch_name=branch.name,
            product_id=pid,
            product_key=f"id:{pid}",
            identity_quality="source_id",
            name=name,
            brand=brand,
            category_paths=[category_path],
            price_nzd=price_nzd,
            availability=avail,
            image_url=img,
            product_url=f"{branch.url.rstrip('/')}/lines/{pid}",
        )
        products.append(p)

    return PageResult(products=products, reported_count=int(total) if total is not None else len(products))
