# Price Monitor 🔔

Async Python price monitoring tool with Discord alerts.

## Features

- **Async Concurrent Checks** — Monitor multiple URLs simultaneously using `httpx` + `asyncio`
- **Request Jitter** — Randomized intervals (±15s) to avoid pattern detection
- **User-Agent Rotation** — 12+ modern browser headers rotated per request
- **Smart Extraction** — Regex patterns with Playwright fallback for JS-rendered pages
- **Flash Sale Detection** — Alerts on >40% price drops or below target price
- **Discord Webhooks** — Rich embedded alerts with color-coded urgency
- **Cooldown Mode** — Auto-pause blocked URLs (403/503) for 30 minutes

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium  # Optional: for JS-rendered pages

# Configure Discord webhook
cp .env.example .env
# Edit .env and add your DISCORD_WEBHOOK_URL

# Add your targets
# Edit targets.json with product URLs and target prices

# Test run (single check cycle)
python run.py --test -v

# Run continuous monitoring
python run.py
```

## Configuration

Edit `.env`:
```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
CHECK_INTERVAL=60  # Optional: seconds between checks
```

Edit `targets.json`:
```json
[
  {
    "name": "Product Name",
    "url": "https://amazon.com/dp/...",
    "target_price": 49.99
  }
]
```

## CLI Options

```
python run.py                    # Continuous monitoring
python run.py --test             # Single check cycle
python run.py --test-webhook     # Test Discord connection
python run.py --interval 30      # Custom interval (seconds)
python run.py -v                 # Verbose logging
```

## Alert Triggers

1. **Below Target** — Current price < your target price
2. **Flash Sale** — Price drops by >40% from last known price

## Project Structure

```
├── price_monitor/
│   ├── config.py        # Settings (env-based)
│   ├── extractor.py     # Price extraction (regex + Playwright)
│   ├── monitor.py       # Core async monitoring logic
│   ├── notifier.py      # Discord webhook integration
│   └── user_agents.py   # UA rotation pool
├── run.py               # CLI entry point
├── targets.json         # Your monitored products
└── .env                 # Your Discord webhook URL
```
