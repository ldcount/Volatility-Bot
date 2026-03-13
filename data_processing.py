import requests
import statistics
import math 
from datetime import datetime
from pybit.unified_trading import HTTP
from pprint import pprint

# ==========================================
# BLOCK 1: THE GATEKEEPER
# ==========================================

def validate_ticker(ticker_symbol):
    """
    Verifies if a symbol exists on Bybit across Linear, Inverse, or Spot markets.
    
    Args:
        ticker_symbol (str): The full symbol name (e.g., 'BTCUSDT').
        
    Returns:
        tuple: (exists (bool), category (str))
        Example: (True, 'linear') or (False, None)
    """
    #print(f"[Gatekeeper] Validating symbol: {ticker_symbol}...")
    
    # We check these categories in order of preference for a bot
    # 'linear' (USDT Perpetuals) is usually what traders want.
    search_order = ["linear", "inverse", "spot"]

    for category in search_order:
        try:
            # PAGINATION LOOP:
            # Bybit limits results to 1000 per page. We must loop to see everything.
            cursor = ""
            while True:
                params = {
                    "category": category,
                    "limit": 1000, 
                }
                if cursor:
                    params["cursor"] = cursor

                # We use raw requests here for precise control over the pagination loop
                response = requests.get(
                    "https://api.bybit.com/v5/market/instruments-info", 
                    params=params,
                    timeout=10 # Good practice: always set a timeout
                )
                response.raise_for_status() # Crashes if API sends 404 or 500 error
                data = response.json()
                
                # 1. Extract the list of coins from this page
                instruments = data.get("result", {}).get("list", [])
                
                # 2. Check if our ticker is in this list
                # Optimization: We check 'symbol' directly.
                for item in instruments:
                    if item.get("symbol") == ticker_symbol:
                        #print(f"[Gatekeeper] Success! Found {ticker_symbol} in '{category}'.")
                        return True, category
                
                # 3. Check for the next page
                cursor = data.get("result", {}).get("nextPageCursor", "")
                if not cursor:
                    break # No more pages in this category, move to the next category
                    
        except Exception as e:
            print(f"[Gatekeeper] Error checking category '{category}': {e}")
            continue # Try the next category even if one fails
            
    # If we finish all loops and find nothing:
    print(f"[Gatekeeper] Error: Symbol {ticker_symbol} not found on Bybit.")
    return False, None

# ==========================================
# BLOCK 2: THE HARVESTER (In-Memory Version)
# ==========================================

def fetch_market_data(ticker_symbol, category, interval="D"):
    """
    Fetches historical candle data from Bybit and processes it in-memory.
    DOES NOT SAVE TO CSV (Faster & Safer for Bots).
    
    Args:
        ticker_symbol (str): e.g., 'BTCUSDT'
        category (str): e.g., 'linear'
        interval (str): 'D' for daily.
        
    Returns:
        list: The list of cleaned candle data if successful, else None.
    """
    print(f"\n[Harvester] Fetching data for {ticker_symbol} ({category})...")
    
    # Initialize Pybit session
    session = HTTP(testnet=False)
    
    try:
        # 1. Fetch from API
        response = session.get_kline(
            category=category,
            symbol=ticker_symbol,
            interval=interval,
            limit=1000
        )
        
        # 2. Extract and Reverse
        raw_candles = response.get("result", {}).get("list", [])
        if not raw_candles:
            print("[Harvester] Error: API returned no candles.")
            return None
            
        raw_candles.reverse()
        
        # 3. Process Data (Convert Timestamps)
        # We do this in-memory instead of writing to a file
        cleaned_candles = []
        for candle in raw_candles:
            # Candle format: [startTime, open, high, low, close, volume, turnover]
            
            # Convert Timestamp to Date String
            ts = int(candle[0]) / 1000
            date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            
            # Update the candle's date field
            candle[0] = date_str
            cleaned_candles.append(candle)
                
        print(f"[Harvester] Successfully loaded {len(cleaned_candles)} candles into RAM.")
        return cleaned_candles

    except Exception as e:
        print(f"[Harvester] Critical Error: {e}")
        return None

# ==========================================
# BLOCK 3: THE BRAIN (Logic & Math)
# ==========================================

