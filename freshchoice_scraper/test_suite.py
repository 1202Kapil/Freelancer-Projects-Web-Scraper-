"""Comprehensive verification test suite for FreshChoice NZ Scraper."""
from decimal import Decimal
import json
from pathlib import Path
import pytest
import httpx
import argparse

from models import Branch, Product, Promotion, PageResult
from network import Fetcher
from parsers import parse_listing, is_valid_gtin_checksum, parse_multibuy
import parsers
from api_adapter import APIConfig, api_url, parse_api_page, lookup
from recover import (
    safe_category_url, sitemap_categories, rendered_children,
    snapshot_children, index_product, recover_branch,
)
from enrich import enrich_output
from storage import write_json, write_jsonl
from runner import Scraper
from jsonl_exporter import to_cents, clean_record
from validate_export import validate_record

HOST = "merivale.store.freshchoice.co.nz"
BASE = "https://" + HOST
BR = Branch(id="merivale", name="Merivale", url=BASE)
URL = BR.url + "/category/bakery?page=10"
FIXTURE = (Path(__file__).parent / "fixtures" / "live_promo_cards.html").read_text()


def product(num, parent=False):
    return Product(
        branch_id="merivale",
        branch_name="Merivale",
        product_id=str(num),
        product_key=f"id:{num}",
        identity_quality="source_id",
        name=f"Item {num}",
        price_nzd=Decimal("2.00"),
        product_url=f"{BASE}/lines/item-{num}",
        category_paths=[["Groceries"]] if parent else [["Breakfast Foods"]],
    )


# ---------------------------------------------------------------------------
# API Adapter Tests
# ---------------------------------------------------------------------------

def test_lookup_and_api_mapping():
    cfg = APIConfig(
        url_template="https://{host}/api/catalogue?category={category_slug}&page={page}",
        items_path="data.items",
        total_path="data.total",
        fields={
            "product_id": "id",
            "name": "name",
            "price": "price.amount",
            "brand": "brand.name",
            "image_url": "image",
            "availability": "in_stock",
        },
    )
    url = api_url(cfg, BR, BR.url + "/category/bakery", 2)
    assert "page=2" in url and "category=bakery" in url
    payload = {
        "data": {
            "total": 1,
            "items": [
                {
                    "id": "010101",
                    "name": "Bread",
                    "price": {"amount": 3.70},
                    "brand": {"name": "Good Food"},
                    "in_stock": False,
                    "image": "/pic.png",
                }
            ],
        }
    }
    output = parse_api_page(payload, cfg, BR, ["Bakery"], url)
    assert output.reported_count == 1
    prod = output.products[0]
    assert prod.product_id == "010101" and prod.price_nzd == Decimal("3.70")
    assert prod.brand == "Good Food" and prod.availability == "out_of_stock"
    assert prod.image_url == BR.url + "/pic.png"
    assert lookup(payload, "data.items.0.id") == "010101"


def test_refuse_unconfigured_external_api_host():
    cfg = APIConfig(url_template="https://outside.example/api?category={category_slug}&page={page}", items_path="items")
    with pytest.raises(ValueError, match="HTTPS branch host"):
        api_url(cfg, BR, BR.url + "/category/bakery", 1)


# ---------------------------------------------------------------------------
# Enrichment & Access Denial Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enrichment_preserves_baseline_and_stops_on_access_denial(tmp_path, monkeypatch):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    base = "https://epsom.store.freshchoice.co.nz"
    write_json(src / "branches.json", [{"id": "epsom", "name": "Epsom", "url": base}])
    write_json(src / "summary.json", {"elapsed_seconds": 1, "total_unique_products": 2, "branch_results": [{"branch_id": "epsom", "products": 2, "requests_failed": 0, "status": "partial"}]})
    rows = [Product(branch_id="epsom", branch_name="Epsom", product_id=str(i), product_key=f"id:{i}", identity_quality="source_id", name=f"Bread {i}", product_url=f"{base}/lines/{i}") for i in range(2)]
    write_jsonl(src / "epsom.jsonl", rows)
    before = (src / "epsom.jsonl").read_bytes()
    calls = []

    def mock(req):
        calls.append(req.url)
        return httpx.Response(403)

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(mock), **kw))
    result = await enrich_output(argparse.Namespace(input_dir=str(src), output_dir=str(dst), branch_concurrency=2, rate_per_host=10000, max_details=0))
    assert result == 1 and len(calls) == 1
    assert (src / "epsom.jsonl").read_bytes() == before
    assert len((dst / "epsom.jsonl").read_text().splitlines()) == 2
    assert "AccessRestricted" in (dst / "enrichment_summary.json").read_text()


