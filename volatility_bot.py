import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from add_func import check_extreme_funding, get_top_funding_rates
from data_processing import (
    analyze_symbol,
    get_top_liquid_symbols,
    normalize_symbol,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)

REQUEST_COUNT = 0
DEFAULT_SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", 1200))
DEFAULT_FUNDING_THRESHOLD = float(os.getenv("FUNDING_THRESHOLD", -0.015))
TOPVOL_UNIVERSE_SIZE = 25
TOPVOL_MAX_WORKERS = 6


def _scan_interval_key(chat_id: int) -> str:
    return f"scan_interval_{chat_id}"


def _threshold_key(chat_id: int) -> str:
    return f"funding_threshold_{chat_id}"


def get_chat_threshold(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> float:
    return context.bot_data.get(_threshold_key(chat_id), DEFAULT_FUNDING_THRESHOLD)


def get_chat_interval(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> int:
    return context.bot_data.get(_scan_interval_key(chat_id), DEFAULT_SCAN_INTERVAL)


def format_percent(value: float, digits: int = 2) -> str:
    return f"{value * 100:.{digits}f}%"


def format_threshold(value: float) -> str:
    return f"{value * 100:.2f}%"


def classify_regime(stats: dict) -> str:
    atr_rel = stats.get("atr_relative", 0)
    vol_day = stats.get("vol_day", 0)
    score = max(atr_rel, vol_day)
    if score >= 0.12:
        return "extreme"
    if score >= 0.08:
        return "elevated"
    if score >= 0.04:
        return "normal"
    return "calm"


def analysis_error_message(symbol: str, error_code: str | None) -> str:
    if error_code == "not_found":
        return f"❌ `{symbol}` was not found on Bybit."
    if error_code == "timeout":
        return (
            f"⚠️ Bybit timed out while processing `{symbol}`. "
            "Try again in a moment."
        )
    if error_code == "network":
        return (
            f"⚠️ Network error while contacting Bybit for `{symbol}`. "
            "Try again in a moment."
        )
    if error_code == "empty_data":
        return f"⚠️ Bybit returned no candle data for `{symbol}`."
    if error_code == "insufficient_data":
        return f"⚠️ Not enough historical data to analyze `{symbol}`."
    return f"⚠️ Could not analyze `{symbol}` because the exchange API returned an unexpected error."


def parse_threshold_input(raw_value: str) -> float:
    value = raw_value.strip().replace("%", "").replace(",", ".")
    threshold = float(value)
    if threshold > 0:
        threshold = -threshold
    if abs(threshold) >= 1:
        threshold /= 100
    if threshold >= 0 or threshold <= -1:
        raise ValueError("Threshold must be a negative percentage.")
    return threshold


def build_general_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Funding", callback_data="funding"),
                InlineKeyboardButton("Top Vol", callback_data="topvol:daily"),
            ],
            [
                InlineKeyboardButton("Set Rate", callback_data="setrate"),
                InlineKeyboardButton("Frequency", callback_data="frequency"),
            ],
        ]
    )


def build_symbol_keyboard(symbol: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Refresh", callback_data=f"ticker:{symbol}"),
                InlineKeyboardButton("Risk", callback_data=f"risk:{symbol}"),
            ],
            [
                InlineKeyboardButton("Funding", callback_data="funding"),
                InlineKeyboardButton("Top Vol", callback_data="topvol:daily"),
            ],
            [
                InlineKeyboardButton("Set Rate", callback_data="setrate"),
                InlineKeyboardButton("Frequency", callback_data="frequency"),
            ],
        ]
    )


