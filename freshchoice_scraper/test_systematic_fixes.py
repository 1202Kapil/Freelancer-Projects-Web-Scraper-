"""Targeted validation tests for all 7 systematic fixes in FreshChoice Scraper."""
import json
from decimal import Decimal
from pathlib import Path
import re
import pytest
import httpx

from api_adapter import APIConfig, read_api_config
from network import Fetcher, RequestBudgetExceeded
from config import CATEGORIES, CATEGORY_ALIASES
from parsers import parse_product_detail_page, normalize_image_url, parse_product_card
from models import Product, Branch, Promotion
from import_products import RETAILER_FILE_PREFIX, _EXPORT_FILENAME_RE
from jsonl_exporter import clean_record
from validate_export import validate_record


# ---------------------------------------------------------------------------
# ISSUE 1: read_api_config & CrawlOptions
# ---------------------------------------------------------------------------

def test_issue1_read_api_config_from_dict_and_file(tmp_path):
    config_dict = {
        "url_template": "https://{host}/api/v1/catalogue?cat={category_slug}&page={page}",
        "items_path": "results.products",
        "total_path": "results.total_count",
        "page_start": 1,
        "allowed_hosts": ["merivale.store.freshchoice.co.nz"],
        "fields": {"product_id": "item_code", "name": "title"},
    }
    # Test from dict
    cfg1 = read_api_config(config_dict)
    assert isinstance(cfg1, APIConfig)
    assert cfg1.url_template == config_dict["url_template"]
    assert cfg1.items_path == "results.products"
    assert cfg1.total_path == "results.total_count"
    assert cfg1.allowed_hosts == ["merivale.store.freshchoice.co.nz"]

    # Test from JSON file
    cfg_file = tmp_path / "api_test.json"
    cfg_file.write_text(json.dumps(config_dict), encoding="utf-8")
    cfg2 = read_api_config(cfg_file)
    assert isinstance(cfg2, APIConfig)
    assert cfg2.url_template == config_dict["url_template"]
    assert cfg2.fields == {"product_id": "item_code", "name": "title"}

    # Test CrawlOptions accommodates all CLI arguments
    from runner import CrawlOptions
    opts = CrawlOptions(
        output_dir="output",
        branch_names=["merivale"],
        branch_concurrency=2,
        max_categories=5,
        max_pages_per_category=10,
        rate_per_host=0.5,
        include_supervalue=True,
        mode="api",
        api_config=cfg2,
        enrich_details=True,
        max_details=25,
        category_names=["bakery"],
    )
    assert opts.mode == "api"
    assert opts.max_categories == 5
    assert opts.include_supervalue is True
    assert opts.api_config == cfg2


# ---------------------------------------------------------------------------
# ISSUE 2: Fetcher per_host_concurrency & rate limiting
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_issue2_fetcher_per_host_concurrency_and_limits():
    def mock_handler(req):
        return httpx.Response(200, text="OK")

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_handler)) as client:
        # 1. Accepts per_host_concurrency without error
        fetcher = Fetcher(
            client=client,
            rate_per_host=500.0,
            per_host_concurrency=3,
            max_retries=1,
            max_requests=5,
        )
        assert fetcher.per_host_concurrency == 3
        assert fetcher.max_requests == 5

        # 2. Can issue requests
        resp = await fetcher.get("https://example.com/1")
        assert resp.status_code == 200
        assert fetcher.request_count == 1

        # 3. Request budget enforcement
        for i in range(2, 6):
            await fetcher.get(f"https://example.com/{i}")
        assert fetcher.request_count == 5

        with pytest.raises(RequestBudgetExceeded):
            await fetcher.get("https://example.com/6")

    # Test max_requests=0 means unlimited
    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_handler)) as client:
        fetcher_unlimited = Fetcher(client=client, rate_per_host=1000.0, per_host_concurrency=2, max_requests=0)
        assert fetcher_unlimited.max_requests is None
        resp = await fetcher_unlimited.get("https://example.com/test")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# ISSUE 3: Psycopg 3 in requirements.txt
# ---------------------------------------------------------------------------

def test_issue3_requirements_declares_psycopg3():
    req_path = Path(__file__).parent / "requirements.txt"
    content = req_path.read_text(encoding="utf-8")
    assert "psycopg[binary]" in content or "psycopg>=" in content
    assert "3." in [line for line in content.splitlines() if "psycopg" in line][0]


# ---------------------------------------------------------------------------
# ISSUE 4: RETAILER_FILE_PREFIX FreshChoice mapping
# ---------------------------------------------------------------------------

def test_issue4_retailer_file_prefix_freshchoice():
    assert "freshchoice" in RETAILER_FILE_PREFIX
    assert RETAILER_FILE_PREFIX["freshchoice"] == "freshchoice"
    assert RETAILER_FILE_PREFIX["fresh-choice"] == "freshchoice"

    # Preserves other retailers without regression
    assert RETAILER_FILE_PREFIX["woolworths"] == "woolworths"
    assert RETAILER_FILE_PREFIX["paknsave"] == "paknsave"
    assert RETAILER_FILE_PREFIX["new-world"] == "newworld"

    # Test filename regex parsing matching import_products.py logic
    sample_filename = "freshchoice_merivale_20261030T045938Z.jsonl"
    m = _EXPORT_FILENAME_RE.match(sample_filename)
    assert m is not None
    prefix_branch = m.group(1)
    timestamp = m.group(2)
    assert timestamp == "20261030T045938Z"

    prefix = RETAILER_FILE_PREFIX["freshchoice"]
    assert prefix_branch.startswith(f"{prefix}_")
    branch_slug = prefix_branch[len(prefix) + 1:]
    assert branch_slug == "merivale"


