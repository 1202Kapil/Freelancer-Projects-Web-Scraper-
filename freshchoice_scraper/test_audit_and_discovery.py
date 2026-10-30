"""Audit, Discovery, Normalization & End-to-end integration tests for FreshChoice."""
import importlib.util
import json
from decimal import Decimal
from pathlib import Path
import httpx
import pytest

from models import Branch, Product, PageResult
from discovery import parse_branches, parse_categories, enrich_branch_from_browse
from normalize import prices, unit_price_from_text, identity, merge_product
from parsers import parse_listing, enrich_from_detail
from runner import Scraper, CrawlOptions
from network import Fetcher, AccessRestricted, RequestBudgetExceeded

F = Path(__file__).parent / "fixtures"
def f(name: str) -> str:
    return (F / name).read_text(encoding="utf-8")

MERIVALE = Branch(id="merivale", name="Merivale", url="https://merivale.store.freshchoice.co.nz")
URL = MERIVALE.url + "/category/bakery"
HTML = f("live_promo_cards.html")

S = Path(__file__).parent / "examples" / "audit_recovered_data.py"
spec = importlib.util.spec_from_file_location("audit_recovered_data", S)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def record(name, category="Groceries", quality="source_id", pid="123", url="https://merivale.store.freshchoice.co.nz/lines/1"):
    return {
        "name": name,
        "identity_quality": quality,
        "product_id": pid,
        "product_url": url,
        "product_key": ("id:" + pid if pid else "name:" + name),
        "category_paths": [[category]],
        "image_url": None,
        "price_nzd": "3.00",
        "attributes": {"source_identifier_type": "storefront_line_id"} if pid else {},
    }


def test_audit_distinguishes_verified_and_weak_product_records():
    rows = [record("Bread"), record("250mL", "Snacks", "name_fallback", None, None)]
    out = audit.summarize(rows)
    assert out["records"] == 2
    assert out["grocery_product_records"] == 1
    assert out["identity_quality"]["name_fallback"] == 1
    assert out["missing_fields"]["product_url"] == 1
    assert out["unit_only_name_count"] == 1
    assert out["source_identifier_provenance"]["storefront_line_id"] == 1


def test_audit_flags_new_weak_records_and_baseline_missing_grocery_paths(tmp_path):
    base = tmp_path / "pilot"
    base.mkdir()
    recovered = tmp_path / "recovered"
    recovered.mkdir()
    (base / "merivale.jsonl").write_text(json.dumps(record("Eggs", "Eggs")) + "\n")
    weak = record("each", "Snacks", "name_fallback", None, None)
    (recovered / "merivale.jsonl").write_text("\n".join([json.dumps(record("Eggs", "Eggs")), json.dumps(weak)]) + "\n")
    (recovered / "recovery_summary.json").write_text(
        json.dumps({
            "branches": [
                {
                    "branch": "merivale",
                    "previous_groceries_count": 0,
                    "previous_reported_groceries_total": 100,
                    "grocery_union_count": 70,
                }
            ]
        })
    )
    result = audit.run(base, recovered, ["merivale"])["branches"][0]
    assert result["added_weak_name_only"] == 1
    assert len(result["notes"]) == 2


def test_all_five_audit_pattern_cards_extracted_without_url_collisions():
    results = parse_listing(HTML, MERIVALE, ["Bakery"], URL)
    assert results.reported_count == 5
    assert results.issues == []
    assert len(results.products) == 5
    assert len({p.product_url for p in results.products}) == 5
    assert len({p.product_key for p in results.products}) == 5


def test_promotional_badges_do_not_hide_product_cards_or_corrupt_prices():
    results = parse_listing(HTML, MERIVALE, ["Bakery"], URL)
    by_url = {p.product_url.rsplit("/", 1)[-1]: p for p in results.products}
    bagels = by_url["abe-s-bagels-everything-4-pack"]
    assert bagels.name == "Abes Bagels Everything 4 Pack"
    assert bagels.price_nzd == Decimal("5.80")
    assert bagels.promotion.previous_price_nzd == Decimal("7.10")
    assert bagels.promotion.savings_nzd == Decimal("1.30")
    assert bagels.image_url == "https://images.test/abe.jpg"
    wraps = by_url["farrah-wraps-garden-spinach-6-pack"]
    assert wraps.name == "Farrahs Wraps Garden Spinach 6 Pack"
    assert wraps.price_nzd == Decimal("5.50")
    assert wraps.promotion.savings_nzd == Decimal("2.30")


