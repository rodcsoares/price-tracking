"""Newegg.ca scraper."""

import logging
from typing import Optional

from .base import BaseScraper, ScrapedItem

logger = logging.getLogger(__name__)


# Newegg.ca category URLs for deals/open-box items
NEWEGG_CATEGORIES = {
    # Computer Systems & Components
    "gpus": "https://www.newegg.ca/p/pl?N=100007709",
    "cpus": "https://www.newegg.ca/p/pl?N=100007671",
    "ram": "https://www.newegg.ca/p/pl?N=100007611",
    "storage": "https://www.newegg.ca/p/pl?N=100011693",      # Internal SSDs
    "motherboards": "https://www.newegg.ca/p/pl?N=100007627",
    "laptops": "https://www.newegg.ca/p/pl?N=100006740",
    "monitors": "https://www.newegg.ca/p/pl?N=100898493",
    # Special
    "deals": "https://www.newegg.ca/todays-deals",
}

# CSS Selectors for Newegg.ca
SELECTORS = {
    "product_card": ".item-cell, .item-container",
    "title": ".item-title",
    "price": ".price-current strong",
    "price_alt": ".price-current",
    "link": ".item-title",
    "sku_attr": "data-item-id",
}


class NeweggScraper(BaseScraper):
    """
    Scraper for Newegg.ca.
    
    Focuses on Open Box deals and Shell Shocker daily deals
    for computer components and electronics.
    """
    
    SOURCE_NAME = "newegg"
    
    def get_category_url(self, category: str) -> Optional[str]:
        """Get URL for a category name."""
        return NEWEGG_CATEGORIES.get(category)
    
    def get_available_categories(self) -> list[str]:
        """Get list of available categories."""
        return list(NEWEGG_CATEGORIES.keys())
    
    async def _scrape_page(self, page) -> list[ScrapedItem]:
        """Scrape all items from the current Newegg page."""
        items = []
        
        try:
            await page.wait_for_selector(SELECTORS["product_card"], timeout=15000)
        except Exception:
            logger.warning("[newegg] No product cards found on page")
            return items
        
        cards = await page.query_selector_all(SELECTORS["product_card"])
        logger.info(f"[newegg] Found {len(cards)} product cards")
        
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
                
                # Extract SKU from URL or data attribute
                sku = await card.get_attribute(SELECTORS["sku_attr"])
                if not sku and url:
                    # Try to extract from URL like /p/N82E16814...
                    import re
                    match = re.search(r'/p/([A-Z0-9]+)', url)
                    if match:
                        sku = match.group(1)
                if not sku:
                    # Generate from title hash
                    sku = f"newegg-{hash(title) % 1000000}"
                
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
                    logger.debug(f"[newegg] No price for: {title[:40]}...")
                    continue
                
                if not self._is_valid_price(price):
                    logger.debug(f"[newegg] Skipping ${price:.2f} for {sku}")
                    continue
                
                items.append(ScrapedItem(
                    sku=sku,
                    title=title,
                    price=price,
                    url=url,
                    source=self.SOURCE_NAME,
                ))
                
            except Exception as e:
                logger.debug(f"[newegg] Error parsing card: {e}")
                continue
        
        return items
    
    async def _goto_next_page(self, page) -> bool:
        """Navigate to next page using Newegg pagination."""
        try:
            # Try multiple selectors for the 'Next' button
            next_selectors = [
                "a[title='Next']",  # Standard button
                "button[title='Next']", # Potential variation
                ".list-tool-pagination a[title='Next']", # More specific
                "a.btn-group-page[title='Next']", # Historic
            ]
            
            for selector in next_selectors:
                next_button = await page.query_selector(selector)
                if next_button:
                    # check if disabled
                    class_attr = await next_button.get_attribute("class")
                    if class_attr and "disabled" in class_attr:
                        continue
                        
                    await self._random_delay()
                    await next_button.click()
                    await page.wait_for_load_state("domcontentloaded")
                    await self._random_delay()
                    return True
                    
        except Exception as e:
            logger.debug(f"[newegg] Pagination failed: {e}")
        return False
