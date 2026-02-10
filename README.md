# Volatility Bot

A Telegram bot that analyzes crypto market volatility using Bybit market data.

## What it does

- Validates symbols on Bybit across `linear`, `inverse`, and `spot` markets.
- Downloads up to 1000 historical daily candles.
- Calculates volatility and risk metrics, including:
  - Daily and weekly volatility (log-return based)
  - Max daily surge/crash
  - Intraday pump/dump extremes
  - ATR (14/28) and ATR relative to current price
  - Pump percentiles (75/80/85/90/95/99)
- Supports funding-rate features:
  - `/funding` command for most negative funding rates
  - Background scan for extreme negative funding rates

## Repository structure

- `bot.py` — Telegram bot entrypoint and command/message handlers.
- `TickerGrubProServer.py` — Core market validation, data fetching, and analysis logic.
- `add_func.py` — Funding-rate data collection and alert helpers.
- `requirements.txt` — Python dependencies.
- `TickerGrubProServer.service` — Example systemd unit file.
- `stats_dictionary_example.md` — Example shape of computed stats.

## Requirements

- Python 3.10+ recommended
- A Telegram bot token
- Internet connectivity to reach:
  - Telegram Bot API
  - Bybit API (`api.bybit.com`)

## Installation

```bash
git clone <your-fork-or-repo-url>
cd Volatility-Bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

`bot.py` currently contains a hardcoded token. For safer operation, prefer using an environment variable.

Example shell setup:

```bash
export TELEGRAM_BOT_TOKEN="<your-telegram-bot-token>"
```

Then update `bot.py` to read from `os.getenv("TELEGRAM_BOT_TOKEN")` before launching the bot.

## Run locally

```bash
python bot.py
```

Once running, in Telegram:

- `/start` to initialize the bot and begin background funding scan for your chat.
- Send a ticker like `BTC` or `PEPE` to get volatility analysis.
- `/funding` to view the top negative funding rates.

## Background funding scan behavior

- A repeating job is created per chat after `/start` (or interaction).
- Interval is 20 minutes.
- The job sends alerts when funding rates are at or below the configured threshold in `add_func.py`.

## Deployment (systemd)

A sample service file is included: `TickerGrubProServer.service`.

Typical setup flow:

1. Copy service file to `/etc/systemd/system/`.
2. Adjust `User`, `WorkingDirectory`, and `ExecStart` for your environment.
3. Reload and enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now TickerGrubProServer.service
sudo systemctl status TickerGrubProServer.service
```

## Notes

- The bot depends on live external APIs; failures can occur due to network issues or API limits.
- If Bybit changes response shapes, helper logic in `TickerGrubProServer.py` and `add_func.py` may need updates.