# ---------------------------------------------------------------------------
# ISSUE 5: Deli category and alias fallbacks
# ---------------------------------------------------------------------------

def test_issue5_deli_in_categories_and_aliases():
    assert "deli" in CATEGORIES
    assert "deli" in CATEGORY_ALIASES
    expected_aliases = ["deli-kitchen", "delicatessen", "deli", "chilled-deli"]
    assert CATEGORY_ALIASES["deli"] == expected_aliases

    # Ensure no duplicates in CATEGORIES
    assert len(CATEGORIES) == len(set(CATEGORIES))


# ---------------------------------------------------------------------------
# ISSUE 6: Detail enrichment preserves GTIN & SKU across Product & PICO contract
# ---------------------------------------------------------------------------

def test_issue6_enrichment_preserves_gtin_and_sku():
    base_record = {
        "source_product_id": "fresh-bread-700g",
        "retailer_sku": "fresh-bread-700g",
        "raw_name": "Bakery Fresh Bread 700g",
        "clean_name": "Bakery Fresh Bread",
        "current_price_cents": 350,
        "stock_status": "in_stock",
        "observed_at": "2026-10-30T10:00:00Z",
        "product_url": "https://merivale.store.freshchoice.co.nz/lines/fresh-bread-700g",
    }
    pdp_html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "Product",
            "name": "Bakery Fresh Bread 700g",
            "gtin13": "9400559000017",
            "sku": "SKU-BAKERY-700",
            "brand": {"@type": "Brand", "name": "FreshChoice Bakery"},
            "description": "Locally baked daily."
        }
        </script>
    </head>
    </html>
    """
    enriched = parse_product_detail_page(pdp_html, base_record)

    # 1. Both canonical and contract fields are present in enriched dict
    assert enriched["gtin"] == "9400559000017"
    assert enriched["barcode"] == "9400559000017"
    assert enriched["sku"] == "SKU-BAKERY-700"
    assert enriched["retailer_sku"] == "SKU-BAKERY-700"
    assert enriched["brand"] == "FreshChoice Bakery"
    assert enriched["description"] == "Locally baked daily."

    # 2. Product.model_validate accepts enriched dict and populates canonical fields
    prod = Product.model_validate(enriched)
    assert prod.gtin == "9400559000017"
    assert prod.sku == "SKU-BAKERY-700"
    assert prod.brand == "FreshChoice Bakery"

    # 3. Product.to_pico_contract exports to valid PICO contract
    pico = prod.to_pico_contract()
    clean = clean_record(pico)
    errors, has_gtin, has_chk = validate_record(clean, line_no=1)
    assert len(errors) == 0
    assert has_gtin is True
    assert has_chk is True
    assert clean["barcode"] == "9400559000017"
    assert clean["retailer_sku"] == "SKU-BAKERY-700"


# ---------------------------------------------------------------------------
# ISSUE 7: Image URL normalization
# ---------------------------------------------------------------------------

def test_issue7_normalize_image_url_variations():
    base_url = "https://merivale.store.freshchoice.co.nz"

    # 1. Root-relative
    assert normalize_image_url("/media/products/apple.jpg", base_url) == f"{base_url}/media/products/apple.jpg"
    assert normalize_image_url("/img.png", f"{base_url}/") == f"{base_url}/img.png"

    # 2. Protocol-relative
    assert normalize_image_url("//cdn.freshchoice.co.nz/logo.png", base_url) == "https://cdn.freshchoice.co.nz/logo.png"

    # 3. Already absolute HTTPS
    assert normalize_image_url("https://images.example.com/milk.jpg", base_url) == "https://images.example.com/milk.jpg"

    # 4. Already absolute HTTP
    assert normalize_image_url("http://images.example.com/milk.jpg", base_url) == "http://images.example.com/milk.jpg"

    # 5. Relative without leading slash
    assert normalize_image_url("assets/bread.jpg", base_url) == f"{base_url}/assets/bread.jpg"

    # 6. Data URI (should return None)
    assert normalize_image_url("data:image/png;base64,iVBORw0KGgo...", base_url) is None

    # 7. Empty or None (should return None)
    assert normalize_image_url(None, base_url) is None
    assert normalize_image_url("", base_url) is None
    assert normalize_image_url("   ", base_url) is None

    # 8. Test parse_product_card with root-relative image
    card_html = """
    <div class="line-item">
        <a href="/lines/golden-apples">Golden Delicious Apples</a>
        <img src="/media/apples.jpg" alt="Golden Delicious Apples" />
        <span class="price">$4.50</span>
    </div>
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(card_html, "html.parser")
    card = soup.find("div")
    parsed = parse_product_card(card, branch_slug="merivale", category_path="Fruit & Vegetables")
    assert parsed is not None
    assert parsed["image_url"] == "https://merivale.store.freshchoice.co.nz/media/apples.jpg"