def test_trailing_price_removed_from_display_name_but_two_urls_stay_distinct():
    results = parse_listing(HTML, MERIVALE, ["Bakery"], URL)
    muffins = [p for p in results.products if p.name == "Muffins Texas Loose"]
    assert len(muffins) == 2
    assert all(p.price_nzd == Decimal("3.50") for p in muffins)
    assert muffins[0].product_key != muffins[1].product_key
    scroll = next(p for p in results.products if "savoury-scrolls" in p.product_url)
    assert scroll.name == "Savoury Scrolls"
    assert scroll.price_nzd == Decimal("3.90")


def test_dom_line_id_recorded_with_transparent_source_type_not_as_gtin():
    results = parse_listing(HTML, MERIVALE, ["Bakery"], URL)
    bagels = next(p for p in results.products if "everything" in p.product_url)
    assert bagels.product_id == "5e45a6f6f605cc6df10f3bb8"
    assert bagels.identity_quality == "source_id"
    assert bagels.attributes["source_identifier_type"] == "storefront_line_id"
    assert bagels.sku is None and bagels.gtin is None


def test_conflicting_dom_and_quantity_control_ids_not_falsely_assigned():
    broken = HTML.replace('5e45a6f6f605cc6df10f3bb8"}}', '000000000000000000000000"}}', 1)
    results = parse_listing(broken, MERIVALE, ["Bakery"], URL)
    bagels = next(p for p in results.products if "everything" in p.product_url)
    assert bagels.product_id is None
    assert bagels.identity_quality == "url"
    assert bagels.attributes["source_identifier_type"] == "line_dom_id_conflicts_with_control"


def test_missing_card_is_explicitly_reported_for_review():
    broken = HTML.replace("<span>$3.50 each</span>", "<span>Price on request</span>", 1)
    broken = broken.replace("Muffins Texas Loose $3.50", "Muffins Texas Loose", 2)
    results = parse_listing(broken, MERIVALE, ["Bakery"], URL)
    assert len(results.products) == 5
    assert sum(p.price_nzd is None for p in results.products) == 1
    assert any("no extractable individual price" in issue for issue in results.issues)


def test_discover_selector():
    stores = parse_branches(f("selector.html"))
    assert [b.id for b in stores] == ["epsom", "fendalton", "merivale"]
    assert next(b for b in stores if b.id == "merivale").shopping_online is True
    assert next(b for b in stores if b.id == "fendalton").shopping_online is False
    assert "Papanui" in next(b for b in stores if b.id == "merivale").address
    assert len(parse_branches(f("selector.html"), include_supervalue=True)) == 4


def test_categories():
    result = parse_categories(f("browse.html"), MERIVALE.url)
    assert list(result) == ["Bakery", "Groceries", "Fruit & Vegetables"]
    assert result["Bakery"] == "https://merivale.store.freshchoice.co.nz/category/bakery"


def test_promotions_and_units():
    p = prices("save 71c was $5.40 $4.69 each $1.12 per 100g")
    assert p == (Decimal("4.69"), Decimal("5.40"), Decimal("0.71"), "each", "per 100g")
    assert unit_price_from_text("was $5.40 $4.69 each $1.12 per 100g") == Decimal("1.12")
    p2 = prices("$5.60 per kg")
    assert p2[0] == Decimal("5.60") and p2[3] == "per kg"
    assert p2[4] is None


def test_product_fields():
    parsed = parse_listing(f("bakery1.html"), MERIVALE, ["Bakery"], MERIVALE.url + "/category/bakery")
    assert parsed.reported_count == 3 and len(parsed.products) == 2
    one = next(p for p in parsed.products if p.product_id == "B101")
    assert one.price_nzd == Decimal("5.75")
    assert one.unit_price_nzd == Decimal("0.77")
    assert one.availability == "in_stock"
    assert one.image_url == "https://images.example.net/b101.jpg"
    special = next(p for p in parsed.products if p.product_id == "B102")
    assert special.promotion.on_special
    assert special.promotion.previous_price_nzd == Decimal("5.40")
    assert special.promotion.savings_nzd == Decimal("0.71")


def test_weighted_stock():
    item = parse_listing(f("bakery2.html"), MERIVALE, ["Bakery"], MERIVALE.url + "/category/bakery?page=2").products[0]
    assert item.pricing_unit == "per kg"
    assert item.price_nzd == Decimal("5.60")
    assert item.availability == "out_of_stock"


def test_missing_id_not_misrepresented():
    key, quality = identity("merivale", "A Name", None, None)
    assert key.startswith("name:") and quality == "name_fallback"


