"""Price extraction utilities with regex and Playwright fallback."""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Site-specific CSS selectors for main product price (most reliable)
SITE_SELECTORS: dict[str, list[str]] = {
    "amazon": [
        "#corePriceDisplay_desktop_feature_div .a-offscreen",
        "#corePrice_desktop .a-offscreen", 
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        ".a-price[data-a-color='price'] .a-offscreen",
        "#apex_offerDisplay_desktop .a-offscreen",
    ],
    "bestbuy": [
        "[data-testid='customer-price'] span",
        ".priceView-customer-price span",
        ".priceView-hero-price span",
    ],
    "newegg": [
        ".price-current strong",
        ".price-current",
    ],
    "walmart": [
        "[itemprop='price']",
        ".price-characteristic",
    ],
}

# Fallback regex patterns (only used if selectors fail)
PRICE_PATTERNS: list[re.Pattern] = [
    re.compile(r'\$[\d,]+\.\d{2}'),
    re.compile(r'(?:CAD|USD|US\$|Price:?\s*\$?)\s*([\d,]+\.?\d*)'),
    re.compile(r'data-price=["\']?([\d.]+)'),
    re.compile(r'"price":\s*"?([\d.]+)'),
]


def _detect_site(url: str) -> Optional[str]:
    """Detect which retailer a URL belongs to."""
    url_lower = url.lower()
    if "amazon" in url_lower:
        return "amazon"
    elif "bestbuy" in url_lower:
        return "bestbuy"
    elif "newegg" in url_lower:
        return "newegg"
    elif "walmart" in url_lower:
        return "walmart"
    return None


def extract_price_from_html(html: str, url: str) -> Optional[float]:
    """
    Extract price from HTML content using regex patterns.
    
    This is a fallback when Playwright selectors are not available.
    Note: For Amazon and similar sites, this may pick up wrong prices
    from ads/accessories. Prefer Playwright extraction for accuracy.
    """
    prices_found: list[float] = []
    
    for pattern in PRICE_PATTERNS:
        matches = pattern.findall(html)
        for match in matches:
            try:
                if isinstance(match, tuple):
                    match = match[0] if match[0] else match[1] if len(match) > 1 else ""
                cleaned = re.sub(r'[^\d.]', '', str(match))
                if cleaned and '.' in cleaned:
                    price = float(cleaned)
                    # Sanity check: exclude very small values (likely shipping/fees)
                    if 5.00 <= price <= 100000:
                        prices_found.append(price)
            except (ValueError, IndexError):
                continue
    
    if prices_found:
        # For regex fallback, use the FIRST match (usually the main price)
        # instead of min() which picks up ads/accessories
        result = prices_found[0]
        logger.debug(f"Regex extracted price ${result:.2f} from {url} (found {len(prices_found)} candidates)")
        return result
    
    logger.warning(f"No price found in HTML from {url}")
    return None


async def extract_price_with_playwright(url: str) -> Optional[float]:
    """
    Extract price using Playwright for JavaScript-rendered pages.
    
    Uses site-specific CSS selectors for accuracy, avoiding prices
    from ads, sponsored products, and accessories.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
        return None
    
    site = _detect_site(url)
    selectors = SITE_SELECTORS.get(site, []) if site else []
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()
            
            logger.info(f"Playwright: Loading {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # Wait for price elements to render
            await page.wait_for_timeout(3000)
            
            # Try site-specific selectors first
            for selector in selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        text = await element.text_content()
                        if text:
                            # Clean and parse the price
                            cleaned = re.sub(r'[^\d.]', '', text)
                            if cleaned:
                                price = float(cleaned)
                                if 1.00 <= price <= 100000:
                                    logger.info(f"Playwright extracted ${price:.2f} via selector '{selector}'")
                                    await browser.close()
                                    return price
                except Exception as e:
                    logger.debug(f"Selector '{selector}' failed: {e}")
                    continue
            
            # Fallback: try regex on rendered HTML
            html = await page.content()
            await browser.close()
            
            price = extract_price_from_html(html, url)
            if price:
                logger.info(f"Playwright regex fallback extracted ${price:.2f} from {url}")
                return price
            
            logger.warning(f"Playwright could not extract price from {url}")
            return None
            
    except Exception as e:
        logger.error(f"Playwright extraction failed for {url}: {e}")
        return None