def build_analysis_report(payload: dict) -> str:
    stats = payload["stats"]
    symbol = payload["symbol"]
    category = payload["category"]
    candles = payload["candles"]
    regime = classify_regime(stats)

    return (
        f"📊 *{symbol}*  `{category}`\n"
        f"Regime: *{regime}*\n"
        f"History: {len(candles)} daily candles\n\n"
        f"*Volatility*\n"
        f"Day: {format_percent(stats['vol_day'])}\n"
        f"Week: {format_percent(stats['vol_week'])}\n"
        f"Max surge: {format_percent(stats['max_daily_surge'])}\n"
        f"Max crash: {format_percent(stats['max_daily_crash'])}\n\n"
        f"*Intraday extremes*\n"
        f"Biggest pump: {format_percent(stats['max_pump_val'])} on {stats['max_pump_date']}\n"
        f"Worst dump: {format_percent(stats['max_dump_val'])} on {stats['max_dump_date']}\n"
        f"Avg pump: {format_percent(stats['avg_pump'])}\n"
        f"Avg dump: {format_percent(stats['avg_dump'])}\n\n"
        f"*Risk frame*\n"
        f"ATR 14: `{stats['atr_14']:.6f}`\n"
        f"ATR 28: `{stats['atr_28']:.6f}`\n"
        f"ATR / close: {format_percent(stats['atr_relative'])}\n\n"
        f"*DCA ladder ideas*\n"
        f"75%: {format_percent(stats['p75_pump'])}\n"
        f"80%: {format_percent(stats['p80_pump'])}\n"
        f"85%: {format_percent(stats['p85_pump'])}\n"
        f"90%: {format_percent(stats['p90_pump'])}\n"
        f"95%: {format_percent(stats['p95_pump'])}\n"
        f"99%: {format_percent(stats['p99_pump'])}"
    )


def build_risk_report(payload: dict) -> str:
    stats = payload["stats"]
    symbol = payload["symbol"]
    last_close = stats["close"]
    atr_pct = stats["atr_relative"]

    stop_pct = max(abs(stats["max_dump_val"]) * 0.6, atr_pct * 1.5)
    stop_price = last_close * (1 - stop_pct)

    ladder_1 = stats["p75_pump"]
    ladder_2 = stats["p85_pump"]
    ladder_3 = stats["p95_pump"]

    return (
        f"🛡️ *Risk frame for {symbol}*\n\n"
        f"Last close: `{last_close:.6f}`\n"
        f"ATR / close: {format_percent(atr_pct)}\n"
        f"Worst historical dump: {format_percent(stats['max_dump_val'])}\n\n"
        f"*Short-side ladder heuristic*\n"
        f"Starter spacing: {format_percent(ladder_1)}\n"
        f"Add 2 spacing: {format_percent(ladder_2)}\n"
        f"Stress spacing: {format_percent(ladder_3)}\n\n"
        f"*Risk control heuristic*\n"
        f"Suggested emergency distance: {format_percent(stop_pct)}\n"
        f"Approx stop price from last close: `{stop_price:.6f}`\n\n"
        "These are statistical heuristics from historical candles, not trading advice."
    )


def build_compare_report(symbols: list[str]) -> str:
    results = []
    with ThreadPoolExecutor(max_workers=min(len(symbols), 4)) as executor:
        future_map = {executor.submit(analyze_symbol, symbol): symbol for symbol in symbols}
        for future in as_completed(future_map):
            results.append(future.result())

    result_map = {item["symbol"]: item for item in results}
    ordered = [result_map[normalize_symbol(symbol)] for symbol in symbols]

    lines = ["📚 *Symbol comparison*\n"]
    for item in ordered:
        if not item["ok"]:
            lines.append(f"- `{item['symbol']}`: {analysis_error_message(item['symbol'], item['error'])}")
            continue

        stats = item["stats"]
        lines.append(
            f"*{item['symbol']}* `{item['category']}` | "
            f"day vol {format_percent(stats['vol_day'])} | "
            f"week vol {format_percent(stats['vol_week'])} | "
            f"ATR {format_percent(stats['atr_relative'])} | "
            f"worst dump {format_percent(stats['max_dump_val'])}"
        )

    return "\n".join(lines)


