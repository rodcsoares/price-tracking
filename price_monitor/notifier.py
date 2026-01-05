"""Discord webhook notification module."""

import logging
import httpx

from .config import DISCORD_WEBHOOK_URL, REQUEST_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


async def send_discord_alert(
    product_name: str,
    old_price: float | None,
    new_price: float,
    discount_pct: float,
    url: str,
) -> bool:
    """
    Send a formatted price alert to Discord webhook.
    
    Args:
        product_name: Name of the product
        old_price: Previous known price (None if first check)
        new_price: Current price
        discount_pct: Discount percentage (positive = price drop)
        url: Direct link to product page
        
    Returns:
        True if sent successfully, False otherwise
    """
    if not DISCORD_WEBHOOK_URL:
        logger.warning("Discord webhook URL not configured. Skipping alert.")
        logger.info(
            f"[ALERT] {product_name}: ${old_price or 'N/A'} → ${new_price:.2f} "
            f"({discount_pct:.1f}% off) - {url}"
        )
        return False
    
    # Determine embed color based on discount
    if discount_pct >= 50:
        color = 0xFF0000  # Red - massive deal
    elif discount_pct >= 40:
        color = 0xFF6600  # Orange - flash sale
    elif discount_pct >= 20:
        color = 0xFFCC00  # Yellow - good deal
    else:
        color = 0x00CC00  # Green - met target
    
    # Build the embed payload
    embed = {
        "title": f"🔔 Price Alert: {product_name}",
        "color": color,
        "fields": [
            {
                "name": "💰 Old Price",
                "value": f"${old_price:.2f}" if old_price else "N/A",
                "inline": True,
            },
            {
                "name": "🏷️ New Price",
                "value": f"**${new_price:.2f}**",
                "inline": True,
            },
            {
                "name": "📉 Discount",
                "value": f"**{discount_pct:.1f}%** off",
                "inline": True,
            },
        ],
        "url": url,
        "footer": {"text": "Price Monitor • Click title to view product"},
    }
    
    payload = {
        "embeds": [embed],
    }
    
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(DISCORD_WEBHOOK_URL, json=payload)
            response.raise_for_status()
            logger.info(f"Discord alert sent for {product_name}")
            return True
    except httpx.HTTPStatusError as e:
        logger.error(f"Discord webhook error: {e.response.status_code} - {e.response.text}")
        return False
    except httpx.RequestError as e:
        logger.error(f"Discord webhook request failed: {e}")
        return False


async def send_test_alert() -> bool:
    """Send a test alert to verify webhook connectivity."""
    return await send_discord_alert(
        product_name="🧪 Test Product",
        old_price=100.00,
        new_price=49.99,
        discount_pct=50.01,
        url="https://example.com/test-product",
    )
