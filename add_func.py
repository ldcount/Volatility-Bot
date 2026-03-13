from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

BYBIT_TICKERS_URL = "https://api.bybit.com/v5/market/tickers"
OKX_FUNDING_URL = "https://www.okx.com/api/v5/public/funding-rate"

OKX_MAX_WORKERS = 8


def get_funding_data(category="linear"):
    try:
        params = {"category": category, "limit": 1000}
        response = requests.get(BYBIT_TICKERS_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("retCode") != 0:
            print(f"[Funding] API Error: {data.get('retMsg')}")
            return []

        return data.get("result", {}).get("list", [])
    except Exception as exc:
        print(f"[Funding] Error fetching data: {exc}")
        return []


def bybit_to_okx_inst_id(bybit_symbol: str) -> str:
    for quote in ("USDC", "USDT"):
        if bybit_symbol.endswith(quote):
            base = bybit_symbol[: -len(quote)]
            return f"{base}-{quote}-SWAP"
    return f"{bybit_symbol}-USDT-SWAP"


def get_okx_funding_rate(bybit_symbol: str) -> float | None:
    inst_id = bybit_to_okx_inst_id(bybit_symbol)
    try:
        response = requests.get(OKX_FUNDING_URL, params={"instId": inst_id}, timeout=8)
        response.raise_for_status()
        data = response.json()

        if data.get("code") != "0" or not data.get("data"):
            return None

        rate_str = data["data"][0].get("fundingRate", "")
        return float(rate_str) if rate_str else None
    except Exception as exc:
        print(f"[OKX] Error fetching funding rate for {inst_id}: {exc}")
        return None


def get_okx_funding_rates(symbols: list[str]) -> dict[str, float | None]:
    results: dict[str, float | None] = {}
    if not symbols:
        return results

    with ThreadPoolExecutor(max_workers=min(OKX_MAX_WORKERS, len(symbols))) as executor:
        future_map = {
            executor.submit(get_okx_funding_rate, symbol): symbol for symbol in symbols
        }
        for future in as_completed(future_map):
            symbol = future_map[future]
            try:
                results[symbol] = future.result()
            except Exception as exc:
                print(f"[OKX] Unexpected error for {symbol}: {exc}")
                results[symbol] = None

    return results


def _format_okx_bracket(okx_rate: float | None) -> str:
    if okx_rate is None:
        return "(OKX n/a)"
    return f"(OKX {okx_rate * 100:.4f}%)"


def _format_bybit_symbol(symbol: str) -> str:
    if symbol.endswith(("USDT", "USDC")):
        return f"[{symbol}](https://www.bybit.com/trade/usdt/{symbol})"
    return f"`{symbol}`"


def _build_funding_lines(entries: list[tuple[str, float]]):
    okx_lookup = get_okx_funding_rates([symbol for symbol, _ in entries])
    lines = []
    for index, (symbol, rate) in enumerate(entries, 1):
        okx_part = _format_okx_bracket(okx_lookup.get(symbol))
        lines.append(
            f"{index}. {_format_bybit_symbol(symbol)}: "
            f"{rate * 100:.4f}% {okx_part}"
        )
    return lines


def get_top_funding_rates(limit=10):
    tickers = get_funding_data()
    if not tickers:
        return "⚠️ Error: Could not fetch funding data from Bybit."

    valid_tickers = []
    for ticker in tickers:
        fr_str = ticker.get("fundingRate", "")
        if not fr_str:
            continue
        try:
            funding_rate = float(fr_str)
        except ValueError:
            continue
        if funding_rate < 0:
            valid_tickers.append((ticker["symbol"], funding_rate))

    valid_tickers.sort(key=lambda item: item[1])
    top_tickers = valid_tickers[:limit]

    if not top_tickers:
        return "ℹ️ No coins with negative funding rates found."

    lines = _build_funding_lines(top_tickers)
    return "🚩 *Top negative funding*\n\n" + "\n".join(lines)


def check_extreme_funding(threshold=-0.015):
    tickers = get_funding_data()
    if not tickers:
        return None

    extreme_tickers = []
    for ticker in tickers:
        fr_str = ticker.get("fundingRate", "")
        if not fr_str:
            continue
        try:
            funding_rate = float(fr_str)
        except ValueError:
            continue
        if funding_rate <= threshold:
            extreme_tickers.append((ticker["symbol"], funding_rate))

    if not extreme_tickers:
        return None

    extreme_tickers.sort(key=lambda item: item[1])
    lines = _build_funding_lines(extreme_tickers)
    header = f"🚨 *EXTREME FUNDING ALERT* 🚨\nThreshold: {threshold * 100:.2f}%\n\n"
    return header + "\n".join(lines)
