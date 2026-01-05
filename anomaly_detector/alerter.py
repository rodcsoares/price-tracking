"""Discord webhook alerts for price anomalies."""

import logging
import httpx
from typing import Optional

from .analyzer import AnomalyResult, AnomalyType

# Import config from parent package
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from price_monitor.config import DISCORD_WEBHOOK_URL, REQUEST_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


async def send_anomaly_alert(
    item_title: str,
    item_url: str,
    result: AnomalyResult,
    asin: Optional[str] = None,
) -> bool:
    """
    Send a Discord alert for a detected price anomaly.
    
    Args:
        item_title: Product title
        item_url: Direct link to product
        result: AnomalyResult from analyzer
        asin: Optional ASIN for reference
    
    Returns:
        True if sent successfully, False otherwise
    """
    if not DISCORD_WEBHOOK_URL:
        logger.warning("Discord webhook URL not configured. Skipping alert.")
        logger.info(
            f"[ANOMALY] {item_title}: ${result.current_price:.2f} "
            f"(Z={result.zscore:.2f}, Drop={result.drop_percent:.1f}%)"
        )
        return False
    
    # Color based on severity
    severity_colors = {
        "CRITICAL": 0xFF0000,  # Red
        "HIGH": 0xFF6600,      # Orange  
        "MODERATE": 0xFFCC00,  # Yellow
        "NONE": 0x00CC00,      # Green
    }
    color = severity_colors.get(result.severity, 0x00CC00)
    
    # Build anomaly type description
    if result.anomaly_type == AnomalyType.BOTH:
        type_desc = "🚨 **Z-Score + Sudden Drop**"
    elif result.anomaly_type == AnomalyType.ZSCORE:
        type_desc = "📊 **Statistical Outlier** (Z-Score)"
    elif result.anomaly_type == AnomalyType.SUDDEN_DROP:
        type_desc = "📉 **Sudden Price Drop**"
    else:
        type_desc = "Unknown"
    
    # Truncate title if too long
    display_title = item_title[:100] + "..." if len(item_title) > 100 else item_title
    
    # Build the embed
    embed = {
        "title": f"🔔 Price Anomaly: {display_title}",
        "color": color,
        "fields": [
            {
                "name": "💰 Current Price",
                "value": f"**${result.current_price:.2f}**",
                "inline": True,
            },
            {
                "name": "📈 Historical Avg",
                "value": f"${result.mean_price:.2f}",
                "inline": True,
            },
            {
                "name": "📊 Z-Score",
                "value": f"{result.zscore:.2f}σ",
                "inline": True,
            },
            {
                "name": "📉 Drop %",
                "value": f"{result.drop_percent:.1f}%",
                "inline": True,
            },
            {
                "name": "🎯 Recent Avg",
                "value": f"${result.recent_avg:.2f}",
                "inline": True,
            },
            {
                "name": "📚 Data Points",
                "value": str(result.history_count),
                "inline": True,
            },
            {
                "name": "🏷️ Anomaly Type",
                "value": type_desc,
                "inline": False,
            },
        ],
        "url": item_url,
        "footer": {
            "text": f"Severity: {result.severity} • ASIN: {asin or 'N/A'} • Click title to view"
        },
    }
    
    payload = {"embeds": [embed]}
    
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(DISCORD_WEBHOOK_URL, json=payload)
            response.raise_for_status()
            logger.info(f"Discord anomaly alert sent for {display_title}")
            return True
    except httpx.HTTPStatusError as e:
        logger.error(f"Discord webhook error: {e.response.status_code} - {e.response.text}")
        return False
    except httpx.RequestError as e:
        logger.error(f"Discord webhook request failed: {e}")
        return False


async def send_test_anomaly_alert() -> bool:
    """Send a test anomaly alert to verify webhook connectivity."""
    test_result = AnomalyResult(
        is_anomaly=True,
        anomaly_type=AnomalyType.BOTH,
        current_price=29.99,
        mean_price=149.99,
        zscore=-4.2,
        drop_percent=75.0,
        recent_avg=124.99,
        history_count=25,
    )
    
    return await send_anomaly_alert(
        item_title="🧪 Test Product - Statistical Anomaly Detector",
        item_url="https://amazon.ca/dp/TEST123",
        result=test_result,
        asin="TEST123",
    )
