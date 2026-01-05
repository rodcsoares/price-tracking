"""Playwright-based scraper for Amazon.ca Warehouse category pages."""

import asyncio
import random
import re
import logging
from dataclasses import dataclass
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Import user agents from parent package
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from price_monitor.user_agents import get_random_user_agent


@dataclass
class ScrapedItem:
    """A single item scraped from the category page."""
    asin: str
    title: str
    price: float
    url: str


# Amazon.ca Resale (formerly Warehouse Deals) category URLs
# Note: Amazon rebranded "Warehouse Deals" to "Amazon Resale" in Canada
# The old i=warehouse-deals index returns 0 results for broad searches
# Can be overridden via environment variable
DEFAULT_CATEGORY_URL = (
    # Electronics category on Amazon Resale (bbn=8929975011 is the Resale root node)
    "https://www.amazon.ca/s?bbn=8929975011"
    "&rh=n%3A8929975011%2Cn%3A667823011"  # Electronics subcategory
    "&s=popularity-rank"
    "&dc"
)

# Focused sub-category URLs for higher-value items
# These are sub-categories within Electronics on Amazon Resale
CATEGORY_URLS = {
    # High-value sub-categories (less junk, more $50+ items)
    "headphones": "https://www.amazon.ca/s?bbn=8929975011&rh=n%3A8929975011%2Cn%3A667823011%2Cn%3A3379552011&s=popularity-rank&dc",
    "gaming": "https://www.amazon.ca/s?bbn=8929975011&rh=n%3A8929975011%2Cn%3A110218011&s=popularity-rank&dc",
    # Computers & Tablets (node 2404990011) - full category, not just graphics cards
    "computers": "https://www.amazon.ca/s?i=electronics&bbn=8929975011&rh=n%3A667823011%2Cn%3A8929975011%2Cn%3A2404990011&s=popularity-rank&dc",
    # Computer Components (node 677273011) - GPUs, RAM, storage, motherboards, etc.
    "components": "https://www.amazon.ca/s?i=electronics&bbn=8929975011&rh=n%3A667823011%2Cn%3A8929975011%2Cn%3A2404990011%2Cn%3A677273011&s=popularity-rank&dc",
    "tvs": "https://www.amazon.ca/s?bbn=8929975011&rh=n%3A8929975011%2Cn%3A667823011%2Cn%3A6205126011&s=popularity-rank&dc",
    "cameras": "https://www.amazon.ca/s?bbn=8929975011&rh=n%3A8929975011%2Cn%3A667823011%2Cn%3A3379554011&s=popularity-rank&dc",
    "monitors": "https://www.amazon.ca/s?bbn=8929975011&rh=n%3A8929975011%2Cn%3A677243011%2Cn%3A677271011&s=popularity-rank&dc",
    # Broad categories
    "electronics": "https://www.amazon.ca/s?bbn=8929975011&rh=n%3A8929975011%2Cn%3A667823011&s=popularity-rank&dc",
    "home": "https://www.amazon.ca/s?bbn=8929975011&rh=n%3A8929975011%2Cn%3A6205512011&s=popularity-rank&dc",
}

# Default minimum price filter (skip items below this)
DEFAULT_MIN_PRICE = 50.0

# CSS Selectors for Amazon.ca search results (verified Jan 2026)
SELECTORS = {
    # Each product card in search results - use s-result-item with data-asin
    # The s-asin class is more reliable than data-component-type on Resale pages
    "product_card": "div.s-result-item.s-asin[data-asin]",
    # ASIN is in data-asin attribute of the card
    "asin_attr": "data-asin",
    # Title link
    "title": "h2 a.a-link-normal span",
    "title_link": "h2 a.a-link-normal",
    # Price (whole + fraction)
    "price_whole": ".a-price .a-price-whole",
    "price_fraction": ".a-price .a-price-fraction",
    # Alternative: offscreen price (most reliable)
    "price_offscreen": ".a-price .a-offscreen",
    # Secondary offer price (for Resale items shown as used offers)
    "price_secondary": "[data-cy='secondary-offer-recipe'] .a-color-base",
}