# ---------------------------------------------------------------------------
# HTML Parser & Quality Regression Tests
# ---------------------------------------------------------------------------

def test_short_final_page_does_not_supplement_real_products(monkeypatch):
    html = FIXTURE.replace("Refine 5 results", "Refine 472 results")

    def bogus(*args):
        raise AssertionError("weak fallback must never run alongside real cards")

    monkeypatch.setattr(parsers, "_text_stream_products", bogus)
    batch = parse_listing(html, BR, ["Bakery"], URL)
    assert len(batch.products) == 5
    assert all(p.product_url for p in batch.products)
    assert all(p.identity_quality != "name_fallback" for p in batch.products)


def test_incomplete_real_card_is_reported_not_guessed(monkeypatch):
    html = FIXTURE.replace("Refine 5 results", "Refine 472 results")
    html = html.replace("<span>$3.50 each</span>", "<span>Price on request</span>", 1)
    html = html.replace("Muffins Texas Loose $3.50", "Muffins Texas Loose", 2)

    def bogus(*args):
        raise AssertionError("weak fallback must not conceal missing card")

    monkeypatch.setattr(parsers, "_text_stream_products", bogus)
    batch = parse_listing(html, BR, ["Bakery"], URL)
    assert len(batch.products) == 5
    assert sum(p.price_nzd is None for p in batch.products) == 1
    assert any("no extractable individual price" in i for i in batch.issues)


def test_real_text_only_page_remains_explicitly_partial():
    html = (Path(__file__).parent / "fixtures" / "text_only.html").read_text()
    batch = parse_listing(html, BR, ["Bakery"], URL)
    assert len(batch.products) == 3
    assert all(p.identity_quality == "name_fallback" for p in batch.products)
    assert any("text-only" in i for i in batch.issues)


# ---------------------------------------------------------------------------
# Category Recovery & URL Safety Tests
# ---------------------------------------------------------------------------

def test_same_host_canonicalization():
    assert safe_category_url("/category/breakfast-foods?page=2", HOST) == BASE + "/category/breakfast-foods"
    assert safe_category_url("https://evil.example/category/breakfast-foods", HOST) is None
    assert safe_category_url("/admin", HOST) is None
    assert safe_category_url("/category/bakery/item", HOST) is None


def test_sitemap_lists_categories_but_not_external_domains():
    xml = f"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>{BASE}/category/groceries</loc></url>
    <url><loc>{BASE}/category/breakfast-foods</loc></url>
    <url><loc>https://wrong.example/category/groceries</loc></url></urlset>"""
    assert sitemap_categories(xml.encode(), HOST) == {BASE + "/category/groceries", BASE + "/category/breakfast-foods"}


def test_rendered_filters_primary_nav_and_pagination():
    html = """<div class="fc-nav"><a class="fc-nav__link" href="/category/bakery">Bakery</a></div>
    <a href="/category/breakfast-foods">Breakfast Foods</a>
    <nav class="mfl-pagination"><a href="/category/groceries?page=2">2</a></nav>
    <a href="https://wrong.example/category/rice">Outside</a>"""
    assert rendered_children(html, HOST, BASE + "/category/groceries") == {
        BASE + "/category/breakfast-foods": "Breakfast Foods"
    }


def test_snapshot_finds_grandchildren_and_rejects_cross_branch():
    allowed = {BASE + "/category/bakery", BASE + "/category/breakfast-foods"}
    snap = {
        "branch": "merivale",
        "host": HOST,
        "browser": {
            "status": 200,
            "category_links": [
                {"path": "/category/bakery", "label": "Bakery"},
                {"path": "/category/breakfast-foods", "label": "Breakfast Foods"},
            ],
        },
    }
    assert snapshot_children(snap, HOST, BASE + "/category/groceries", allowed) == {
        BASE + "/category/breakfast-foods": "Breakfast Foods"
    }
    with pytest.raises(ValueError):
        snapshot_children(snap, "epsom.store.freshchoice.co.nz", BASE + "/category/groceries", allowed)


