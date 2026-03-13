import requests
from pprint import pprint

# Constants
BYBIT_TICKERS_URL = "https://api.bybit.com/v5/market/tickers"
OKX_FUNDING_URL = "https://www.okx.com/api/v5/public/funding-rate"


def get_funding_data(category="linear"):
    """
    Fetches market data including funding rates for all tickers in the specified category.
    """
    try:
        params = {"category": category, "limit": 1000}

        response = requests.get(BYBIT_TICKERS_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data["retCode"] != 0:
            print(f"[Funding] API Error: {data['retMsg']}")
            return []

        return data.get("result", {}).get("list", [])

    except Exception as e:
        print(f"[Funding] Error fetching data: {e}")
        return []


def bybit_to_okx_inst_id(bybit_symbol: str) -> str:
    """
    Converts a Bybit linear symbol to an OKX instId.
    Example: 'KAVAUSDT' -> 'KAVA-USDT-SWAP'
    Handles both *USDT and *USDC suffixes.
    """
    for quote in ("USDC", "USDT"):
        if bybit_symbol.endswith(quote):
            base = bybit_symbol[: -len(quote)]
            return f"{base}-{quote}-SWAP"
    # Fallback: treat the whole thing as base quoted in USDT
    return f"{bybit_symbol}-USDT-SWAP"


def get_okx_funding_rate(bybit_symbol: str) -> float | None:
    """
    Returns the current funding rate for the equivalent OKX linear perpetual,
    or None if the instrument does not exist on OKX or the request fails.
    """
    inst_id = bybit_to_okx_inst_id(bybit_symbol)
    try:
        response = requests.get(OKX_FUNDING_URL, params={"instId": inst_id}, timeout=8)
        response.raise_for_status()
        data = response.json()

        if data.get("code") != "0" or not data.get("data"):
            return None

        rate_str = data["data"][0].get("fundingRate", "")
        return float(rate_str) if rate_str else None

    except Exception as e:
        print(f"[OKX] Error fetching funding rate for {inst_id}: {e}")
        return None


def _format_okx_bracket(okx_rate: float | None) -> str:
    """Returns '(X.XX%)' if rate is available, otherwise '(x)'."""
    if okx_rate is None:
        return "(x)"
    return f"({okx_rate * 100:.4f}%)"


def get_top_funding_rates(limit=10):
    """
    Returns a formatted string of the top 'limit' coins with the lowest
    (most negative) funding rates on Bybit, alongside OKX cross-reference.
    """
    tickers = get_funding_data()
    if not tickers:
        return "⚠️ Error: Could not fetch funding data."

    # Filter for negative funding rates
    valid_tickers = []
    for t in tickers:
        fr_str = t.get("fundingRate", "")
        if fr_str:
            try:
                fr = float(fr_str)
                if fr < 0:
                    valid_tickers.append((t["symbol"], fr))
            except ValueError:
                continue

    # Sort ascending (most negative first)
    valid_tickers.sort(key=lambda x: x[1])
    top_tickers = valid_tickers[:limit]

    if not top_tickers:
        return "ℹ️ No coins with negative funding rates found."

    report = "🚩 *Top 10 negative funding*\n\n"
    for i, (symbol, rate) in enumerate(top_tickers, 1):
        okx_rate = get_okx_funding_rate(symbol)
        okx_part = _format_okx_bracket(okx_rate)
        report += (
            f"{i}. [{symbol}](https://www.bybit.com/trade/usdt/{symbol}): "
            f"{rate * 100:.4f}% {okx_part}\n"
        )

    return report


def check_extreme_funding(threshold=-0.015):
    """
    Scans for coins with funding rates <= threshold (default -1.5%).
    Returns a formatted warning message if any found, else None.
    Includes OKX cross-reference in brackets for each coin.
    """
    tickers = get_funding_data()
    if not tickers:
        return None

    extreme_tickers = []
    for t in tickers:
        fr_str = t.get("fundingRate", "")
        if fr_str:
            try:
                fr = float(fr_str)
                if fr <= threshold:
                    extreme_tickers.append((t["symbol"], fr))
            except ValueError:
                continue

    if not extreme_tickers:
        return None

    # Sort by funding rate (most extreme first)
    extreme_tickers.sort(key=lambda x: x[1])

    report = "🚨 *EXTREME FUNDING ALERT* 🚨\n\n"
    for symbol, rate in extreme_tickers:
        okx_rate = get_okx_funding_rate(symbol)
        okx_part = _format_okx_bracket(okx_rate)
        report += (
            f"[{symbol}](https://www.bybit.com/trade/usdt/{symbol}): "
            f"{rate * 100:.4f}% {okx_part}\n"
        )

    return report