def build_topvol_report(metric: str = "daily", limit: int = 10) -> str:
    symbols = get_top_liquid_symbols(limit=max(TOPVOL_UNIVERSE_SIZE, limit * 2))
    if not symbols:
        return "⚠️ Could not fetch liquid Bybit symbols for volatility ranking."

    analyzed = []
    with ThreadPoolExecutor(max_workers=min(TOPVOL_MAX_WORKERS, len(symbols))) as executor:
        future_map = {
            executor.submit(analyze_symbol, symbol, "linear"): symbol for symbol in symbols
        }
        for future in as_completed(future_map):
            result = future.result()
            if result["ok"]:
                analyzed.append(result)

    if not analyzed:
        return "⚠️ Unable to build the volatility ranking because market data requests failed."

    metric_key = "vol_week" if metric == "weekly" else "vol_day"
    metric_label = "weekly" if metric == "weekly" else "daily"
    ranked = sorted(
        analyzed,
        key=lambda item: item["stats"][metric_key],
        reverse=True,
    )[:limit]

    lines = [f"🔥 *Top {len(ranked)} {metric_label} volatility names*\n"]
    for index, item in enumerate(ranked, 1):
        stats = item["stats"]
        lines.append(
            f"{index}. `{item['symbol']}` "
            f"| {metric_label} vol {format_percent(stats[metric_key])} "
            f"| ATR {format_percent(stats['atr_relative'])} "
            f"| regime {classify_regime(stats)}"
        )

    lines.append(
        "\nUniverse: most liquid Bybit linear symbols by 24h turnover."
    )
    return "\n".join(lines)


async def run_blocking(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func, *args)


async def send_analysis_message(
    message_target,
    symbol: str,
    status_prefix: str = "🔍 Checking",
):
    global REQUEST_COUNT
    REQUEST_COUNT += 1

    normalized = normalize_symbol(symbol)
    status_msg = await message_target.reply_text(f"{status_prefix} `{normalized}`...", parse_mode="Markdown")
    payload = await run_blocking(analyze_symbol, normalized)

    if not payload["ok"]:
        await status_msg.edit_text(
            analysis_error_message(normalized, payload["error"]),
            parse_mode="Markdown",
        )
        return

    report = build_analysis_report(payload)
    await status_msg.edit_text(
        report,
        parse_mode="Markdown",
        reply_markup=build_symbol_keyboard(payload["symbol"]),
    )

    print(f"[Result] Request #{REQUEST_COUNT}: Sent report for {payload['symbol']}.")


async def send_risk_message(message_target, symbol: str):
    normalized = normalize_symbol(symbol)
    status_msg = await message_target.reply_text(f"🛡️ Building risk frame for `{normalized}`...", parse_mode="Markdown")
    payload = await run_blocking(analyze_symbol, normalized)

    if not payload["ok"]:
        await status_msg.edit_text(
            analysis_error_message(normalized, payload["error"]),
            parse_mode="Markdown",
        )
        return

    await status_msg.edit_text(
        build_risk_report(payload),
        parse_mode="Markdown",
        reply_markup=build_symbol_keyboard(payload["symbol"]),
    )


async def send_funding_message(message_target, limit: int = 10):
    status_msg = await message_target.reply_text("🔍 Fetching funding rates...")
    report = await run_blocking(get_top_funding_rates, limit)
    await status_msg.edit_text(
        report,
        parse_mode="Markdown",
        link_preview_options=LinkPreviewOptions(is_disabled=True),
        reply_markup=build_general_keyboard(),
    )


def start_scanning_job(context, chat_id, interval_seconds: int | None = None):
    if interval_seconds is None:
        interval_seconds = get_chat_interval(context, chat_id)

    if not context.job_queue:
        print("[System] Warning: JobQueue not available. Background scanning disabled.")
        return

    current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    if current_jobs and interval_seconds == get_chat_interval(context, chat_id):
        return

    for job in current_jobs:
        job.schedule_removal()

    context.job_queue.run_repeating(
        scan_funding_job,
        interval=interval_seconds,
        first=10,
        chat_id=chat_id,
        name=str(chat_id),
    )
    context.bot_data[_scan_interval_key(chat_id)] = interval_seconds
    print(f"[System] Background funding scan for chat {chat_id} set to every {interval_seconds}s.")


