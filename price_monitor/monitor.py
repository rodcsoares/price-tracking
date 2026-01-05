"""Core price monitoring logic with async concurrency."""

import asyncio
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx

from .config import (
    CHECK_INTERVAL_SECONDS,
    COOLDOWN_MINUTES,
    FLASH_SALE_THRESHOLD,
    JITTER_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
)
from .extractor import extract_price_from_html, extract_price_with_playwright
from .notifier import send_discord_alert
from .user_agents import get_random_user_agent

logger = logging.getLogger(__name__)


@dataclass
class Target:
    """A monitored product target."""
    name: str
    url: str
    target_price: float
    last_price: Optional[float] = None
    cooldown_until: Optional[datetime] = None
    check_count: int = 0
    last_checked: Optional[datetime] = None


@dataclass
class PriceMonitor:
    """Async price monitor with jitter, rotation, and cooldown."""
    
    targets: list[Target] = field(default_factory=list)
    use_playwright_fallback: bool = True
    _running: bool = False
    
    @classmethod
    def from_json(cls, path: str | Path, use_playwright: bool = True) -> "PriceMonitor":
        """Load targets from a JSON file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Targets file not found: {path}")
        
        with open(path) as f:
            data = json.load(f)
        
        targets = [
            Target(
                name=item["name"],
                url=item["url"],
                target_price=float(item["target_price"]),
            )
            for item in data
        ]
        
        logger.info(f"Loaded {len(targets)} targets from {path}")
        return cls(targets=targets, use_playwright_fallback=use_playwright)
    
    def _get_jittered_delay(self) -> float:
        """Get check interval with random jitter (±JITTER_SECONDS)."""
        jitter = random.uniform(-JITTER_SECONDS, JITTER_SECONDS)
        delay = CHECK_INTERVAL_SECONDS + jitter
        return max(5, delay)  # Minimum 5 seconds
    
    def _is_in_cooldown(self, target: Target) -> bool:
        """Check if a target is in cooldown mode."""
        if target.cooldown_until is None:
            return False
        if datetime.now() >= target.cooldown_until:
            target.cooldown_until = None
            logger.info(f"[{target.name}] Cooldown ended, resuming checks")
            return False
        return True
    
    def _enter_cooldown(self, target: Target) -> None:
        """Put a target in cooldown mode after being blocked."""
        target.cooldown_until = datetime.now() + timedelta(minutes=COOLDOWN_MINUTES)
        logger.warning(
            f"[{target.name}] Entered cooldown mode until "
            f"{target.cooldown_until.strftime('%H:%M:%S')}"
        )
    
    async def check_price(self, target: Target) -> Optional[float]:
        """
        Fetch and extract price for a single target.
        
        Returns the extracted price or None if failed.
        """
        if self._is_in_cooldown(target):
            remaining = (target.cooldown_until - datetime.now()).seconds // 60
            logger.debug(f"[{target.name}] In cooldown, {remaining}m remaining")
            return None
        
        headers = {
            "User-Agent": get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        
        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT_SECONDS,
                follow_redirects=True,
            ) as client:
                logger.debug(f"[{target.name}] Fetching {target.url}")
                response = await client.get(target.url, headers=headers)
                
                # Check for blocking responses
                if response.status_code in (403, 503):
                    logger.warning(f"[{target.name}] Blocked with {response.status_code}")
                    self._enter_cooldown(target)
                    return None
                
                response.raise_for_status()
                html = response.text
                
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (403, 503):
                self._enter_cooldown(target)
            else:
                logger.error(f"[{target.name}] HTTP error: {e}")
            return None
        except httpx.RequestError as e:
            logger.error(f"[{target.name}] Request failed: {e}")
            return None
        
        # For known retailers (Amazon, BestBuy, etc), use Playwright directly
        # as regex is unreliable (picks up ads, accessories, etc.)
        url_lower = target.url.lower()
        needs_playwright = any(site in url_lower for site in ["amazon", "bestbuy", "newegg", "walmart"])
        
        if needs_playwright and self.use_playwright_fallback:
            # Go straight to Playwright for reliable extraction
            logger.debug(f"[{target.name}] Using Playwright for retailer site")
            price = await extract_price_with_playwright(target.url)
        else:
            # Use regex for other sites
            price = extract_price_from_html(html, target.url)
            
            # Fallback to Playwright if regex failed
            if price is None and self.use_playwright_fallback:
                logger.info(f"[{target.name}] Trying Playwright fallback...")
                price = await extract_price_with_playwright(target.url)
        
        target.check_count += 1
        target.last_checked = datetime.now()
        
        return price
    
    def _should_alert(self, target: Target, current_price: float) -> tuple[bool, str]:
        """
        Determine if an alert should be triggered.
        
        Returns (should_alert, reason).
        """
        # Always alert if below target price
        if current_price < target.target_price:
            return True, "below_target"
        
        # Check for flash sale (>40% drop from last known price)
        if target.last_price is not None:
            drop_pct = (target.last_price - current_price) / target.last_price
            if drop_pct > FLASH_SALE_THRESHOLD:
                return True, "flash_sale"
        
        return False, ""
    
    async def process_target(self, target: Target) -> None:
        """Process a single target: check price and alert if needed."""
        current_price = await self.check_price(target)
        
        if current_price is None:
            return
        
        should_alert, reason = self._should_alert(target, current_price)
        
        if should_alert:
            # Calculate discount percentage
            if target.last_price:
                discount = ((target.last_price - current_price) / target.last_price) * 100
            else:
                discount = ((target.target_price - current_price) / target.target_price) * 100
            
            logger.info(
                f"[{target.name}] 🚨 Alert triggered ({reason}): "
                f"${target.last_price or target.target_price:.2f} → ${current_price:.2f} "
                f"({discount:.1f}% off)"
            )
            
            await send_discord_alert(
                product_name=target.name,
                old_price=target.last_price or target.target_price,
                new_price=current_price,
                discount_pct=discount,
                url=target.url,
            )
        else:
            logger.debug(
                f"[{target.name}] Price: ${current_price:.2f} "
                f"(target: ${target.target_price:.2f})"
            )
        
        # Update last known price
        target.last_price = current_price
    
    async def run_once(self) -> None:
        """Run a single check cycle on all targets concurrently."""
        logger.info(f"Starting check cycle for {len(self.targets)} targets...")
        
        tasks = [self.process_target(target) for target in self.targets]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        logger.info("Check cycle complete")
    
    async def run(self) -> None:
        """Run the monitor loop indefinitely with jittered intervals."""
        self._running = True
        logger.info(
            f"Price monitor started. Checking {len(self.targets)} targets "
            f"every {CHECK_INTERVAL_SECONDS}s (±{JITTER_SECONDS}s jitter)"
        )
        
        while self._running:
            await self.run_once()
            
            delay = self._get_jittered_delay()
            logger.debug(f"Next check in {delay:.1f}s")
            await asyncio.sleep(delay)
    
    def stop(self) -> None:
        """Stop the monitor loop."""
        self._running = False
        logger.info("Price monitor stopping...")