def test_jsonld():
    html = """<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",
 "name":"Milk 2L", "sku":"M22", "brand":{"name":"Farm"},
 "image":"/milk.jpg", "offers":{"price":"4.65","availability":"https://schema.org/InStock"}}</script>"""
    item = parse_listing(html, MERIVALE, ["Dairy"], MERIVALE.url + "/category/dairy").products[0]
    assert item.name == "Milk 2L" and item.product_id is None and item.sku == "M22" and item.brand == "Farm"
    assert item.price_nzd == Decimal("4.65") and item.availability == "in_stock"


def test_text_only_fallback_marked_partial():
    parsed = parse_listing(f("text_only.html"), MERIVALE, ["Bakery"], MERIVALE.url + "/category/bakery")
    assert parsed.reported_count == 3 and len(parsed.products) == 3
    assert "fallback" in str(parsed.issues)
    assert all(p.identity_quality == "name_fallback" for p in parsed.products)


def test_detail_enrichment_without_guessing_id():
    item = parse_listing(f("bakery1.html"), MERIVALE, ["Bakery"], MERIVALE.url + "/category/bakery").products[0]
    item.image_url = None
    html = """<html><head><meta property="og:image" content="/media/bread.jpg"></head>
    <body><h1>Vogels Bread Original Mixed Grain Toast 750g</h1>
    <div class="product-description">A substantial mixed grain toast loaf.</div>
    <div itemprop="brand" content="Vogels"></div></body></html>"""
    enrich_from_detail(html, MERIVALE, item)
    assert item.product_id == "B101"
    assert item.brand == "Vogels" and "mixed grain toast loaf" in item.description
    assert item.image_url == MERIVALE.url + "/media/bread.jpg"


def test_branch_contacts_hours():
    branch = Branch(id="merivale", name="Merivale", url=MERIVALE.url)
    html = """<html><body><footer><h3>Opening hours</h3><p>Monday</p><p>7:00 am - 9:00 pm</p>
      <p>Tuesday</p><p>7:00 am - 9:00 pm</p><h3>Contact</h3>
      <a href="tel:+6433554432">03 355 4432</a>
      <a href="mailto:test@merivale.example">Send email</a></footer></body></html>"""
    enrich_branch_from_browse(branch, html)
    assert branch.phone == "+6433554432" and branch.email == "test@merivale.example"
    assert branch.opening_hours["Monday"] == "7:00 am - 9:00 pm"


# ---------------------------------------------------------------------------
# Runner Tests
# ---------------------------------------------------------------------------

def _products(start, n):
    return [
        Product(
            branch_id="merivale",
            branch_name="Merivale",
            product_id=str(i),
            product_key=f"id:merivale:{i}",
            identity_quality="source_id",
            name=f"Test Item {i}",
            price_nzd=Decimal("2.50"),
            product_url=f"https://merivale.store.freshchoice.co.nz/lines/item-{i}",
        )
        for i in range(start, start + n)
    ]


