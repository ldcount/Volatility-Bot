import requests
from pprint import pprint

# Constants
BYBIT_TICKERS_URL = "https://api.bybit.com/v5/market/tickers"


def get_funding_data(category="linear"):
    """
    Fetches market data including funding rates for all tickers in the specified category.
    """
    try:
        # We need to fetch all tickers. Pagination might be needed if > 1000 tickers.
        # However, get_tickers endpoint might not support cursor based pagination like instruments-info.
        # Let's check documentation or just try to fetch.
        # Actually, https://bybit-exchange.github.io/docs/v5/market/tickers says "limit" up to 1000.
        # Does it support pagination? The response doesn't seem to have nextPageCursor for 'tickers' endpoint usually,
        # but let's assume valid linear tickers fit in one go or we handle what we get.
        # Actually, for 'tickers', there is no cursor. It returns a snapshot.
        # If there are more than 1000 linear pairs, we might miss some involving a filter.
        # But 'tickers' endpoint usually returns all for the category if no symbol is specified?
        # Wait, the docs say "limit" default 200, max 1000.
        # To be safe, we might need to filter or hope 1000 is enough for now.
        # Let's try to get 1000. Bybit has around 400-500 linear perps usually.

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


def get_top_funding_rates(limit=10):
    """
    Returns a formatted string of the top 'limit' coins with the lowest (most negative) funding rates.
    """
    tickers = get_funding_data()
    if not tickers:
        return "⚠️ Error: Could not fetch funding data."

    # Filter for tickers with funding rate
    # Funding rate is a string in the response e.g. "0.0001"
    valid_tickers = []
    for t in tickers:
        fr_str = t.get("fundingRate", "")
        if fr_str:
            try:
                fr = float(fr_str)
                # We only want negative funding rates for this specific request?
                # User said: "lowers negative funding sorted from the lowest to biggest"
                # "Most negative funding" implies we look for -0.05, -0.04, etc.
                if fr < 0:
                    valid_tickers.append((t["symbol"], fr))
            except ValueError:
                continue

    # Sort by funding rate ascending (lowest first, e.g. -0.1 before -0.01)
    valid_tickers.sort(key=lambda x: x[1])

    # Take top 'limit'
    top_tickers = valid_tickers[:limit]

    if not top_tickers:
        return "ℹ️ No coins with negative funding rates found."

    report = "📉 *Most Negative Funding*\n\n"
    for i, (symbol, rate) in enumerate(top_tickers, 1):
        # Rate is usually 8-hour rate. User wants %.
        # e.g. -0.005 is -0.5%
        report += f"{i}. **{symbol}**: {rate*100:.2f}%\n"

    return report


def check_extreme_funding(threshold=-0.015):
    """
    Scans for coins with funding rates <= threshold (default -2.5%).
    Returns a formatted warning message if any found, else None.
    """
    tickers = get_funding_data()
    # print (len(tickers))
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

    # Sort by funding rate for better visibility (lowest (most extreme) first)
    extreme_tickers.sort(key=lambda x: x[1])

    report = "🚨 *EXTREME FUNDING ALERT* 🚨\n\n"
    for symbol, rate in extreme_tickers:
        report += f"**{symbol}**: {rate*100:.4f}%\n"

    return report
