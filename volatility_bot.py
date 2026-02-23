import logging
import asyncio
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
from telegram import Update, LinkPreviewOptions
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)

# IMPORT YOUR EXISTING MODULES
from data_processing import validate_ticker, fetch_market_data, analyze_market_data
from add_func import get_top_funding_rates, check_extreme_funding  # [NEW]

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
    """Sends a welcome message and starts background jobs."""
    await update.message.reply_text(
        "👋 I am the Volatility Bot.\n"
        "Send me a ticker (e.g., PEPE) to analyze.\n\n"
        "Commands:\n"
        "/funding — top negative funding rates\n"
        "/frequency <min> — set background scan interval\n"
        "/help — list all commands"
    )

    # Start background job immediately
    chat_id = update.effective_chat.id
    start_scanning_job(context, chat_id)


async def funding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the top 10 negative funding rates."""
    status_msg = await update.message.reply_text("🔍 Fetching funding rates...")

    # Run in executor to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    report = await loop.run_in_executor(None, get_top_funding_rates)

    await status_msg.edit_text(
        report,
        parse_mode="Markdown",
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def scan_funding_job(context: ContextTypes.DEFAULT_TYPE):
    """Background task to scan for extreme funding rates."""
    # Run in executor
    loop = asyncio.get_event_loop()
    # Use default threshold from add_func (-0.01) or specify it here if needed.
    # User wanted -0.01 (1%)
    # Get threshold from env, default to -0.015 if not set
    threshold = float(os.getenv("FUNDING_THRESHOLD", -0.015))
    report = await loop.run_in_executor(None, check_extreme_funding, threshold)

    if report:
        # Send to the user who started the bot?
        # Since we don't have a database of users, we can try to send to the chat_id from context.job.chat_id
        # or broadcast if we had a list.
        # For this simple bot, we'll assume the job is started with a chat_id.
        job = context.job
        if job.chat_id:
            await context.bot.send_message(
                job.chat_id,
                text=report,
                parse_mode="Markdown",
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        else:
            print("[Job] Error: No chat_id in job context.")


def start_scanning_job(context, chat_id, interval_seconds: int | None = None):
    """Helper to start (or restart) the background scanning job.

    If *interval_seconds* is provided the existing job is cancelled and a new
    one is created with the new interval.  Otherwise the job is only started
    when it is not already running.
    """
    if interval_seconds is None:
        # Use a previously saved interval, or fall back to the .env default.
        interval_seconds = context.bot_data.get(
            f"scan_interval_{chat_id}",
            int(os.getenv("SCAN_INTERVAL", 1200)),
        )

    try:
        if context.job_queue:
            current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
            if current_jobs:
                if interval_seconds is None:
                    # Already running, nothing to do.
                    return
                # Cancel existing jobs before re-scheduling.
                for job in current_jobs:
                    job.schedule_removal()

            context.job_queue.run_repeating(
                scan_funding_job,
                interval=interval_seconds,
                first=10,
                chat_id=chat_id,
                name=str(chat_id),
            )
            # Persist so future restarts/reschedules remember the value.
            context.bot_data[f"scan_interval_{chat_id}"] = interval_seconds
            print(
                f"[System] Background funding scan for chat {chat_id} "
                f"set to every {interval_seconds}s."
            )
        else:
            print(
                "[System] Warning: JobQueue not available. Background scanning disabled."
            )
    except Exception as e:
        print(f"[System] Error initializing background job: {e}")


async def frequency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set the background scan interval. Usage: /frequency <minutes>"""
    chat_id = update.effective_chat.id

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "⚠️ Usage: /frequency <minutes>\n"
            "Example: /frequency 30  →  scan every 30 minutes"
        )
        return

    minutes = int(context.args[0])
    if minutes < 1:
        await update.message.reply_text("⚠️ Interval must be at least 1 minute.")
        return

    interval_seconds = minutes * 60
    start_scanning_job(context, chat_id, interval_seconds=interval_seconds)
    await update.message.reply_text(
        f"✅ Background scan interval updated to every {minutes} minute(s)."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a concise list of all available bot commands."""
    help_text = (
        "🤖 *Volatility Bot — Available Commands*\n\n"
        "/start — Initialize the bot and start background funding scan\n"
        "/funding — Fetch the top 10 most negative funding rates right now\n"
        "/frequency <min> — Change how often the background scan runs "
        "(e.g. `/frequency 30` = every 30 min)\n"
        "/help — Show this help message\n\n"
        "💬 *Ticker analysis*\n"
        "Send any coin name (e.g. `BTC`, `PEPE`) to receive a full "
        "volatility report with ATR, pump/dump extremes, and DCA levels."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """The Main Event Loop: logic from your old 'main()' goes here."""
    global REQUEST_COUNT
    REQUEST_COUNT += 1

    # Check if we should start the background job for this chat (singleton check logic could be added here)
    # For simplicity, we just ensure the job is running or start it when user interacts?
    # Better approach: Start it on /start or just ensure it's added.
    # But job_queue needs a chat_id to know where to send messages.
    # Let's add the job if it doesn't exist for this chat.
    # Check if we should start the background job for this chat
    chat_id = update.effective_chat.id
    start_scanning_job(context, chat_id)

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
    TOKEN = os.getenv("TELEGRAM_TOKEN_PROD")

    # development token for DevelopmentDloBot
    # TOKEN = os.getenv("TELEGRAM_TOKEN_DEV")

    if not TOKEN:
        print("Error: TELEGRAM_TOKEN_PROD not found in .env file.")
        exit(1)

    application = ApplicationBuilder().token(TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("funding", funding))
    application.add_handler(CommandHandler("frequency", frequency))
    application.add_handler(CommandHandler("help", help_command))

    # This handler listens to ALL text messages that aren't commands
    application.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    )

    # Run forever
    application.run_polling()
