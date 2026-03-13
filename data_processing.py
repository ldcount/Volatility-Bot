import math
import statistics
import time
from datetime import datetime

import requests
from pybit.unified_trading import HTTP

BYBIT_INSTRUMENTS_URL = "https://api.bybit.com/v5/market/instruments-info"
BYBIT_TICKERS_URL = "https://api.bybit.com/v5/market/tickers"
INSTRUMENTS_CACHE_TTL = 300

_INSTRUMENT_CACHE: dict[str, tuple[float, dict[str, dict]]] = {}


def normalize_symbol(raw_symbol: str) -> str:
    symbol = raw_symbol.strip().upper()
    if not symbol:
        return symbol
    if symbol.endswith(("USDT", "USDC", "USD")):
        return symbol
    return f"{symbol}USDT"


def _get_cached_instruments(category: str) -> dict[str, dict]:
    now = time.time()
    cached = _INSTRUMENT_CACHE.get(category)
    if cached and now - cached[0] < INSTRUMENTS_CACHE_TTL:
        return cached[1]

    instruments_map: dict[str, dict] = {}
    cursor = ""

    while True:
        params = {"category": category, "limit": 1000}
        if cursor:
            params["cursor"] = cursor

        response = requests.get(BYBIT_INSTRUMENTS_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("retCode") != 0:
            raise RuntimeError(data.get("retMsg", "Unknown Bybit instruments error"))

        instruments = data.get("result", {}).get("list", [])
        for item in instruments:
            symbol = item.get("symbol")
            if symbol:
                instruments_map[symbol] = item

        cursor = data.get("result", {}).get("nextPageCursor", "")
        if not cursor:
            break

    _INSTRUMENT_CACHE[category] = (now, instruments_map)
    return instruments_map


def validate_ticker(ticker_symbol: str):
    """
    Returns:
      (True, category, None) when symbol exists
      (False, None, error_code) on failure where error_code is one of:
        not_found, timeout, network, api_error
    """
    search_order = ["linear", "inverse", "spot"]
    last_error = None

    for category in search_order:
        try:
            instruments = _get_cached_instruments(category)
            if ticker_symbol in instruments:
                return True, category, None
        except requests.Timeout:
            last_error = "timeout"
        except requests.RequestException:
            last_error = "network"
        except Exception as exc:
            print(f"[Gatekeeper] Error checking category '{category}': {exc}")
            last_error = "api_error"

    if last_error:
        return False, None, last_error

    print(f"[Gatekeeper] Error: Symbol {ticker_symbol} not found on Bybit.")
    return False, None, "not_found"


def fetch_market_data(ticker_symbol, category, interval="D"):
    """
    Returns:
      (candles, None) on success
      (None, error_code) where error_code is one of:
        timeout, network, api_error, empty_data
    """
    print(f"\n[Harvester] Fetching data for {ticker_symbol} ({category})...")
    session = HTTP(testnet=False)

    try:
        response = session.get_kline(
            category=category,
            symbol=ticker_symbol,
            interval=interval,
            limit=1000,
        )
    except requests.Timeout:
        return None, "timeout"
    except requests.RequestException:
        return None, "network"
    except Exception as exc:
        print(f"[Harvester] Transport error: {exc}")
        return None, "api_error"

    try:
        if response.get("retCode") != 0:
            print(f"[Harvester] API returned error: {response.get('retMsg')}")
            return None, "api_error"

        raw_candles = response.get("result", {}).get("list", [])
        if not raw_candles:
            print("[Harvester] Error: API returned no candles.")
            return None, "empty_data"

        raw_candles.reverse()
        cleaned_candles = []

        for candle in raw_candles:
            ts = int(candle[0]) / 1000
            date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            cleaned_candles.append([date_str] + candle[1:])

        print(f"[Harvester] Success! Processed {len(cleaned_candles)} candles in-memory.")
        return cleaned_candles, None
    except Exception as exc:
        print(f"[Harvester] Processing error: {exc}")
        return None, "api_error"


def analyze_market_data(candles):
    if not candles or len(candles) < 2:
        print("[Brain] Error: Need at least 2 candles to analyze.")
        return None

    pump_data = []
    dump_data = []
    log_returns = []
    tr_list = []

    for i, candle in enumerate(candles):
        date_str = candle[0]
        curr_open = float(candle[1])
        curr_high = float(candle[2])
        curr_low = float(candle[3])
        curr_close = float(candle[4])

        if curr_open > 0:
            pump = (curr_high - curr_open) / curr_open
            pump_data.append((pump, date_str))

            dump = (curr_low - curr_open) / curr_open
            dump_data.append((dump, date_str))

        if i > 0:
            prev_close = float(candles[i - 1][4])
            if prev_close > 0 and curr_close > 0:
                log_ret = math.log(curr_close / prev_close)
                log_returns.append(log_ret)

            raw_hl = curr_high - curr_low
            raw_h_pc = abs(curr_high - prev_close)
            raw_l_pc = abs(curr_low - prev_close)
            tr_list.append(max(raw_hl, raw_h_pc, raw_l_pc))

    stats = {}

    if len(log_returns) > 1:
        stdev_log = statistics.stdev(log_returns)
        stats["vol_day"] = stdev_log
        stats["vol_week"] = stdev_log * (7**0.5)
    else:
        stats["vol_day"] = 0.0
        stats["vol_week"] = 0.0

    max_log = max(log_returns) if log_returns else 0
    min_log = min(log_returns) if log_returns else 0
    stats["max_daily_surge"] = math.exp(max_log) - 1
    stats["max_daily_crash"] = math.exp(min_log) - 1

    if pump_data:
        stats["max_pump_val"], stats["max_pump_date"] = max(pump_data, key=lambda x: x[0])
        pump_values = [x[0] for x in pump_data]
        stats["avg_pump"] = statistics.mean(pump_values)
        stats["std_pump"] = statistics.stdev(pump_values) if len(pump_values) > 1 else 0
    else:
        stats["max_pump_val"], stats["max_pump_date"] = (0, "N/A")
        stats["avg_pump"] = 0
        stats["std_pump"] = 0

    if dump_data:
        stats["max_dump_val"], stats["max_dump_date"] = min(dump_data, key=lambda x: x[0])
        dump_values = [x[0] for x in dump_data]
        stats["avg_dump"] = statistics.mean(dump_values)
        stats["std_dump"] = statistics.stdev(dump_values) if len(dump_values) > 1 else 0
    else:
        stats["max_dump_val"], stats["max_dump_date"] = (0, "N/A")
        stats["avg_dump"] = 0
        stats["std_dump"] = 0

    current_close = float(candles[-1][4])
    stats["close"] = current_close

    if len(tr_list) >= 14:
        stats["atr_14"] = statistics.mean(tr_list[-14:])
    else:
        stats["atr_14"] = 0

    if len(tr_list) >= 28:
        atr_28 = statistics.mean(tr_list[-28:])
        stats["atr_28"] = atr_28
        stats["atr_relative"] = atr_28 / current_close if current_close > 0 else 0
    else:
        stats["atr_28"] = 0
        stats["atr_relative"] = 0

    if pump_data:
        pump_values_sorted = sorted([p[0] for p in pump_data])
        n = len(pump_values_sorted)

        def get_p(percent):
            index = min(max(int(n * percent), 0), n - 1)
            return pump_values_sorted[index]

        stats["p75_pump"] = get_p(0.75)
        stats["p80_pump"] = get_p(0.80)
        stats["p85_pump"] = get_p(0.85)
        stats["p90_pump"] = get_p(0.90)
        stats["p95_pump"] = get_p(0.95)
        stats["p99_pump"] = get_p(0.99)
    else:
        for key in ["p75_pump", "p80_pump", "p85_pump", "p90_pump", "p95_pump", "p99_pump"]:
            stats[key] = 0.0

    return stats


def analyze_symbol(symbol: str, category: str | None = None):
    normalized = normalize_symbol(symbol)

    if category is None:
        exists, category, validation_error = validate_ticker(normalized)
        if not exists:
            return {
                "ok": False,
                "symbol": normalized,
                "error": validation_error,
            }
    else:
        validation_error = None

    candles, fetch_error = fetch_market_data(normalized, category, "D")
    if not candles:
        return {
            "ok": False,
            "symbol": normalized,
            "category": category,
            "error": fetch_error,
        }

    stats = analyze_market_data(candles)
    if not stats:
        return {
            "ok": False,
            "symbol": normalized,
            "category": category,
            "error": "insufficient_data",
        }

    return {
        "ok": True,
        "symbol": normalized,
        "category": category,
        "candles": candles,
        "stats": stats,
        "validation_error": validation_error,
    }


def get_linear_tickers():
    try:
        response = requests.get(
            BYBIT_TICKERS_URL,
            params={"category": "linear", "limit": 1000},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        if data.get("retCode") != 0:
            raise RuntimeError(data.get("retMsg", "Unknown Bybit tickers error"))

        return data.get("result", {}).get("list", [])
    except Exception as exc:
        print(f"[Tickers] Error fetching linear tickers: {exc}")
        return []


def get_top_liquid_symbols(limit=25):
    tickers = get_linear_tickers()
    if not tickers:
        return []

    ranked = sorted(
        tickers,
        key=lambda item: float(item.get("turnover24h") or 0),
        reverse=True,
    )

    symbols = []
    for item in ranked:
        symbol = item.get("symbol")
        if not symbol:
            continue
        if not symbol.endswith(("USDT", "USDC")):
            continue
        symbols.append(symbol)
        if len(symbols) >= limit:
            break

    return symbols
