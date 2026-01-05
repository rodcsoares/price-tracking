"""Base scraper class and common utilities for all site scrapers."""

import asyncio
import random
import re
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from pathlib import Path

# Import user agents from parent package
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from price_monitor.user_agents import get_random_user_agent

logger = logging.getLogger(__name__)

# Default minimum price filter (skip items below this)
DEFAULT_MIN_PRICE = 50.0



@dataclass
class ScrapedItem:
    """A single item scraped from any retailer."""
    sku: str          # Unique identifier (ASIN for Amazon, SKU for others)
    title: str
    price: float
    url: str
    source: str       # Retailer name (amazon, newegg, canadacomputers, memoryexpress)


class BaseScraper(ABC):
    """
    Abstract base class for all site scrapers.
    
    Provides common functionality like random delays, price extraction,
    and Playwright browser management. Subclasses must implement
    site-specific scraping logic.
    """
    
    # Override in subclasses
    SOURCE_NAME: str = "unknown"
    
    def __init__(
        self,
        category_url: str,
        max_pages: int = 20,
        min_price: float = 50.0,
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
    
    def _is_valid_price(self, price: float) -> bool:
        """Check if price is within valid range and above minimum."""
        if price < 1 or price > 100000:
            return False
        if price < self.min_price:
            return False
        return True
    
    async def _scroll_to_bottom(self, page, max_scrolls: int = 10):
        """Scroll page to trigger lazy loading."""
        previous_height = 0
        scroll_count = 0
        
        while scroll_count < max_scrolls:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self._random_delay()
            
            current_height = await page.evaluate("document.body.scrollHeight")
            if current_height == previous_height:
                break
            
            previous_height = current_height
            scroll_count += 1
            logger.debug(f"Scroll {scroll_count}: page height = {current_height}")
    
    @abstractmethod
    async def _scrape_page(self, page) -> list[ScrapedItem]:
        """
        Scrape all items from the current page.
        Must be implemented by subclasses.
        """
        pass
    
    @abstractmethod
    def get_category_url(self, category: str) -> Optional[str]:
        """
        Get the URL for a given category name.
        Must be implemented by subclasses.
        """
        pass
    
    @abstractmethod
    def get_available_categories(self) -> list[str]:
        """
        Get list of available category names.
        Must be implemented by subclasses.
        """
        pass
    
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
        seen_skus: set[str] = set()
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                context = await browser.new_context(
                    user_agent=get_random_user_agent(),
                    viewport={"width": 1920, "height": 1080},
                    locale="en-CA",
                )
                page = await context.new_page()
                
                logger.info(f"[{self.SOURCE_NAME}] Loading: {self.category_url}")
                await page.goto(self.category_url, wait_until="domcontentloaded", timeout=60000)
                await self._random_delay()
                
                for page_num in range(1, self.max_pages + 1):
                    logger.info(f"[{self.SOURCE_NAME}] Scraping page {page_num}/{self.max_pages}")
                    
                    await self._scroll_to_bottom(page)
                    items = await self._scrape_page(page)
                    
                    # Deduplicate by SKU
                    for item in items:
                        if item.sku not in seen_skus:
                            seen_skus.add(item.sku)
                            all_items.append(item)
                    
                    logger.info(f"[{self.SOURCE_NAME}] Page {page_num}: {len(items)} items, {len(all_items)} total unique")
                    
                    # Try to go to next page
                    if page_num < self.max_pages:
                        if not await self._goto_next_page(page):
                            logger.info(f"[{self.SOURCE_NAME}] No more pages available")
                            break
                
                await browser.close()
                
        except Exception as e:
            logger.error(f"[{self.SOURCE_NAME}] Scraping failed: {e}")
        
        logger.info(f"[{self.SOURCE_NAME}] Complete: {len(all_items)} unique items")
        return all_items
    
    async def _goto_next_page(self, page) -> bool:
        """
        Navigate to the next page. Override for site-specific pagination.
        Returns True if successfully navigated, False if no more pages.
        """
        # Default: look for common pagination patterns
        next_selectors = [
            "a.s-pagination-next:not(.s-pagination-disabled)",  # Amazon
            ".pagination-next:not(.disabled) a",
            "a[rel='next']",
            ".next-page a",
        ]
        
        for selector in next_selectors:
            try:
                next_button = await page.query_selector(selector)
                if next_button:
                    await self._random_delay()
                    await next_button.click()
                    await page.wait_for_load_state("domcontentloaded")
                    await self._random_delay()
                    return True
            except Exception:
                continue
        
        return False