class CategoryScraper:
    """
    Scraper for Amazon.ca Resale (formerly Warehouse Deals) category pages.
    
    Uses Playwright to handle JavaScript rendering and pagination.
    Designed for low-frequency scraping (4+ hour intervals) with
    random delays to avoid detection.
    """
    
    def __init__(
        self,
        category_url: str = DEFAULT_CATEGORY_URL,
        max_pages: int = 20,  # Increased from 3 to cover more products
        min_price: float = DEFAULT_MIN_PRICE,  # Skip items below this price
        scroll_delay_range: tuple[float, float] = (2.0, 5.0),
        headless: bool = True,
    ):
        self.category_url = category_url
        self.max_pages = max_pages
        self.min_price = min_price
        self.scroll_delay_range = scroll_delay_range
        self.headless = headless
    
    async def _random_delay(self):
        """Wait a random amount of time to appear more human-like."""
        delay = random.uniform(*self.scroll_delay_range)
        logger.debug(f"Waiting {delay:.1f}s...")
        await asyncio.sleep(delay)
    
    def _extract_price(self, price_text: str) -> Optional[float]:
        """Parse price from text like '$29.99' or '29.99'."""
        if not price_text:
            return None
        # Remove currency symbols and whitespace
        cleaned = re.sub(r'[^\d.]', '', price_text)
        if cleaned:
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None
    
    async def _scrape_page(self, page) -> list[ScrapedItem]:
        """Scrape all items from the current page."""
        items = []
        
        # Wait for product cards to load
        try:
            await page.wait_for_selector(SELECTORS["product_card"], timeout=15000)
        except Exception:
            logger.warning("No product cards found on page")
            return items
        
        # Get all product cards
        cards = await page.query_selector_all(SELECTORS["product_card"])
        logger.info(f"Found {len(cards)} product cards")
        
        for card in cards:
            try:
                # Get ASIN
                asin = await card.get_attribute(SELECTORS["asin_attr"])
                if not asin:
                    continue
                
                # Get title - use .a-text-normal which works on Amazon Resale
                title_elem = await card.query_selector(".a-text-normal")
                if not title_elem:
                    # Fallback to older selector
                    title_elem = await card.query_selector(SELECTORS["title"])
                title = await title_elem.text_content() if title_elem else None
                if not title:
                    logger.debug(f"No title found for card with ASIN {asin}")
                    continue
                title = title.strip()
                
                # Get URL
                link_elem = await card.query_selector(SELECTORS["title_link"])
                if not link_elem:
                    link_elem = await card.query_selector("h2 a")
                href = await link_elem.get_attribute("href") if link_elem else None
                url = f"https://www.amazon.ca{href}" if href and href.startswith("/") else href
                if not url:
                    url = f"https://www.amazon.ca/dp/{asin}"
                
                # Get price - Amazon Resale items use secondary-offer-recipe
                price = None
                
                # Try secondary offer price first (Amazon Resale items)
                price_elem = await card.query_selector('[data-cy="secondary-offer-recipe"] .a-color-base')
                if price_elem:
                    price_text = await price_elem.text_content()
                    price = self._extract_price(price_text)
                    if price:
                        logger.debug(f"Price from secondary-offer: ${price}")
                
                # Fallback: standard offscreen price
                if price is None:
                    price_elem = await card.query_selector(SELECTORS["price_offscreen"])
                    if price_elem:
                        price_text = await price_elem.text_content()
                        price = self._extract_price(price_text)
                
                # Fallback: whole + fraction
                if price is None:
                    whole_elem = await card.query_selector(SELECTORS["price_whole"])
                    frac_elem = await card.query_selector(SELECTORS["price_fraction"])
                    if whole_elem:
                        whole = await whole_elem.text_content() or "0"
                        frac = await frac_elem.text_content() if frac_elem else "00"
                        whole = re.sub(r'[^\d]', '', whole)
                        frac = re.sub(r'[^\d]', '', frac)
                        if whole:
                            price = float(f"{whole}.{frac}")
                
                if price is None:
                    logger.debug(f"No price found for {asin}: {title[:50]}")
                    continue
                
                # Sanity check price and apply min_price filter
                if price < 1 or price > 100000:
                    logger.debug(f"Skipping invalid price ${price} for {asin}")
                    continue
                
                # Skip items below the minimum price threshold
                if price < self.min_price:
                    logger.debug(f"Skipping ${price:.2f} (below ${self.min_price} min) for {asin}")
                    continue
                
                items.append(ScrapedItem(
                    asin=asin,
                    title=title,
                    price=price,
                    url=url,
                ))
                
            except Exception as e:
                logger.debug(f"Error parsing product card: {e}")
                continue
        
        return items
    
    async def _scroll_to_bottom(self, page):
        """Scroll page to trigger lazy loading."""
        previous_height = 0
        scroll_count = 0
        max_scrolls = 10
        
        while scroll_count < max_scrolls:
            # Scroll down
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self._random_delay()
            
            # Check if we've reached the bottom
            current_height = await page.evaluate("document.body.scrollHeight")
            if current_height == previous_height:
                break
            
            previous_height = current_height
            scroll_count += 1
            logger.debug(f"Scroll {scroll_count}: page height = {current_height}")
    
    async def scrape(self) -> list[ScrapedItem]:
        """
        Scrape items from category pages.
        
        Returns list of ScrapedItem objects.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
            return []
        
        all_items: list[ScrapedItem] = []
        seen_asins: set[str] = set()
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                context = await browser.new_context(
                    user_agent=get_random_user_agent(),
                    viewport={"width": 1920, "height": 1080},
                    locale="en-CA",
                )
                page = await context.new_page()
                
                # Navigate to category page
                logger.info(f"Loading category page: {self.category_url}")
                await page.goto(self.category_url, wait_until="domcontentloaded", timeout=60000)
                await self._random_delay()
                
                # Scrape multiple pages
                for page_num in range(1, self.max_pages + 1):
                    logger.info(f"Scraping page {page_num}/{self.max_pages}")
                    
                    # Scroll to load all items
                    await self._scroll_to_bottom(page)
                    
                    # Scrape current page
                    items = await self._scrape_page(page)
                    
                    # Deduplicate by ASIN
                    for item in items:
                        if item.asin not in seen_asins:
                            seen_asins.add(item.asin)
                            all_items.append(item)
                    
                    logger.info(f"Page {page_num}: Found {len(items)} items, {len(all_items)} total unique")
                    
                    # Try to go to next page
                    if page_num < self.max_pages:
                        next_button = await page.query_selector("a.s-pagination-next:not(.s-pagination-disabled)")
                        if next_button:
                            await self._random_delay()
                            await next_button.click()
                            await page.wait_for_load_state("domcontentloaded")
                            await self._random_delay()
                        else:
                            logger.info("No more pages available")
                            break
                
                await browser.close()
                
        except Exception as e:
            logger.error(f"Scraping failed: {e}")
        
        logger.info(f"Scraping complete: {len(all_items)} unique items found")
        return all_items


async def run_scraper_test():
    """Quick test of the scraper (scrapes 1 page)."""
    logging.basicConfig(level=logging.INFO)
    scraper = CategoryScraper(max_pages=1, headless=True)
    items = await scraper.scrape()
    
    print(f"\n{'='*60}")
    print(f"Found {len(items)} items:")
    print(f"{'='*60}")
    
    for item in items[:10]:  # Show first 10
        print(f"  [{item.asin}] ${item.price:.2f} - {item.title[:60]}...")
    
    if len(items) > 10:
        print(f"  ... and {len(items) - 10} more")
    
    return items


if __name__ == "__main__":
    asyncio.run(run_scraper_test())