def analyze_market_data(candles):
    """
    Performs quantitative analysis on candle data.
    Now includes Log Returns, ATR, and detailed Percentiles.
    """
    # 1. Safety Checks
    if not candles or len(candles) < 30: # Need at least 28 days for ATR
        print("[Brain] Error: Not enough data (need > 30 candles).")
        return None

    # 2. Initialize Containers
    # Intraday tracking
    pump_data = []      # List of tuples: (value, date_str)
    dump_data = []      # List of tuples: (value, date_str)
    
    # Interday tracking
    log_returns = []    # ln(Close / PrevClose)
    tr_list = []        # True Range values

    # 3. The Grand Loop (O(N))
    for i, candle in enumerate(candles):
        # Candle: [date, open, high, low, close, vol, turnover]
        date_str = candle[0]
        curr_open = float(candle[1])
        curr_high = float(candle[2])
        curr_low = float(candle[3])
        curr_close = float(candle[4])

        # --- A. Intraday Pumps & Dumps (Open vs High/Low) ---
        if curr_open > 0:
            # Pump: How much did it fly?
            pump = (curr_high - curr_open) / curr_open
            pump_data.append((pump, date_str))
            
            # Dump: How much did it bleed?
            dump = (curr_low - curr_open) / curr_open
            dump_data.append((dump, date_str))

        # --- B. Interday Stats (Requires Previous Candle) ---
        if i > 0:
            prev_close = float(candles[i-1][4])
            
            # 1. Logarithmic Returns (Standard Finance Volatility)
            # Formula: ln(Current_Close / Previous_Close)
            if prev_close > 0 and curr_close > 0:
                log_ret = math.log(curr_close / prev_close)
                log_returns.append(log_ret)

            # 2. True Range (TR) Calculation
            # TR = Max(High-Low, |High-PrevClose|, |Low-PrevClose|)
            raw_hl = curr_high - curr_low
            raw_h_pc = abs(curr_high - prev_close)
            raw_l_pc = abs(curr_low - prev_close)
            
            true_range = max(raw_hl, raw_h_pc, raw_l_pc)
            tr_list.append(true_range)

    # 4. Compiling the Stats Dictionary
    stats = {}
    
    # --- SECTION A: VOLATILITY (Log Returns) ---
    if len(log_returns) > 1:
        # Standard deviation of log returns
        stdev_log = statistics.stdev(log_returns)
        stats['vol_day'] = stdev_log
        stats['vol_week'] = stdev_log * (7 ** 0.5) # Annualized rule applied to week
    else:
        stats['vol_day'] = 0.0
        stats['vol_week'] = 0.0

    # Max moves (Converted back to linear % for display readability)
    # We use the raw daily change for "Max Surge" just for display purposes
    # But strictly speaking, the user asked for Log, so we stick to Log stats for Vol.
    # For "Max Daily Surge" display, simple % is often more intuitive, 
    # but I will use the Max Log Return converted to linear: (e^x - 1)
    max_log = max(log_returns) if log_returns else 0
    min_log = min(log_returns) if log_returns else 0
    stats['max_daily_surge'] = math.exp(max_log) - 1
    stats['max_daily_crash'] = math.exp(min_log) - 1

    # --- SECTION B: INTRADAY EXTREMES ---
    # Max Pump
    if pump_data:
        stats['max_pump_val'], stats['max_pump_date'] = max(pump_data, key=lambda x: x[0])
        pump_values = [x[0] for x in pump_data]
        stats['avg_pump'] = statistics.mean(pump_values)
        stats['std_pump'] = statistics.stdev(pump_values) if len(pump_values) > 1 else 0
    else:
        stats['max_pump_val'], stats['max_pump_date'] = (0, "N/A")
        stats['avg_pump'] = 0
        stats['std_pump'] = 0

    # Max Dump (Min because negative)
    if dump_data:
        stats['max_dump_val'], stats['max_dump_date'] = min(dump_data, key=lambda x: x[0])
        dump_values = [x[0] for x in dump_data]
        stats['avg_dump'] = statistics.mean(dump_values)
        stats['std_dump'] = statistics.stdev(dump_values) if len(dump_values) > 1 else 0
    else:
        stats['max_dump_val'], stats['max_dump_date'] = (0, "N/A")
        stats['avg_dump'] = 0
        stats['std_dump'] = 0

    # --- SECTION C: ATR (Risk Management) ---
    # We take the Simple Moving Average of the LAST n TR values.
    # This is slightly different from Wilder's Smoothing but statistically valid for snapshots.
    current_close = float(candles[-1][4])
    
    if len(tr_list) >= 14:
        stats['atr_14'] = statistics.mean(tr_list[-14:])
    else:
        stats['atr_14'] = 0
        
    if len(tr_list) >= 28:
        atr_28 = statistics.mean(tr_list[-28:])
        stats['atr_28'] = atr_28
        stats['atr_relative'] = atr_28 / current_close if current_close > 0 else 0
    else:
        stats['atr_28'] = 0
        stats['atr_relative'] = 0

    # --- SECTION D: PERCENTILES (Martingale Logic) ---
    # We focus on PUMPS for the DCA levels
    if pump_data:
        # Extract values and sort
        pv = sorted([p[0] for p in pump_data])
        n = len(pv)
        
        # Helper for safe indexing
        def get_p(percent):
            return pv[int(n * percent)] if n > 0 else 0

        stats['p75_pump'] = get_p(0.75)
        stats['p80_pump'] = get_p(0.80)
        stats['p85_pump'] = get_p(0.85)
        stats['p90_pump'] = get_p(0.90)
        stats['p95_pump'] = get_p(0.95)
        stats['p99_pump'] = get_p(0.99)
    else:
        # Zeros if no data
        for k in ['p75_pump','p80_pump','p85_pump','p90_pump','p95_pump','p99_pump']:
            stats[k] = 0.0

    return stats
