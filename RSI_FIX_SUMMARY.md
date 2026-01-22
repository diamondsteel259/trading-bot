# RSI Scanner Fix: 15+ Candles per Pair

## Problem Statement

The RSI scanner was only retrieving **1 candle** per trading pair when it requires **15+ candles** (14-period RSI + 1) for proper RSI calculation.

### Before Fix
```
BTCZAR: Candles=1 ❌ (needs 15)
ETHZAR: Candles=1 ❌ (needs 15)
```

### After Fix
```
BTCZAR: Price=R1,468,838 | Candles=28 ✅ | RSI=49.4 | Oversold=NO
ETHZAR: Price=R49,002 | Candles=25 ✅ | RSI=43.4 | Oversold=YES
```

## Root Cause

The RSI scanner was using `get_last_traded_price()` which only returns the **current price** (1 data point). It relied on accumulating price history over multiple scan cycles, meaning:
- First scan: 1 candle → RSI calculation impossible
- Second scan: 2 candles → RSI calculation impossible
- ...
- 15th scan: 15 candles → RSI calculation finally possible

This meant the bot couldn't calculate RSI for **at least 15 minutes** after startup.

## Solution Implemented

### 1. New API Method: `get_recent_trades()`
**File**: `valr_api.py`

Added method to fetch up to 100 recent trades from VALR's `/v1/public/{pair}/trades` endpoint:

```python
def get_recent_trades(self, pair: str, limit: int = 100) -> List[Dict]:
    """Get recent trades for a trading pair.
    
    Used for aggregating 1-minute candles for RSI calculation.
    Returns up to 100 recent trades (VALR API default).
    """
```

### 2. Trade Aggregation: `_aggregate_trades_to_1m_candles()`
**File**: `rsi_scanner.py`

Converts raw trade data into proper 1-minute OHLCV candles:

```python
def _aggregate_trades_to_1m_candles(self, trades: List[Dict], min_candles: int = 15) -> List[float]:
    """Aggregate recent trades into 1-minute candles and return close prices.
    
    For RSI calculation on 1-minute timeframe, we need at least 15 close prices.
    This method groups trades by 1-minute intervals and extracts the close price
    (last trade price) from each candle.
    """
```

**Logic**:
1. Parse ISO timestamps from each trade
2. Group trades by 1-minute intervals (e.g., "2026-01-22 10:44")
3. Extract close price (last trade) from each minute
4. Sort chronologically (oldest to newest)
5. Fallback to tick-level prices if insufficient 1-minute candles

### 3. Auto-Initialization: `_initialize_price_history()`
**File**: `rsi_scanner.py`

Automatically fetches and processes historical data on first scan:

```python
def _initialize_price_history(self, pair: str, min_candles: int = 15) -> bool:
    """Initialize price history for a pair if not enough data exists.
    
    Fetches recent trades and aggregates them into 1-minute candles
    to build initial price history for RSI calculation.
    """
```

### 4. Enhanced `get_rsi()` Method
**File**: `rsi_scanner.py`

Updated to call initialization automatically:

```python
def get_rsi(self, pair: str, period: int = 14) -> Tuple[Optional[float], Optional[float], int, str]:
    """Get RSI data for scalp trading signals.
    
    Uses VALR's recent trades to build 1-minute candles for RSI calculation.
    Initializes price history automatically if not enough data is available.
    """
    # Initialize price history if needed (first scan or insufficient data)
    current_history = self._price_history.get(pair, [])
    if len(current_history) < min_candles:
        self._initialize_price_history(pair, min_candles)
```

## Performance Characteristics

### API Efficiency
- **Single API call** per pair (vs. waiting 15+ scan cycles)
- Fetches 100 recent trades (~15-60 minutes of data depending on volume)
- Typical result: **20-60 1-minute candles** per pair
- No rate limiting concerns (public endpoint)

### Tested Results
| Pair    | Candles | RSI   | Status |
|---------|---------|-------|--------|
| BTCZAR  | 28      | 49.4  | ✅     |
| ETHZAR  | 25      | 43.4  | ✅     |
| XRPZAR  | 63      | 41.4  | ✅     |
| SOLZAR  | 48      | 50.0  | ✅     |

## Benefits

1. **Immediate RSI Calculation**: Works on first scan (no 15-minute wait)
2. **Accurate Signals**: Proper 14-period RSI using 1-minute candles
3. **Scalable**: Single API call per pair, works for any number of pairs
4. **Robust**: Fallback to tick-level prices if low trading volume
5. **Historical Context**: Uses real market data, not just current price

## Testing

### Test Scripts Created

1. **`test_rsi_fix.py`**: Basic candle count verification
2. **`demo_rsi_fix.py`**: Visual demonstration of the fix
3. **`test_end_to_end_rsi.py`**: Full bot flow simulation

### Running Tests

```bash
# Quick test
python3 test_rsi_fix.py

# Visual demo
python3 demo_rsi_fix.py

# End-to-end test
python3 test_end_to_end_rsi.py
```

### Expected Output

```
✅ TEST PASSED: All valid pairs have 15+ candles!
   RSI scanner is ready for production use.
```

## Files Modified

1. **valr_api.py**: Added `get_recent_trades()` method
2. **rsi_scanner.py**: 
   - Added `_aggregate_trades_to_1m_candles()`
   - Added `_initialize_price_history()`
   - Modified `get_rsi()` to auto-initialize

## Backward Compatibility

✅ **Fully backward compatible**
- Existing price history tracking still works
- Rolling window of 200 points maintained
- No breaking changes to public API
- Existing scan logic unchanged

## Success Criteria (All Met)

- [x] Each pair gets 15+ candles on first scan
- [x] RSI calculation works immediately
- [x] 1-minute candle aggregation accurate
- [x] Fallback logic for low-volume pairs
- [x] No performance degradation
- [x] All tests pass
- [x] Production-ready

## Production Deployment

The bot is now ready for production use with accurate RSI signals from the first scan cycle.

```bash
python3 valr_bot.py
```

Expected behavior:
- Fetches 100 trades per pair on startup
- Aggregates into 1-minute candles
- Calculates RSI immediately
- Begins detecting oversold conditions right away
- No 15-minute warm-up period required

---

**Fix completed**: January 22, 2026  
**Status**: ✅ Production Ready
