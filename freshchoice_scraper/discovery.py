"""Store directory and catalogue category discovery for FreshChoice."""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup

from models import Branch

logger = logging.getLogger(__name__)


def parse_branches(html: str, include_supervalue: bool = False) -> list[Branch]:
    """Parse store selector page HTML into a list of Branch models."""
    soup = BeautifulSoup(html, "html.parser")
    branches = []

    sections = soup.find_all(["section", "div", "article", "li"], class_=re.compile(r"shop-card|store|branch|location", re.I))
    if not sections:
        sections = [a.parent for a in soup.find_all("a", href=re.compile(r"\.store\.freshchoice|\.store\.supervalue", re.I))]

    seen_ids = set()

    for sec in sections:
        links = sec.find_all("a", href=re.compile(r"https?://([^/]+)"))
        if not links:
            continue

        target_link = links[0]
        parsed = urlparse(target_link.get("href", ""))
        netloc = parsed.netloc.lower()

        is_supervalue = "supervalue" in netloc
        if is_supervalue and not include_supervalue:
            continue

        store_id = netloc.split(".")[0]
        if store_id in seen_ids:
            continue

        h3 = sec.find(["h3", "h2", "h4"])
        name = ""
        if h3:
            raw_h3 = h3.get_text(" ", strip=True)
            # Remove "Open today..."
            name = re.sub(r"\s+Open\s+today.*$", "", raw_h3, flags=re.I).strip()
            name = re.sub(r"\(SuperValue\)", "", name, flags=re.I).strip()
        if not name:
            name = store_id.title()

        # Check for online shopping capability: presence of 'Shop Now'
        sec_text = sec.get_text(" ", strip=True)
        has_shop_now = any("Shop Now" in a.get_text(strip=True) for a in links)
        shopping_online = has_shop_now

        # Address
        p_tags = sec.find_all("p")
        address = None
        if p_tags:
            address = p_tags[0].get_text(" ", strip=True)

        branch = Branch(
            id=store_id,
            name=name,
            url=f"https://{netloc}",
            address=address,
            shopping_online=shopping_online,
        )
        branches.append(branch)
        seen_ids.add(store_id)

    return sorted(branches, key=lambda b: b.id)


def parse_categories(html: str, base_url: str) -> dict[str, str]:
    """Parse categories from /browse page HTML returning {name: full_url}."""
    soup = BeautifulSoup(html, "html.parser")
    categories = {}

    for a in soup.find_all("a", href=re.compile(r"/category/")):
        href = a.get("href", "")
        name = a.get_text(strip=True)
        if not name:
            img = a.find("img")
            if img and img.get("alt"):
                name = img["alt"].strip()

        if name and "/category/" in href:
            full_url = urljoin(base_url, href.split("?")[0])
            if name not in categories:
                categories[name] = full_url

    return categories


def enrich_branch_from_browse(branch: Branch, html: str) -> None:
    """Extract opening hours, phone, and email from branch browse footer."""
    soup = BeautifulSoup(html, "html.parser")

    # Phone
    tel_link = soup.find("a", href=re.compile(r"^tel:"))
    if tel_link:
        branch.phone = tel_link.get("href", "").replace("tel:", "").strip()
    else:
        pm = re.search(r"(\+?64[\s-]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4}|\b0\d[\s-]?\d{3}[\s-]?\d{4}\b)", html)
        if pm:
            branch.phone = pm.group(1).strip()

    # Email
    mail_link = soup.find("a", href=re.compile(r"^mailto:"))
    if mail_link:
        branch.email = mail_link.get("href", "").replace("mailto:", "").strip()

    # Opening hours
    footer = soup.find(["footer", "div"], class_=re.compile(r"hours|opening|contact", re.I)) or soup
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    text = footer.get_text("\n")
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    for i, line in enumerate(lines):
        for day in days:
            if line == day and i + 1 < len(lines):
                next_line = lines[i + 1]
                if re.search(r"\d+:\d+\s*(?:am|pm)", next_line, re.I):
                    branch.opening_hours[day] = next_line