async def scan_funding_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    if not job or not job.chat_id:
        return

    threshold = get_chat_threshold(context, job.chat_id)
    report = await run_blocking(check_extreme_funding, threshold)
    if not report:
        return

    await context.bot.send_message(
        job.chat_id,
        text=report,
        parse_mode="Markdown",
        link_preview_options=LinkPreviewOptions(is_disabled=True),
        reply_markup=build_general_keyboard(),
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    start_scanning_job(context, chat_id)
    threshold = get_chat_threshold(context, chat_id)
    interval_minutes = get_chat_interval(context, chat_id) // 60

    await update.message.reply_text(
        "👋 *Volatility Bot is ready*\n\n"
        "Use `/ticker BTC` for analysis.\n"
        "Use `/compare BTC ETH SOL` to compare names.\n"
        "Use `/funding` for negative funding, `/topvol` for rankers, and `/risk BTC` for ladder heuristics.\n\n"
        f"Current funding alert threshold: `{format_threshold(threshold)}`\n"
        f"Current scan frequency: `{interval_minutes}` minute(s)",
        parse_mode="Markdown",
        reply_markup=build_general_keyboard(),
    )


async def funding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    limit = 10
    if context.args:
        try:
            limit = max(1, min(20, int(context.args[0])))
        except ValueError:
            await update.message.reply_text("⚠️ Usage: `/funding` or `/funding 15`", parse_mode="Markdown")
            return

    await send_funding_message(update.message, limit)


async def frequency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if not context.args:
        minutes = get_chat_interval(context, chat_id) // 60
        await update.message.reply_text(
            f"Current scan frequency: `{minutes}` minute(s)\nUse `/frequency 30` to change it.",
            parse_mode="Markdown",
        )
        return

    try:
        minutes = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "⚠️ Usage: `/frequency <minutes>`\nExample: `/frequency 30`",
            parse_mode="Markdown",
        )
        return

    if minutes < 1:
        await update.message.reply_text("⚠️ Interval must be at least 1 minute.")
        return

    interval_seconds = minutes * 60
    start_scanning_job(context, chat_id, interval_seconds=interval_seconds)
    await update.message.reply_text(
        f"✅ Background scan interval updated to every `{minutes}` minute(s).",
        parse_mode="Markdown",
    )


async def rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        threshold = get_chat_threshold(context, chat_id)
        await update.message.reply_text(
            f"Current funding alert threshold: `{format_threshold(threshold)}`\n"
            "Use `/rate -1.8` to alert at or below -1.80% funding.",
            parse_mode="Markdown",
        )
        return

    try:
        threshold = parse_threshold_input(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "⚠️ Usage: `/rate -1.8` or `/rate -0.018`\n"
            "Value must be negative and represent a percent threshold.",
            parse_mode="Markdown",
        )
        return

    context.bot_data[_threshold_key(chat_id)] = threshold
    await update.message.reply_text(
        f"✅ Funding alert threshold updated to `{format_threshold(threshold)}`.",
        parse_mode="Markdown",
    )


async def ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "⚠️ Usage: `/ticker BTC` or `/ticker BTCUSDT`",
            parse_mode="Markdown",
        )
        return

    chat_id = update.effective_chat.id
    start_scanning_job(context, chat_id)
    await send_analysis_message(update.message, context.args[0])


async def compare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Usage: `/compare BTC ETH SOL`\nCompare at least two symbols.",
            parse_mode="Markdown",
        )
        return

    symbols = [normalize_symbol(arg) for arg in context.args[:5]]
    status_msg = await update.message.reply_text("📚 Building comparison...")
    report = await run_blocking(build_compare_report, symbols)
    await status_msg.edit_text(
        report,
        parse_mode="Markdown",
        reply_markup=build_general_keyboard(),
    )