def test_merges_by_product_url_without_duplicate():
    products = {"id:1": product(1)}
    url_index = {"/lines/item-1": "id:1"}
    other = product(1)
    other.product_id = None
    other.product_key = "url:/lines/item-1"
    other.identity_quality = "url"
    other.category_paths = [["Groceries", "Breakfast Foods"]]
    assert not index_product(products, url_index, other)
    assert len(products) == 1
    assert ["Groceries", "Breakfast Foods"] in products["id:1"].category_paths


@pytest.mark.asyncio
async def test_recover_merges_baseline_and_counts_real_union(tmp_path, monkeypatch):
    baseline = tmp_path / "output-pilot"
    baseline.mkdir()
    write_jsonl(baseline / "merivale.jsonl", [product(1, True), product(2, True)])
    snapshot_dir = tmp_path / "output-taxonomy"
    snapshot_dir.mkdir()
    (snapshot_dir / "merivale.json").write_text(
        json.dumps({
            "branch": "merivale",
            "host": HOST,
            "browser": {
                "status": 200,
                "category_links": [
                    {"path": "/category/bakery", "label": "Bakery"},
                    {"path": "/category/breakfast-foods", "label": "Breakfast Foods"},
                ],
            },
        })
    )

    def mock(req):
        if req.url.path == "/sitemap.xml":
            return httpx.Response(200, text=f"<urlset><url><loc>{BASE}/category/breakfast-foods</loc></url></urlset>")
        raise AssertionError(str(req.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        fetcher = Fetcher(client, rate_per_host=10000, max_retries=0)

        async def pages(self, branch, category, url, page):
            assert category == "Breakfast Foods"
            return PageResult(products=[product(2), product(3), product(4)] if page == 1 else [], reported_count=3)

        monkeypatch.setattr(Scraper, "_page", pages)
        report = await recover_branch(
            {"branch_id": "merivale", "branch_name": "Merivale", "issues": ["Groceries: extracted 2/4 unique items"]},
            input_dir=baseline,
            output_dir=tmp_path / "out",
            fetcher=fetcher,
            snapshot_dir=snapshot_dir,
        )
    assert report["status"] == "reconciled"
    assert report["original_products"] == 2
    assert report["merged_products"] == 4
    assert report["new_products"] == 2
    assert report["grocery_union_count"] == 4
    assert len((tmp_path / "out" / "merivale.jsonl").read_text().splitlines()) == 4


# ---------------------------------------------------------------------------
# PICO Common Contract & Multibuy Regression Tests
# ---------------------------------------------------------------------------

def test_pico_common_contract_validation():
    # Green Island Multibuy regression check
    p = Product(
        branch_id="greenisland",
        branch_name="Green Island",
        product_id="ocean-blue-salmon",
        name="Ocean Blue Salmon Smoked Cooking Pieces",
        price_nzd=Decimal("9.30"),
        pricing_unit="125g",
        product_url="https://greenisland.store.freshchoice.co.nz/lines/ocean-blue-salmon",
        promotion=Promotion(
            on_special=True,
            previous_price_nzd=Decimal("9.50"),
            savings_nzd=Decimal("0.20"),
            multibuy_quantity=3,
            multibuy_price_nzd=Decimal("25.00"),
        ),
        availability="in_stock",
    )
    contract_rec = p.to_pico_contract()

    # Rule 1: Prices in integer cents
    assert contract_rec["current_price_cents"] == 930
    assert contract_rec["comparison_price_cents"] == 950
    assert contract_rec["multibuy_quantity"] == 3
    assert contract_rec["multibuy_price_cents"] == 2500
    assert contract_rec["stock_status"] == "in_stock"

    # Rule 2: Clean record passes PICO audit
    clean = clean_record(contract_rec)
    errs, has_gtin, has_chk = validate_record(clean, line_no=1)
    assert len(errs) == 0, f"PICO validation errors: {errs}"


def test_gs1_checksum_verification():
    assert is_valid_gtin_checksum("9400559000017") is True
    assert is_valid_gtin_checksum("9400559000011") is False
    # Produce PLUs must not be treated as GTIN
    assert is_valid_gtin_checksum("4011") is False
    assert is_valid_gtin_checksum("4224") is False
