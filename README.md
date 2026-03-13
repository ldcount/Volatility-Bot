# Volatility Bot

Telegram bot for crypto volatility and funding-rate monitoring using Bybit market data, with OKX funding cross-checks.

## Features

- Full volatility report with `/ticker <symbol>`
- Multi-symbol comparison with `/compare`
- Negative funding ranking with `/funding`
- Live funding alert threshold changes with `/rate`
- Background funding scan with configurable `/frequency`
- Volatility leaderboard with `/topvol`
- Practical ATR / ladder heuristic with `/risk`
- Inline Telegram buttons for refresh, funding, top-vol ranking, threshold help, and scan-frequency help

## Commands

| Command | What it does |
| --- | --- |
| `/start` | Starts the bot for the current chat and enables the repeating background funding scan. |
| `/ticker BTC` | Builds the full volatility report for one symbol. Plain text ticker messages are intentionally not supported anymore. |
| `/compare BTC ETH SOL` | Compares up to 5 symbols in one message. |
| `/funding` | Shows the most negative funding rates on Bybit right now. |
| `/funding 15` | Same as above, but with a custom result count. |
| `/rate -1.8` | Sets the funding alert threshold to -1.80% for the current chat. |
| `/rate -0.018` | Same threshold format, using decimal form instead of percentage form. |
| `/frequency 30` | Sets the background funding scan interval to every 30 minutes for the current chat. |
| `/topvol` | Ranks the most volatile liquid Bybit linear symbols by daily volatility. |
| `/topvol weekly 8` | Ranks by weekly volatility and returns 8 names. |
| `/risk BTC` | Shows ATR-based risk framing and ladder spacing heuristics for one symbol. |
| `/help` | Displays the command list. |

## Typical Usage

1. Start the bot with `/start`.
2. Ask for single-symbol analysis with `/ticker BTC`.
3. Compare names with `/compare BTC ETH SOL`.
4. Check negative funding with `/funding`.
5. Set the alert trigger with `/rate -1.8`.
6. Adjust scan frequency with `/frequency 15`.
7. Explore momentum / noise leaders with `/topvol`.
8. Get risk framing with `/risk BTC`.

## Inline Buttons

After most bot responses you will see Telegram buttons:

- `Refresh`: reruns the last ticker analysis
- `Risk`: opens the ATR / ladder heuristic for that symbol
- `Funding`: opens the negative funding ranking
- `Top Vol`: opens the volatility leaderboard
- `Set Rate`: reminds you how to change the live funding threshold
- `Frequency`: reminds you how to change the scan interval

## Funding Alerts

The bot can scan funding rates in the background and notify the current chat when funding drops below your chosen threshold.

- Default threshold comes from `.env` via `FUNDING_THRESHOLD`
- You can override it live in Telegram with `/rate`
- The override is chat-specific while the bot process is running

Examples:

```text
/rate -1.8
/rate -2.25
/rate -0.018
```

All three forms mean “alert me when funding is at or below this negative level”.

## Error Handling

The bot now distinguishes between several failure cases:

- symbol not found on Bybit
- network failure while contacting the exchange
- exchange timeout
- empty candle response
- insufficient historical data

That makes it easier to tell whether the issue is your input or the exchange/API.

## Performance Notes

- Bybit instrument metadata is cached to avoid re-validating the full symbol universe on every request.
- OKX funding lookups are fetched in parallel to speed up funding reports and alerts.
- `/topvol` only evaluates the most liquid Bybit linear symbols first, which keeps the ranking responsive.

## Project Layout

- `volatility_bot.py` - Telegram bot entrypoint and command handlers
- `data_processing.py` - Bybit validation, candle downloads, cached metadata, volatility analysis
- `add_func.py` - Funding data collection and OKX cross-check logic
- `requirements.txt` - Python dependencies
- `volatility_bot.service` - Example systemd unit

## Requirements

- Python 3.10+
- Telegram bot token
- Internet access to:
  - `api.telegram.org`
  - `api.bybit.com`
  - `www.okx.com`

## Configuration

Create a `.env` file in the project root:

```env
TELEGRAM_TOKEN_PROD=<your-telegram-bot-token>
FUNDING_THRESHOLD=-0.015
SCAN_INTERVAL=1200
```

Meaning:

- `TELEGRAM_TOKEN_PROD`: Telegram bot token
- `FUNDING_THRESHOLD`: default alert threshold, in decimal form (`-0.015` = `-1.5%`)
- `SCAN_INTERVAL`: default background scan interval in seconds (`1200` = 20 minutes)

## Local Run

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python volatility_bot.py
```

## Deployment

The repository includes:

- `volatility_bot.service` for `systemd`
- `.github/workflows/deploy.yml` for GitHub Actions deployment

Typical server layout:

- code in `/opt/bots/volatility_bot`
- virtualenv in `/opt/bots/volatility_bot/venv`
- local runtime config in `/opt/bots/volatility_bot/.env`

## Notes

- The bot is designed around command usage. Plain text ticker messages intentionally do not trigger analysis anymore.
- `/risk` output is a statistical heuristic, not financial advice.
- If Bybit or OKX change response formats, helper logic may need updates.
