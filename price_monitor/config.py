"""Configuration settings for the price monitor."""

import os
from dotenv import load_dotenv

load_dotenv()

# Monitoring intervals
CHECK_INTERVAL_SECONDS: int = int(os.getenv("CHECK_INTERVAL", "60"))
JITTER_SECONDS: int = 15  # ±15s randomization to avoid pattern detection

# Cooldown settings for blocked requests
COOLDOWN_MINUTES: int = 30

# Alert thresholds
FLASH_SALE_THRESHOLD: float = 0.40  # Trigger alert if price drops by >40%

# Discord webhook
DISCORD_WEBHOOK_URL: str | None = os.getenv("DISCORD_WEBHOOK_URL")

# HTTP settings
REQUEST_TIMEOUT_SECONDS: int = 30
MAX_RETRIES: int = 3
