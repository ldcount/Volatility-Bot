import logging
import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)

# IMPORT YOUR EXISTING MODULES
# Assuming your previous file is named 'TickerGrubProServer.py'
from TickerGrubProServer import validate_ticker, fetch_market_data, analyze_market_data

# 1. SETUP LOGGING (So you can see errors in the console)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# 2. ADD THIS LINE to silence the repetitive network logs
logging.getLogger("httpx").setLevel(logging.WARNING)

# Global Request Counter
REQUEST_COUNT = 0

# 2. THE HANDLERS (The new "Input/Output" layer)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message when the command /start is issued."""
    await update.message.reply_text(
        "I am the Volatility Bot. Send me a ticker (e.g., PEPE) to analyze."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """The Main Event Loop: logic from your old 'main()' goes here."""
    global REQUEST_COUNT
    REQUEST_COUNT += 1

    # A. Get Input (Replaces 'input()')
    user_text = update.message.text.strip().upper()

    # Notify user we are working (Logic takes time)
    status_msg = await update.message.reply_text(f"🔍 Checking {user_text}...")

    # B. Gatekeeper Logic
    # Fix Ticker
    if not user_text.endswith("USDT"):
        target_symbol = user_text + "USDT"
    else:
        target_symbol = user_text

    # Run Validator (Non-blocking now)
    loop = asyncio.get_event_loop()
    exists, category = await loop.run_in_executor(None, validate_ticker, target_symbol)

    if not exists:
        await status_msg.edit_text(f"❌ Symbol {target_symbol} not found on Bybit.")
        return

    await status_msg.edit_text(f"✅ Found in {category}. Downloading data...")

    # C. Harvester Logic
    # We pass the arguments: function, arg1, arg2, arg3 (interval="D")
    candles = await loop.run_in_executor(
        None, fetch_market_data, target_symbol, category, "D"
    )
    if not candles:
        await status_msg.edit_text("❌ Failed to download data.")
        return

    # D. Brain Logic
    stats = analyze_market_data(candles)

    if stats:
        # We use .6f for ATR to handle meme coins with many decimals (e.g., 0.000001)
        report = (
            f"📊 **{target_symbol} based on {len(candles)} candles**\n\n"
            f"📝 **DAILY STATS (close to close)**\n"
            f"Volatility (Day): {stats['vol_day']*100:.2f}%\n"
            f"Volatility (Week): {stats['vol_week']*100:.2f}%\n"
            f"Max daily surge: {stats['max_daily_surge']*100:.2f}%\n"
            f"Max daily crash: {stats['max_daily_crash']*100:.2f}%\n\n"
            f"⬆️ **INTRADAY PUMP EXTREMES**\n"
            f"=> open / high\n"
            f"Biggest Pump: {stats['max_pump_val']*100:.2f}% on {stats['max_pump_date']}\n"
            f"Average Pump: {stats['avg_pump']*100:.2f}%\n"
            f"Pump Deviation (Std): {stats['std_pump']*100:.2f}%\n\n"
            f"⬇️ **INTRADAY DUMP EXTREMES**\n"
            f"=> open / low\n"
            f"Worst Dump: {stats['max_dump_val']*100:.2f}% on {stats['max_dump_date']}\n"
            f"Average Dump: {stats['avg_dump']*100:.2f}%\n"
            f"Dump Deviation (Std): {stats['std_dump']*100:.2f}%\n\n"
            f"📏 **ATR (Average True Range)**\n"
            f"ATR 14: {stats['atr_14']:.6f}\n"
            f"ATR 28: {stats['atr_28']:.6f}\n"
            f"ATR 28 to close: {stats['atr_relative']*100:.2f}%\n\n"
            f"📈 **MARTINGALE BASED ON PERCENTILES**\n"
            f"1st DCA (75%): {stats['p75_pump']*100:.2f}%\n"
            f"2nd DCA (80%): {stats['p80_pump']*100:.2f}%\n"
            f"3rd DCA (85%): {stats['p85_pump']*100:.2f}%\n"
            f"4th DCA (90%): {stats['p90_pump']*100:.2f}%\n"
            f"5th DCA (95%): {stats['p95_pump']*100:.2f}%\n"
            f"6th DCA (99%): {stats['p99_pump']*100:.2f}%\n"
        )
    else:
        report = "⚠️ Error: Could not calculate stats. Not enough data?"

    # Send the final report
    # parse_mode='Markdown' allows bold text
    await update.message.reply_text(report, parse_mode="Markdown")

    # Log the successful request
    if candles:
        print(
            f"[Result] Request #{REQUEST_COUNT}: Sent report with {len(candles)} candles."
        )


# 3. THE ENGINE
if __name__ == "__main__":
    # original prod token
    #TOKEN = "8567746274:AAGUyI4c5Kt5uETiB9SbwMFbi8sPnOzqr8I"

    # development token for MyStrategyDevBot
    TOKEN = "8407333658:AAFOsgpuO-KhUTL-7VNQfqEQxHGYjRmrN7o"

    application = ApplicationBuilder().token(TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))

    # This handler listens to ALL text messages that aren't commands
    application.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    )

    # Run forever
    application.run_polling()
