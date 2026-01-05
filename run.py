#!/usr/bin/env python3
"""
Price Monitor - Entry Point

Async price monitoring tool with Discord alerts.

Usage:
    python run.py                    # Run continuous monitoring
    python run.py --test             # Single check cycle (dry run)
    python run.py --test-webhook     # Test Discord webhook connection
    python run.py --interval 30      # Custom check interval
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from price_monitor.config import CHECK_INTERVAL_SECONDS, DISCORD_WEBHOOK_URL
from price_monitor.monitor import PriceMonitor
from price_monitor.notifier import send_test_alert

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("price_monitor")


async def test_webhook() -> bool:
    """Test Discord webhook connectivity."""
    print("\n🔔 Testing Discord Webhook...")
    
    if not DISCORD_WEBHOOK_URL:
        print("❌ DISCORD_WEBHOOK_URL not set!")
        print("   Set it in .env file or as environment variable.")
        print("   Example: export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'")
        return False
    
    print(f"   Webhook URL: {DISCORD_WEBHOOK_URL[:50]}...")
    
    success = await send_test_alert()
    
    if success:
        print("✅ Test alert sent successfully! Check your Discord channel.")
    else:
        print("❌ Failed to send test alert. Check logs for details.")
    
    return success


async def run_single_check(targets_path: Path) -> None:
    """Run a single check cycle (for testing)."""
    print(f"\n🔍 Running single check cycle on {targets_path}...")
    
    monitor = PriceMonitor.from_json(targets_path, use_playwright=True)
    await monitor.run_once()
    
    print("\n📊 Results:")
    for target in monitor.targets:
        status = "✓" if target.last_price else "✗"
        price = f"${target.last_price:.2f}" if target.last_price else "Not found"
        print(f"   {status} {target.name}: {price} (target: ${target.target_price:.2f})")


async def run_continuous(targets_path: Path) -> None:
    """Run continuous monitoring."""
    print(f"\n🚀 Starting continuous price monitoring...")
    print(f"   Targets: {targets_path}")
    print(f"   Interval: {CHECK_INTERVAL_SECONDS}s (with jitter)")
    print(f"   Webhook: {'Configured' if DISCORD_WEBHOOK_URL else 'NOT SET'}")
    print("\n   Press Ctrl+C to stop.\n")
    
    monitor = PriceMonitor.from_json(targets_path, use_playwright=True)
    
    try:
        await monitor.run()
    except KeyboardInterrupt:
        monitor.stop()
        print("\n\n👋 Monitor stopped.")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Async Price Monitor with Discord Alerts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--targets",
        type=Path,
        default=Path("targets.json"),
        help="Path to targets.json file (default: targets.json)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run single check cycle and exit",
    )
    parser.add_argument(
        "--test-webhook",
        action="store_true",
        help="Test Discord webhook connection and exit",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help=f"Check interval in seconds (default: {CHECK_INTERVAL_SECONDS})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Override interval if specified
    if args.interval:
        from price_monitor import config
        config.CHECK_INTERVAL_SECONDS = args.interval
    
    # Test webhook mode
    if args.test_webhook:
        return 0 if asyncio.run(test_webhook()) else 1
    
    # Validate targets file
    if not args.targets.exists():
        print(f"❌ Targets file not found: {args.targets}")
        print("   Create a targets.json with your monitored products.")
        return 1
    
    # Run mode
    if args.test:
        asyncio.run(run_single_check(args.targets))
    else:
        asyncio.run(run_continuous(args.targets))
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
