"""Memory Express scraper."""

import logging
from typing import Optional

from .base import BaseScraper, ScrapedItem

logger = logging.getLogger(__name__)


# Memory Express category URLs for deals/clearance
MEMORYEXPRESS_CATEGORIES = {
    # Open Box / Clearance
    "openbox": "https://www.memoryexpress.com/Category/OpenBox",
    "clearance": "https://www.memoryexpress.com/Category/Clearance",
    # Component categories
    "gpus": "https://www.memoryexpress.com/Category/VideoCards",
    "cpus": "https://www.memoryexpress.com/Category/CPUs",
    "ram": "https://www.memoryexpress.com/Category/DesktopMemory",
    "motherboards": "https://www.memoryexpress.com/Category/Motherboards",
    "storage": "https://www.memoryexpress.com/Category/SolidStateDrives",
    "cases": "https://www.memoryexpress.com/Category/ComputerCases",
    "psus": "https://www.memoryexpress.com/Category/PowerSupplies",
    "cooling": "https://www.memoryexpress.com/Category/CPUCooling",
    # Systems
    "laptops": "https://www.memoryexpress.com/Category/LaptopsNotebooks",
    "monitors": "https://www.memoryexpress.com/Category/Monitors",
}

# CSS Selectors for Memory Express
SELECTORS = {
    "product_card": ".c-shca-icon-item, .product-item",
    "title": ".c-shca-icon-item__body-name a, .product-title a",
    "price": ".c-shca-icon-item__summary-list .c-shca-icon-item__price, .price-sale",
    "price_alt": ".GrandTotal, .price",
    "sku_attr": "data-product-id",
}


class MemoryExpressScraper(BaseScraper):
    """
    Scraper for Memory Express.
    
    Canadian computer retailer with Open Box and Clearance
    sections for discounted items.
    """
    
    SOURCE_NAME = "memoryexpress"
    
    def get_category_url(self, category: str) -> Optional[str]:
        """Get URL for a category name."""
        return MEMORYEXPRESS_CATEGORIES.get(category)
    
    def get_available_categories(self) -> list[str]:
        """Get list of available categories."""
        return list(MEMORYEXPRESS_CATEGORIES.keys())
    
    async def _scrape_page(self, page) -> list[ScrapedItem]:
        """Scrape all items from the current Memory Express page."""
        items = []
        
        try:
            await page.wait_for_selector(SELECTORS["product_card"], timeout=15000)
        except Exception:
            logger.warning("[memoryexpress] No product cards found on page")
            return items
        
        cards = await page.query_selector_all(SELECTORS["product_card"])
        logger.info(f"[memoryexpress] Found {len(cards)} product cards")
        
        for card in cards:
            try:
                # Get title and URL
                title_elem = await card.query_selector(SELECTORS["title"])
                if not title_elem:
                    continue
                    
                title = await title_elem.text_content()
                if not title:
                    continue
                title = title.strip()
                
                href = await title_elem.get_attribute("href")
                url = f"https://www.memoryexpress.com{href}" if href and href.startswith("/") else href
                
                # Extract SKU
                sku = await card.get_attribute(SELECTORS["sku_attr"])
                if not sku and url:
                    import re
                    match = re.search(r'/Products/([^/]+)', url)
                    if match:
                        sku = f"mx-{match.group(1)}"
                if not sku:
                    sku = f"mx-{hash(title) % 1000000}"
                
                # Get price
                price = None
                price_elem = await card.query_selector(SELECTORS["price"])
                if price_elem:
                    price_text = await price_elem.text_content()
                    price = self._extract_price(price_text)
                
                if price is None:
                    price_elem = await card.query_selector(SELECTORS["price_alt"])
                    if price_elem:
                        price_text = await price_elem.text_content()
                        price = self._extract_price(price_text)
                
                if price is None:
                    logger.debug(f"[memoryexpress] No price for: {title[:40]}...")
                    continue
                
                if not self._is_valid_price(price):
                    logger.debug(f"[memoryexpress] Skipping ${price:.2f} for {sku}")
                    continue
                
                items.append(ScrapedItem(
                    sku=sku,
                    title=title,
                    price=price,
                    url=url,
                    source=self.SOURCE_NAME,
                ))
                
            except Exception as e:
                logger.debug(f"[memoryexpress] Error parsing card: {e}")
                continue
        
        return items
    
    async def _goto_next_page(self, page) -> bool:
        """Navigate to next page."""
        try:
            next_button = await page.query_selector(".c-pagination__next:not(.disabled) a, .pagination .next a")
            if next_button:
                await self._random_delay()
                await next_button.click()
                await page.wait_for_load_state("domcontentloaded")
                await self._random_delay()
                return True
        except Exception as e:
            logger.debug(f"[memoryexpress] Pagination failed: {e}")
        return False
