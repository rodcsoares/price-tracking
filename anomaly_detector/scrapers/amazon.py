"""Amazon.ca Resale scraper."""

import logging
from typing import Optional

from .base import BaseScraper, ScrapedItem

logger = logging.getLogger(__name__)


# Amazon.ca Resale category URLs
AMAZON_CATEGORIES = {
    # High-value sub-categories
    "headphones": "https://www.amazon.ca/s?bbn=8929975011&rh=n%3A8929975011%2Cn%3A667823011%2Cn%3A3379552011&s=popularity-rank&dc",
    "gaming": "https://www.amazon.ca/s?bbn=8929975011&rh=n%3A8929975011%2Cn%3A110218011&s=popularity-rank&dc",
    # Computers & Tablets (full category)
    "computers": "https://www.amazon.ca/s?i=electronics&bbn=8929975011&rh=n%3A667823011%2Cn%3A8929975011%2Cn%3A2404990011&s=popularity-rank&dc",
    # Computer Components - GPUs, RAM, storage, motherboards, etc.
    "components": "https://www.amazon.ca/s?i=electronics&bbn=8929975011&rh=n%3A667823011%2Cn%3A8929975011%2Cn%3A2404990011%2Cn%3A677273011&s=popularity-rank&dc",
    "tvs": "https://www.amazon.ca/s?bbn=8929975011&rh=n%3A8929975011%2Cn%3A667823011%2Cn%3A6205126011&s=popularity-rank&dc",
    "cameras": "https://www.amazon.ca/s?bbn=8929975011&rh=n%3A8929975011%2Cn%3A667823011%2Cn%3A3379554011&s=popularity-rank&dc",
    "monitors": "https://www.amazon.ca/s?bbn=8929975011&rh=n%3A8929975011%2Cn%3A677243011%2Cn%3A677271011&s=popularity-rank&dc",
    # Broad categories
    "electronics": "https://www.amazon.ca/s?bbn=8929975011&rh=n%3A8929975011%2Cn%3A667823011&s=popularity-rank&dc",
    "home": "https://www.amazon.ca/s?bbn=8929975011&rh=n%3A8929975011%2Cn%3A6205512011&s=popularity-rank&dc",
}

# CSS Selectors for Amazon.ca search results (verified Jan 2026)
SELECTORS = {
    "product_card": "div.s-result-item.s-asin[data-asin]",
    "asin_attr": "data-asin",
    "title": "h2 a.a-link-normal span",
    "title_link": "h2 a.a-link-normal",
    "price_whole": ".a-price .a-price-whole",
    "price_fraction": ".a-price .a-price-fraction",
    "price_offscreen": ".a-price .a-offscreen",
    "price_secondary": "[data-cy='secondary-offer-recipe'] .a-color-base",
}


class AmazonScraper(BaseScraper):
    """
    Scraper for Amazon.ca Resale (formerly Warehouse Deals).
    
    Focuses on the Amazon Resale program which offers discounted
    open-box and refurbished items.
    """
    
    SOURCE_NAME = "amazon"
    
    def get_category_url(self, category: str) -> Optional[str]:
        """Get URL for a category name."""
        return AMAZON_CATEGORIES.get(category)
    
    def get_available_categories(self) -> list[str]:
        """Get list of available categories."""
        return list(AMAZON_CATEGORIES.keys())
    
    async def _scrape_page(self, page) -> list[ScrapedItem]:
        """Scrape all items from the current Amazon page."""
        items = []
        
        # Wait for product cards to load
        try:
            await page.wait_for_selector(SELECTORS["product_card"], timeout=15000)
        except Exception:
            logger.warning("[amazon] No product cards found on page")
            return items
        
        cards = await page.query_selector_all(SELECTORS["product_card"])
        logger.info(f"[amazon] Found {len(cards)} product cards")
        
        for card in cards:
            try:
                # Get ASIN
                asin = await card.get_attribute(SELECTORS["asin_attr"])
                if not asin:
                    continue
                
                # Get title
                title_elem = await card.query_selector(".a-text-normal")
                if not title_elem:
                    title_elem = await card.query_selector(SELECTORS["title"])
                title = await title_elem.text_content() if title_elem else None
                if not title:
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
                
                # Get price - try secondary offer first (Amazon Resale items)
                price = None
                
                price_elem = await card.query_selector(SELECTORS["price_secondary"])
                if price_elem:
                    price_text = await price_elem.text_content()
                    price = self._extract_price(price_text)
                
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
                        import re
                        whole = await whole_elem.text_content() or "0"
                        frac = await frac_elem.text_content() if frac_elem else "00"
                        whole = re.sub(r'[^\d]', '', whole)
                        frac = re.sub(r'[^\d]', '', frac)
                        if whole:
                            price = float(f"{whole}.{frac}")
                
                if price is None:
                    logger.debug(f"[amazon] No price for {asin}: {title[:40]}...")
                    continue
                
                if not self._is_valid_price(price):
                    logger.debug(f"[amazon] Skipping ${price:.2f} (invalid/below min) for {asin}")
                    continue
                
                items.append(ScrapedItem(
                    sku=asin,
                    title=title,
                    price=price,
                    url=url,
                    source=self.SOURCE_NAME,
                ))
                
            except Exception as e:
                logger.debug(f"[amazon] Error parsing card: {e}")
                continue
        
        return items
    
    async def _goto_next_page(self, page) -> bool:
        """Navigate to next page using Amazon pagination."""
        try:
            next_button = await page.query_selector("a.s-pagination-next:not(.s-pagination-disabled)")
            if next_button:
                await self._random_delay()
                await next_button.click()
                await page.wait_for_load_state("domcontentloaded")
                await self._random_delay()
                return True
        except Exception as e:
            logger.debug(f"[amazon] Pagination failed: {e}")
        return False
