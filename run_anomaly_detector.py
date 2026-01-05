#!/usr/bin/env python3
"""
Category-Wide Pricing Anomaly Detector

Scrapes Amazon.ca Warehouse Deals category, stores price history in SQLite,
and alerts on statistical anomalies via Discord.

Usage:
    python run_anomaly_detector.py              # Run once
    python run_anomaly_detector.py --schedule   # Run every 4 hours
    python run_anomaly_detector.py --first-run  # Populate DB (no alerts)
    python run_anomaly_detector.py --test-db    # Verify database
    python run_anomaly_detector.py --test-alert # Test Discord webhook
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from anomaly_detector.database import PriceDatabase
from anomaly_detector.scrapers import get_scraper, get_all_sites, get_site_categories
from anomaly_detector.scrapers.base import DEFAULT_MIN_PRICE
from anomaly_detector.analyzer import AnomalyAnalyzer
from anomaly_detector.alerter import send_anomaly_alert, send_test_anomaly_alert

# Configuration
DEFAULT_INTERVAL_HOURS = 4
DEFAULT_MAX_PAGES = 20  # Increased to cover more products
DB_PATH = Path(__file__).parent / "prices.db"

logger = logging.getLogger(__name__)


async def run_detection_cycle(
    db: PriceDatabase,
    scraper,  # BaseScraper instance
    analyzer: AnomalyAnalyzer,
    skip_alerts: bool = False,
) -> dict:
    """
    Run a single detection cycle:
    1. Scrape category page
    2. Store prices in database
    3. Analyze for anomalies
    4. Send alerts if detected
    
    Returns summary statistics.
    """
    stats = {
        "items_scraped": 0,
        "items_stored": 0,
        "anomalies_detected": 0,
        "alerts_sent": 0,
        "errors": 0,
    }
    
    # Step 1: Scrape
    logger.info("Starting category scrape...")
    items = await scraper.scrape()
    stats["items_scraped"] = len(items)
    
    if not items:
        logger.warning("No items scraped. Check connection or selectors.")
        return stats
    
    logger.info(f"Scraped {len(items)} items")
    
    # Step 2: Store and analyze each item
    for item in items:
        try:
            # Upsert item (now with source)
            item_id = db.upsert_item(
                sku=item.sku,
                title=item.title,
                source=item.source,
                url=item.url,
            )
            
            # Get price history BEFORE adding new price
            history = db.get_all_prices_for_item(item_id)
            
            # Add new price
            db.add_price(item_id, item.price)
            stats["items_stored"] += 1
            
            # Skip analysis if first run or insufficient history
            if skip_alerts or len(history) < analyzer.MIN_HISTORY_FOR_DROP:
                continue
            
            # Step 3: Analyze for anomalies
            result = analyzer.analyze(item.price, history)
            
            if result.is_anomaly:
                stats["anomalies_detected"] += 1
                logger.info(
                    f"[{item.source}] ANOMALY: {item.title[:50]}... "
                    f"${item.price:.2f} (Z={result.zscore:.2f}, Drop={result.drop_percent:.1f}%)"
                )
                
                # Step 4: Send alert
                if analyzer.should_alert(result):
                    success = await send_anomaly_alert(
                        item_title=f"[{item.source.upper()}] {item.title}",
                        item_url=item.url,
                        result=result,
                        asin=item.sku,
                    )
                    if success:
                        stats["alerts_sent"] += 1
                    
        except Exception as e:
            logger.error(f"Error processing {item.sku}: {e}")
            stats["errors"] += 1
    
    return stats


async def run_with_schedule(
    interval_hours: float = DEFAULT_INTERVAL_HOURS,
    site: str = "amazon",
    category: str = "electronics",
    max_pages: int = DEFAULT_MAX_PAGES,
    min_price: float = DEFAULT_MIN_PRICE,
):
    """Run detection in a loop with the specified interval."""
    db = PriceDatabase(DB_PATH)
    
    # Get scraper for site
    scraper = get_scraper(site, category, max_pages=max_pages, min_price=min_price, headless=True)
    analyzer = AnomalyAnalyzer()
    
    interval_seconds = interval_hours * 3600
    
    logger.info(f"Starting scheduled detector (interval: {interval_hours}h)")
    logger.info(f"Database: {DB_PATH}")
    logger.info(f"Items in DB: {db.get_item_count()}, Price points: {db.get_price_count()}")
    
    cycle = 0
    while True:
        cycle += 1
        start_time = datetime.now()
        logger.info(f"\n{'='*60}")
        logger.info(f"Cycle {cycle} starting at {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'='*60}")
        
        try:
            if isinstance(scraper, list):
                aggregated = {
                    "items_scraped": 0,
                    "items_stored": 0,
                    "anomalies_detected": 0,
                    "alerts_sent": 0,
                    "errors": 0,
                }
                for s in scraper:
                    sub_stats = await run_detection_cycle(db, s, analyzer)
                    for k in aggregated:
                        aggregated[k] += sub_stats.get(k, 0)
                stats = aggregated
            else:
                stats = await run_detection_cycle(db, scraper, analyzer)

            logger.info(f"\nCycle {cycle} complete:")
            logger.info(f"  Items scraped: {stats['items_scraped']}")
            logger.info(f"  Items stored: {stats['items_stored']}")
            logger.info(f"  Anomalies: {stats['anomalies_detected']}")
            logger.info(f"  Alerts sent: {stats['alerts_sent']}")
            if stats['errors']:
                logger.warning(f"  Errors: {stats['errors']}")
            
            logger.info(f"\nCycle {cycle} complete:")
            logger.info(f"  Items scraped: {stats['items_scraped']}")
            logger.info(f"  Items stored: {stats['items_stored']}")
            logger.info(f"  Anomalies: {stats['anomalies_detected']}")
            logger.info(f"  Alerts sent: {stats['alerts_sent']}")
            if stats['errors']:
                logger.warning(f"  Errors: {stats['errors']}")
                
        except Exception as e:
            logger.error(f"Cycle {cycle} failed: {e}")
        
        logger.info(f"\nNext cycle in {interval_hours} hours...")
        await asyncio.sleep(interval_seconds)


async def run_once(
    first_run: bool = False,
    site: str = "amazon",
    category: str = "electronics",
    max_pages: int = DEFAULT_MAX_PAGES,
    min_price: float = DEFAULT_MIN_PRICE,
):
    """Run a single detection cycle."""
    db = PriceDatabase(DB_PATH)
    
    # Get scraper for site
    scraper = get_scraper(site, category, max_pages=max_pages, min_price=min_price, headless=True)
    analyzer = AnomalyAnalyzer()
    
    mode = "FIRST RUN (no alerts)" if first_run else "SINGLE RUN"
    logger.info(f"\n{'='*60}")
    logger.info(f"Anomaly Detector - {mode}")
    logger.info(f"{'='*60}")
    logger.info(f"Site: {site} | Category: {category} ({max_pages} pages, min ${min_price})")
    logger.info(f"Database: {DB_PATH}")
    logger.info(f"Items in DB: {db.get_item_count()}, Price points: {db.get_price_count()}")
    
    if isinstance(scraper, list):
        aggregated = {
            "items_scraped": 0,
            "items_stored": 0,
            "anomalies_detected": 0,
            "alerts_sent": 0,
            "errors": 0,
        }
        logger.info(f"Processing {len(scraper)} categories...")
        for i, s in enumerate(scraper, 1):
            logger.info(f"--- Category {i}/{len(scraper)}: {s.category_url} ---")
            sub_stats = await run_detection_cycle(db, s, analyzer, skip_alerts=first_run)
            for k in aggregated:
                aggregated[k] += sub_stats.get(k, 0)
        stats = aggregated
    else:
        stats = await run_detection_cycle(db, scraper, analyzer, skip_alerts=first_run)
    
    print(f"\n{'='*60}")
    print(f"Results:")
    print(f"{'='*60}")
    print(f"  Items scraped:  {stats['items_scraped']}")
    print(f"  Items stored:   {stats['items_stored']}")
    print(f"  Anomalies:      {stats['anomalies_detected']}")
    print(f"  Alerts sent:    {stats['alerts_sent']}")
    if stats['errors']:
        print(f"  Errors:         {stats['errors']}")
    print(f"\nDatabase now contains:")
    print(f"  Total items:    {db.get_item_count()}")
    print(f"  Total prices:   {db.get_price_count()}")


async def test_database():
    """Test database connection and schema."""
    print(f"\n{'='*60}")
    print("Database Test")
    print(f"{'='*60}")
    
    db = PriceDatabase(DB_PATH)
    
    if db.verify_schema():
        print(f"✓ Database schema verified at {DB_PATH}")
        print(f"  Items:  {db.get_item_count()}")
        print(f"  Prices: {db.get_price_count()}")
        return True
    else:
        print("✗ Database schema verification failed")
        return False


async def test_alert():
    """Test Discord webhook with a sample alert."""
    print(f"\n{'='*60}")
    print("Discord Webhook Test")
    print(f"{'='*60}")
    
    success = await send_test_anomaly_alert()
    
    if success:
        print("✓ Test alert sent successfully!")
    else:
        print("✗ Failed to send test alert. Check DISCORD_WEBHOOK_URL in .env")
    
    return success


def main():
    parser = argparse.ArgumentParser(
        description="Category-Wide Pricing Anomaly Detector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    
    parser.add_argument(
        "--schedule",
        action="store_true",
        help=f"Run continuously every {DEFAULT_INTERVAL_HOURS} hours",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_HOURS,
        metavar="HOURS",
        help=f"Interval between cycles (default: {DEFAULT_INTERVAL_HOURS}h)",
    )
    parser.add_argument(
        "--first-run",
        action="store_true",
        help="Populate database with initial data (no alerts)",
    )
    parser.add_argument(
        "--test-db",
        action="store_true",
        help="Test database connection and schema",
    )
    parser.add_argument(
        "--test-alert",
        action="store_true",
        help="Send a test alert to Discord",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--site",
        type=str,
        default="amazon",
        choices=get_all_sites(),
        help=f"Retailer to scrape (default: amazon). Options: {', '.join(get_all_sites())}",
    )
    parser.add_argument(
        "--category",
        type=str,
        default="electronics",
        help="Category to scrape (varies by site). Use --help to see available categories.",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        metavar="N",
        help=f"Number of pages to scrape (default: {DEFAULT_MAX_PAGES})",
    )
    parser.add_argument(
        "--min-price",
        type=float,
        default=DEFAULT_MIN_PRICE,
        metavar="PRICE",
        help=f"Minimum price filter in CAD (default: ${DEFAULT_MIN_PRICE})",
    )
    
    args = parser.parse_args()
    
    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    
    # Suppress noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    
    # Run appropriate mode
    if args.test_db:
        asyncio.run(test_database())
    elif args.test_alert:
        asyncio.run(test_alert())
    elif args.schedule:
        try:
            asyncio.run(run_with_schedule(
                interval_hours=args.interval,
                site=args.site,
                category=args.category,
                max_pages=args.pages,
                min_price=args.min_price,
            ))
        except KeyboardInterrupt:
            print("\n\nStopped by user.")
    else:
        asyncio.run(run_once(
            first_run=args.first_run,
            site=args.site,
            category=args.category,
            max_pages=args.pages,
            min_price=args.min_price,
        ))


if __name__ == "__main__":
    main()
