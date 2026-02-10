# Stats Dictionary Structure Example

This file demonstrates the structure and sample values of the `stats` dictionary returned by the `analyze_market_data` function in `TickerGrubProServer.py`.

```python
stats = {
    # --- VOLATILITY (Log Returns) ---
    'vol_day': 0.042,              # Daily Volatility (Stdev of Log Returns)
    'vol_week': 0.111,             # Weekly Volatility (vol_day * sqrt(7))
    'max_daily_surge': 0.150,      # Max Day-Close vs Prev-Close gain (e.g., +15.0%)
    'max_daily_crash': -0.120,     # Max Day-Close vs Prev-Close loss (e.g., -12.0%)

    # --- INTRADAY EXTREMES (Pumps & Dumps) ---
    'max_pump_val': 0.250,         # Highest (High - Open) / Open observed
    'max_pump_date': '2024-03-15', # Date when the max pump occurred
    'avg_pump': 0.035,             # Average intraday pump across all days
    'std_pump': 0.012,             # Standard deviation of intraday pumps

    'max_dump_val': -0.180,        # Lowest (Low - Open) / Open observed
    'max_dump_date': '2024-01-10', # Date when the max dump occurred
    'avg_dump': -0.028,            # Average intraday dump across all days
    'std_dump': 0.009,             # Standard deviation of intraday dumps

    # --- ATR (Risk Management) ---
    'atr_14': 1250.50,             # Average True Range (Last 14 candles)
    'atr_28': 1210.25,             # Average True Range (Last 28 candles)
    'atr_relative': 0.045,         # ATR(28) / Current Price (e.g., 4.5% of price)

    # --- PERCENTILES (Pump Distribution) ---
    'p75_pump': 0.040,             # 75% of days had a pump <= 4.0%
    'p80_pump': 0.048,             # 80% of days had a pump <= 4.8%
    'p85_pump': 0.055,             # 85% of days had a pump <= 5.5%
    'p90_pump': 0.068,             # 90% of days had a pump <= 6.8%
    'p95_pump': 0.092,             # 95% of days had a pump <= 9.2%
    'p99_pump': 0.145              # 99% of days had a pump <= 14.5%
}
```
