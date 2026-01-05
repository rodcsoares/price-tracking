"""Canada Computers scraper."""

import re
import logging
from typing import Optional

from .base import BaseScraper, ScrapedItem

logger = logging.getLogger(__name__)


# Canada Computers category URLs for Open Box / Clearance
# Canada Computers category URLs
# Note: Site redirects old cPath URLs to /en/... we use the confirmed new paths where possible
CANADACOMPUTERS_CATEGORIES = {
    # Open Box section
    "openbox": "https://www.canadacomputers.com/en/openbox",
    # Clearance
    "clearance": "https://www.canadacomputers.com/en/clearance",
    # Component categories (using redirectable IDs or explicit paths)
    "gpus": "https://www.canadacomputers.com/en/915/desktop-graphics-cards",
    "cpus": "https://www.canadacomputers.com/index.php?cPath=4_64",
    "ram": "https://www.canadacomputers.com/index.php?cPath=24_311_312",
    "motherboards": "https://www.canadacomputers.com/index.php?cPath=26",
    "storage": "https://www.canadacomputers.com/index.php?cPath=179_1088",
    "cases": "https://www.canadacomputers.com/index.php?cPath=6_112",
    "psus": "https://www.canadacomputers.com/index.php?cPath=33_442",
    "cooling": "https://www.canadacomputers.com/index.php?cPath=8_129",
    # Full systems
    "laptops": "https://www.canadacomputers.com/index.php?cPath=710",
    "desktops": "https://www.canadacomputers.com/index.php?cPath=7",
    "monitors": "https://www.canadacomputers.com/index.php?cPath=22_700",
}

# CSS Selectors for Canada Computers (New Layout 2024/2025)
SELECTORS = {
    "product_card": "article.product-miniature",
    "title": ".product-title a",
    "price": "span.price",
    "sku_attr": "data-id-product",  # Standard Prestashop attribute
}


class CanadaComputersScraper(BaseScraper):
    """
    Scraper for Canada Computers.
    
    Focuses on Open Box and Clearance sections,
    plus regular categories sorted by discount.
    """
    
    SOURCE_NAME = "canadacomputers"
    
    def get_category_url(self, category: str) -> Optional[str]:
        """Get URL for a category name."""
        return CANADACOMPUTERS_CATEGORIES.get(category)
    
    def get_available_categories(self) -> list[str]:
        """Get list of available categories."""
        return list(CANADACOMPUTERS_CATEGORIES.keys())
    
    async def _scrape_page(self, page) -> list[ScrapedItem]:
        """Scrape all items from the current Canada Computers page."""
        items = []
        
        try:
            await page.wait_for_selector(SELECTORS["product_card"], timeout=15000)
        except Exception:
            logger.warning("[canadacomputers] No product cards found on page")
            return items
        
        cards = await page.query_selector_all(SELECTORS["product_card"])
        logger.info(f"[canadacomputers] Found {len(cards)} product cards")
        
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
                url = href if href else ""
                
                # Extract SKU
                sku = await card.get_attribute(SELECTORS["sku_attr"])
                if not sku and url:
                    # Look for ID in URL pattern like /12345-product-name
                    import re
                    match = re.search(r'/(\d+)-', url)
                    # Or old pattern product_id=...
                    if not match:
                        match = re.search(r'product_id=(\d+)', url)
                    
                    if match:
                        sku = f"cc-{match.group(1)}"
                
                if not sku:
                    # Fallback unique ID
                    sku = f"cc-{hash(title) % 1000000}"
                
                # Get price
                price = None
                price_elem = await card.query_selector(SELECTORS["price"])
                if price_elem:
                    price_text = await price_elem.text_content()
                    price = self._extract_price(price_text)
                
                if price is None:
                    logger.debug(f"[canadacomputers] No price for: {title[:40]}...")
                    continue
                
                if not self._is_valid_price(price):
                    logger.debug(f"[canadacomputers] Skipping ${price:.2f} for {sku}")
                    continue
                
                items.append(ScrapedItem(
                    sku=sku,
                    title=title,
                    price=price,
                    url=url,
                    source=self.SOURCE_NAME,
                ))
                

                
            except Exception as e:
                logger.debug(f"[canadacomputers] Error parsing card: {e}")
                continue
        
        return items
    
    async def _goto_next_page(self, page) -> bool:
        """Navigate to next page via Load More or URL param."""
        # Try Load More button (typical for new layout)
        try:
            load_more = await page.query_selector(".load-more a, .btn-load-more, #btn-load-more")
            # Ensure it's visible
            if load_more and await load_more.is_visible():
                await self._random_delay()
                await load_more.click()
                # Wait for network idle as content is likely loaded via AJAX
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except:
                    pass
                await asyncio.sleep(2)  # Extra grace period for DOM update
                return True
        except Exception as e:
            logger.debug(f"[canadacomputers] Load More click failed: {e}")

        # Fallback: URL manipulation if load more failed or not found
        try:
            url = page.url
            if "page=" in url:
                match = re.search(r'[?&]page=(\d+)', url)
                if match:
                    curr = int(match.group(1))
                    next_page = curr + 1
                    # Replace page=N with page=N+1
                    new_url = re.sub(r'([?&])page=\d+', f'\\g<1>page={next_page}', url)
                    await page.goto(new_url, wait_until="domcontentloaded")
                    return True
            else:
                # No page param, assume page 1 -> append page=2
                # Check if we actully have items? If scraper found 0 items, we shouldn't paginate probably.
                # But BaseScraper handles loop.
                sep = "&" if "?" in url else "?"
                new_url = f"{url}{sep}page=2"
                await page.goto(new_url, wait_until="domcontentloaded")
                return True
        except Exception as e:
            logger.debug(f"[canadacomputers] distinct pagination failed: {e}")

        return False