@pytest.mark.asyncio
async def test_interior_short_page_does_not_terminate_category(tmp_path):
    calls = []

    def mock(req):
        return httpx.Response(200, text='<a href="/category/household">Household</a>', headers={"content-type": "text/html"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        scraper = Scraper(Fetcher(client, rate_per_host=10000, max_retries=0), CrawlOptions(output_dir=str(tmp_path)))

        async def page(branch, category, url, number):
            calls.append(number)
            batches = {1: _products(0, 48), 2: _products(48, 47), 3: _products(95, 13)}
            return PageResult(products=batches.get(number, []), reported_count=108)

        scraper._page = page
        result = await scraper.scrape_branch(MERIVALE)
    assert calls == [1, 2, 3]
    assert result.status == "complete"
    assert result.products == 108
    assert result.pages_fetched == 3


@pytest.mark.asyncio
async def test_duplicate_occurrence_counted_only_once(tmp_path):
    def mock(req):
        return httpx.Response(200, text='<a href="/category/groceries">Groceries</a>', headers={"content-type": "text/html"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        scraper = Scraper(Fetcher(client, rate_per_host=10000, max_retries=0), CrawlOptions(output_dir=str(tmp_path)))

        async def page(branch, category, url, number):
            if number == 1:
                return PageResult(products=_products(0, 2), reported_count=3)
            if number == 2:
                return PageResult(products=[_products(1, 1)[0], _products(2, 1)[0]], reported_count=3)
            return PageResult()

        scraper._page = page
        result = await scraper.scrape_branch(MERIVALE)
    assert result.products == 3
    assert result.duplicates == 1
    assert result.status == "complete"


@pytest.mark.asyncio
async def test_category_filter_is_diagnostic_not_complete(tmp_path):
    def mock(req):
        return httpx.Response(200, text='<a href="/category/bakery">Bakery</a><a href="/category/groceries">Groceries</a>', headers={"content-type": "text/html"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        scraper = Scraper(Fetcher(client, rate_per_host=10000, max_retries=0), CrawlOptions(output_dir=str(tmp_path), category_names=["Groceries"]))

        async def page(branch, category, url, number):
            assert category == "Groceries"
            return PageResult(products=_products(0, 1), reported_count=1)

        scraper._page = page
        result = await scraper.scrape_branch(MERIVALE)
    assert result.categories_discovered == 2
    assert result.categories_scraped == 1
    assert result.status == "partial"
    assert "diagnostic" in " ".join(result.issues)


@pytest.mark.asyncio
async def test_count_ceil_estimate_does_not_end_pagination(tmp_path):
    calls = []

    def mock(req):
        return httpx.Response(200, text='<a href="/category/household">Household</a>', headers={"content-type": "text/html"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        scraper = Scraper(Fetcher(client, rate_per_host=10000, max_retries=0), CrawlOptions(output_dir=str(tmp_path)))

        async def page(branch, category, url, number):
            calls.append(number)
            batches = {1: _products(0, 5), 2: _products(5, 1), 3: _products(6, 1)}
            return PageResult(products=batches.get(number, []), reported_count=7)

        scraper._page = page
        result = await scraper.scrape_branch(MERIVALE)
    assert calls == [1, 2, 3]
    assert result.status == "complete"
    assert result.products == 7


# End to End Mock
def end_to_end_mock(req):
    path = req.url.path
    host = req.url.host
    if host == "store.freshchoice.co.nz":
        return httpx.Response(200, text=f("selector.html"), headers={"content-type": "text/html"})
    if path == "/browse":
        return httpx.Response(200, text=f("browse.html"), headers={"content-type": "text/html"})
    name = path.removeprefix("/category/")
    page = req.url.params.get("page", "1")
    filename = "bakery" + page + ".html" if name == "bakery" else "groceries1.html" if name == "groceries" else None
    if filename and (F / filename).exists():
        return httpx.Response(200, text=(F / filename).read_text(encoding="utf-8"), headers={"content-type": "text/html"})
    if name == "fresh":
        return httpx.Response(200, text="<h1>Fresh</h1><p>Refine 0 results</p>", headers={"content-type": "text/html"})
    return httpx.Response(404)


@pytest.mark.asyncio
async def test_end_to_end_two_branches(tmp_path):
    async with httpx.AsyncClient(transport=httpx.MockTransport(end_to_end_mock)) as client:
        fetcher = Fetcher(client, rate_per_host=10000, max_retries=0)
        opts = CrawlOptions(branch_names=["merivale", "epsom"], output_dir=str(tmp_path), branch_concurrency=2)
        summary = await Scraper(fetcher, opts).run()
    assert summary.branches_discovered == 3
    assert summary.branches_selected == 2
    assert summary.branches_completed == 2
    assert summary.total_unique_products == 8
    assert (tmp_path / "merivale.jsonl").exists()
    records = [json.loads(x) for x in (tmp_path / "merivale.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(records) == 4
    assert len({p["product_key"] for p in records}) == 4
    pita = next(x for x in records if x["product_id"] == "B102")
    assert {tuple(x) for x in pita["category_paths"]} == {("Bakery",), ("Groceries",)}
    assert (tmp_path / "summary.json").exists()
    assert summary.elapsed_seconds >= 0


@pytest.mark.asyncio
async def test_capped_pages_mark_partial(tmp_path):
    async with httpx.AsyncClient(transport=httpx.MockTransport(end_to_end_mock)) as client:
        opts = CrawlOptions(branch_names=["merivale"], output_dir=str(tmp_path), max_pages_per_category=1)
        summary = await Scraper(Fetcher(client, rate_per_host=10000, max_retries=0), opts).run()
    assert summary.branches_partial == 1
    assert summary.total_unique_products == 3
    assert "limited" in str(summary.branch_results[0].issues)


@pytest.mark.asyncio
async def test_403_not_retried():
    calls = []

    def forbidden(req):
        calls.append(str(req.url))
        return httpx.Response(403)

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        with pytest.raises(AccessRestricted):
            await Fetcher(client, rate_per_host=10000, max_retries=2).get("https://merivale.store.freshchoice.co.nz/browse")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_max_request_budget():
    async with httpx.AsyncClient(transport=httpx.MockTransport(end_to_end_mock)) as client:
        fetcher = Fetcher(client, rate_per_host=10000, max_requests=1, max_retries=0)
        await fetcher.get("https://store.freshchoice.co.nz/")
        with pytest.raises(RequestBudgetExceeded):
            await fetcher.get("https://store.freshchoice.co.nz/")
