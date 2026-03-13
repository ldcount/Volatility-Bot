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
  - Background scan for extreme negative funding rates with configurable frequency

## Bot commands

| Command | Description |
|---------|-------------|
| `/start` | Initialize the bot and begin the background funding scan for your chat. |
| `/funding` | Fetch the top 10 most negative funding rates on Bybit right now. |
| `/frequency <minutes>` | Set how often the background scan runs. E.g. `/frequency 30` = every 30 min, `/frequency 1` = every minute. |
| `/help` | Show the full list of commands with explanations. |
| `<TICKER>` | Send any coin name (e.g. `BTC`, `PEPE`) for a full volatility report. |

## Repository structure

- `volatility_bot.py` — Telegram bot entrypoint and command/message handlers.
- `data_processing.py` — Core market validation, data fetching, and analysis logic.
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

Create a `.env` file in the project root (see `.env.example` if present) with the following keys:

```env
TELEGRAM_TOKEN_PROD=<your-telegram-bot-token>
FUNDING_THRESHOLD=-0.015     # Alert when funding rate is at or below this value
SCAN_INTERVAL=1200           # Default background scan interval in seconds (20 min)
```

The scan interval can also be changed at runtime via the `/frequency` command without restarting the bot.

## Run locally

```bash
python volatility_bot.py
```

Once running, in Telegram:

- `/start` — initialize the bot and begin background funding scan.
- `/funding` — view the top negative funding rates on demand.
- `/frequency 30` — change the background scan to run every 30 minutes.
- `/help` — view all available commands.
- Send a ticker like `BTC` or `PEPE` to get a volatility analysis report.

## Background funding scan behavior

- A repeating job is created per chat after `/start` (or on first interaction).
- Default interval is controlled by `SCAN_INTERVAL` in `.env` (default: 1200 s / 20 min).
- The interval can be changed live at any time with `/frequency <minutes>`.
- The job sends alerts when funding rates are at or below the configured threshold.

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
- If Bybit changes response shapes, helper logic in `data_processing.py` and `add_func.py` may need updates.