async def topvol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    metric = "daily"
    limit = 10

    if context.args:
        first = context.args[0].lower()
        if first in {"daily", "weekly"}:
            metric = first
            if len(context.args) > 1:
                try:
                    limit = max(3, min(15, int(context.args[1])))
                except ValueError:
                    await update.message.reply_text(
                        "⚠️ Usage: `/topvol`, `/topvol weekly`, or `/topvol weekly 8`",
                        parse_mode="Markdown",
                    )
                    return
        else:
            try:
                limit = max(3, min(15, int(context.args[0])))
            except ValueError:
                await update.message.reply_text(
                    "⚠️ Usage: `/topvol`, `/topvol weekly`, or `/topvol weekly 8`",
                    parse_mode="Markdown",
                )
                return

    status_msg = await update.message.reply_text("🔥 Ranking volatility leaders...")
    report = await run_blocking(build_topvol_report, metric, limit)
    await status_msg.edit_text(
        report,
        parse_mode="Markdown",
        reply_markup=build_general_keyboard(),
    )


async def risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "⚠️ Usage: `/risk BTC` or `/risk BTCUSDT`",
            parse_mode="Markdown",
        )
        return

    await send_risk_message(update.message, context.args[0])


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Volatility Bot commands*\n\n"
        "/start - start the bot for this chat and enable background funding scans\n"
        "/ticker <symbol> - full volatility report for one symbol\n"
        "/compare <symbol1> <symbol2> ... - compare up to 5 symbols\n"
        "/funding [limit] - most negative funding rates right now\n"
        "/rate <negative percent> - set alert threshold, example `/rate -1.8`\n"
        "/frequency <minutes> - set background scan interval\n"
        "/topvol [daily|weekly] [limit] - rank the most volatile liquid linear names\n"
        "/risk <symbol> - ATR and ladder-based risk frame\n"
        "/help - show this help message\n\n"
        "Plain text messages no longer trigger analysis. Use `/ticker BTC` instead.",
        parse_mode="Markdown",
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data == "funding":
        await send_funding_message(query.message)
        return

    if data == "setrate":
        chat_id = query.message.chat.id
        threshold = get_chat_threshold(context, chat_id)
        await query.message.reply_text(
            f"Current threshold: `{format_threshold(threshold)}`\nUse `/rate -1.8` to change it.",
            parse_mode="Markdown",
        )
        return

    if data == "frequency":
        chat_id = query.message.chat.id
        minutes = get_chat_interval(context, chat_id) // 60
        await query.message.reply_text(
            f"Current scan frequency: `{minutes}` minute(s)\nUse `/frequency 30` to change it.",
            parse_mode="Markdown",
        )
        return

    if data.startswith("ticker:"):
        symbol = data.split(":", 1)[1]
        await send_analysis_message(query.message, symbol, status_prefix="🔄 Refreshing")
        return

    if data.startswith("risk:"):
        symbol = data.split(":", 1)[1]
        await send_risk_message(query.message, symbol)
        return

    if data.startswith("topvol:"):
        metric = data.split(":", 1)[1]
        status_msg = await query.message.reply_text("🔥 Ranking volatility leaders...")
        report = await run_blocking(build_topvol_report, metric, 10)
        await status_msg.edit_text(
            report,
            parse_mode="Markdown",
            reply_markup=build_general_keyboard(),
        )
        return


async def text_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Use commands only. Example: `/ticker BTC`, `/compare BTC ETH`, `/topvol`, `/risk BTC`.",
        parse_mode="Markdown",
    )


if __name__ == "__main__":
    token = os.getenv("TELEGRAM_TOKEN_PROD")
    if not token:
        print("Error: TELEGRAM_TOKEN_PROD not found in .env file.")
        raise SystemExit(1)

    application = ApplicationBuilder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ticker", ticker))
    application.add_handler(CommandHandler("compare", compare))
    application.add_handler(CommandHandler("funding", funding))
    application.add_handler(CommandHandler("rate", rate))
    application.add_handler(CommandHandler("frequency", frequency))
    application.add_handler(CommandHandler("topvol", topvol))
    application.add_handler(CommandHandler("risk", risk))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_fallback))
    application.run_polling()
