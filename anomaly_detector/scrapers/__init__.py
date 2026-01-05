"""Scrapers package - site-specific scrapers for price monitoring."""

from .base import BaseScraper, ScrapedItem
from .amazon import AmazonScraper
from .newegg import NeweggScraper
from .canadacomputers import CanadaComputersScraper
from .memoryexpress import MemoryExpressScraper

# Registry of all available scrapers
SCRAPERS = {
    "amazon": AmazonScraper,
    "newegg": NeweggScraper,
    "canadacomputers": CanadaComputersScraper,
    "memoryexpress": MemoryExpressScraper,
}

def get_scraper(site: str, category: str, **kwargs):
    """
    Factory function to get a configured scraper instance.

    Args:
        site: Site name (amazon, newegg, canadacomputers, memoryexpress)
        category: Category name (varies by site) or 'all' to scrape every category
        **kwargs: Additional args passed to scraper (max_pages, min_price, etc.)

    Returns:
        Configured scraper instance or list of instances when category == 'all'

    Raises:
        ValueError: If site or category is invalid
    """
    if site not in SCRAPERS:
        raise ValueError(f"Unknown site: {site}. Available: {list(SCRAPERS.keys())}")

    scraper_class = SCRAPERS[site]

    # If user wants all categories, create a scraper for each one
    if category == "all":
        categories = get_site_categories(site)
        if not categories:
            raise ValueError(f"No categories found for site '{site}'.")
        scrapers = []
        for cat in categories:
            temp_scraper = scraper_class.__new__(scraper_class)
            category_url = temp_scraper.get_category_url(cat)
            if not category_url:
                continue
            scrapers.append(scraper_class(category_url=category_url, **kwargs))
        if not scrapers:
            raise ValueError(f"Failed to create scrapers for any categories of site '{site}'.")
        return scrapers

    # Get category URL for a single category
    temp_scraper = scraper_class.__new__(scraper_class)
    category_url = temp_scraper.get_category_url(category)

    if not category_url:
        available = temp_scraper.get_available_categories()
        raise ValueError(f"Unknown category '{category}' for {site}. Available: {available}")

    return scraper_class(category_url=category_url, **kwargs)


def get_all_sites() -> list[str]:
    """Get list of all available site names."""
    return list(SCRAPERS.keys())


def get_site_categories(site: str) -> list[str]:
    """Get available categories for a site."""
    if site not in SCRAPERS:
        return []
    scraper_class = SCRAPERS[site]
    temp_scraper = scraper_class.__new__(scraper_class)
    return temp_scraper.get_available_categories()


__all__ = [
    "BaseScraper",
    "ScrapedItem",
    "AmazonScraper",
    "NeweggScraper",
    "CanadaComputersScraper",
    "MemoryExpressScraper",
    "SCRAPERS",
    "get_scraper",
    "get_all_sites",
    "get_site_categories",
]
