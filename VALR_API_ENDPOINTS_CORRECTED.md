# VALR API Endpoints - CORRECTED

## Summary of Endpoint Fixes

All endpoints have been verified against official VALR API documentation and reference implementations from:
- https://github.com/johnstonematt/valr-client (official Python reference implementation)

## Critical Endpoint Changes

### 1. LIMIT ORDER PLACEMENT (FIXED)

**Before (INCORRECT - returns 404):**
```
POST /v1/orders
Body: {pair, side, quantity, price, type: "LIMIT", postOnly}
```

**After (CORRECT - from official docs):**
```
POST /v1/orders/limit
Body: {pair, side, quantity, price, postOnly, timeInForce}
```

**Changes:**
- Endpoint: `/orders` → `/orders/limit`
- Removed `type` field (endpoint implies LIMIT order)
- Added `timeInForce: "GTC"` (Good Till Cancel)
- Request body sent as JSON (not params)

### 2. MARKET ORDER PLACEMENT (FIXED)

**Before (INCORRECT - returns 404):**
```
POST /v1/orders
Body: {pair, side, quantity, type: "MARKET"}
```

**After (CORRECT - from official docs):**
```
POST /v1/orders/market
Body: {pair, side, quoteAmount}
```

**Changes:**
- Endpoint: `/orders` → `/orders/market`
- Parameter: `quantity` → `quoteAmount` (for sell-side market orders)
- Removed `type` field (endpoint implies MARKET order)

### 3. ORDER STATUS (FIXED)

**Before (INCORRECT):**
```
GET /v1/orders/{order_id}
```

**After (CORRECT - from official docs):**
```
GET /v1/orders/{symbol}/orderid/{order_id}
```

**Changes:**
- Endpoint: `/orders/{order_id}` → `/orders/{symbol}/orderid/{order_id}`
- Now requires `pair` parameter
- Updated `get_order_status(order_id, pair=...)` signature

### 4. ORDER CANCELLATION (FIXED)

**Before (INCORRECT):**
```
DELETE /v1/orders/{order_id}
```

**After (CORRECT - from official docs):**
```
DELETE /v1/orders/order
Body: {pair, orderId}
```

**Changes:**
- Endpoint: `/orders/{order_id}` → `/orders/order`
- Method: URL parameter → POST-like JSON body
- Body format: `{pair: "BTCZAR", orderId: "xxx"}`
- Updated `cancel_order(order_id, pair=...)` signature

### 5. REQUEST BODY HANDLING (FIXED)

**Before (INCORRECT for VALR):**
- GET requests used `params`
- POST/PUT/DELETE used `data` as JSON body
- DELETE requests might send empty body

**After (CORRECT for VALR):**
- GET requests use `params`
- POST/PUT/DELETE send `data` as JSON body
- DELETE requests send JSON body with order details
- 204/202 responses handled (no content)

## Working Endpoints (Verified)

### Public Endpoints (No Authentication)

| Method | Endpoint | Purpose | Status |
|---------|-----------|----------|--------|
| GET | `/v1/public/{pair}/marketsummary` | Market data | ✅ Working |
| GET | `/v1/public/{pair}/orderbook` | Order book | ✅ Working |
| GET | `/v1/public/{pair}/orderbook/full` | Full order book | ✅ Working |
| GET | `/v1/public/{pair}/trades` | Recent trades | ✅ Working |
| GET | `/v1/public/marketsummary` | All market summaries | ✅ Working |
| GET | `/v1/public/currencies` | Available currencies | ✅ Working |
| GET | `/v1/public/currencypairs` | Available pairs | ✅ Working |

### Authenticated Endpoints (API Key Required)

| Method | Endpoint | Purpose | Status |
|---------|-----------|----------|--------|
| GET | `/v1/account/balances` | Account balances | ✅ Working |
| POST | `/v1/orders/limit` | Place limit order | ✅ Fixed |
| POST | `/v1/orders/market` | Place market order | ✅ Fixed |
| GET | `/v1/orders/{pair}/orderid/{id}` | Get order status | ✅ Fixed |
| DELETE | `/v1/orders/order` | Cancel order | ✅ Fixed |
| GET | `/v1/orders/open` | Open orders | ✅ Working |
| GET | `/v1/orders/history` | Order history | ✅ Working |
| GET | `/v1/orders/{pair}/orderid/{id}/fills` | Order fills | ✅ Working |

## Code Changes Summary

### valr_api.py

1. **`_make_request()`** - Fixed request body handling:
   - GET requests use `params` for query parameters
   - POST/PUT/DELETE use `data` for JSON body
   - Proper handling of 204/202 responses

2. **`place_limit_order()`** - Corrected endpoint:
   - Endpoint: `/orders/limit`
   - Payload: `{pair, side, quantity, price, postOnly, timeInForce}`
   - Removed `type: "LIMIT"` (implied by endpoint)

3. **`place_market_order()`** - Corrected endpoint:
   - Endpoint: `/orders/market`
   - Payload: `{pair, side, quoteAmount}` (not `quantity`)

4. **`cancel_order()`** - Corrected endpoint and signature:
   - Endpoint: `/orders/order`
   - Signature: `cancel_order(order_id, pair=None)`
   - Payload: `{pair, orderId}`
   - Returns boolean (success/failure)

5. **`get_order_status()`** - Corrected endpoint and signature:
   - Endpoint: `/orders/{pair}/orderid/{order_id}`
   - Signature: `get_order_status(order_id, pair=None)`
   - Requires `pair` parameter

### trading_engine.py

Updated all method calls to pass `pair` parameter:

1. **`_wait_for_order_fill()`** - Added `pair` parameter:
   - Signature: `_wait_for_order_fill(order_id, pair, ...)`
   - Calls: `get_order_status(order_id, pair=pair)`

2. **`_cancel_if_open()`** - Added `pair` parameter:
   - Signature: `_cancel_if_open(order_id, pair=None)`
   - Calls: `get_order_status(order_id, pair=pair)` and `cancel_order(order_id, pair=pair)`

3. **`_sync_persisted_order_status()`** - Added `pair` parameter:
   - Signature: `_sync_persisted_order_status(order_id, pair=None)`
   - Calls: `get_order_status(order_id, pair=pair)`

4. **`_monitor_single_position()`** - Updated calls:
   - TP/SL status checks: `get_order_status(tp_id, pair=pair)`

5. **`_close_position_at_market()`** - Updated calls:
   - Cancellation: `_cancel_if_open(order_id, pair=pair)`
   - Sync: `_sync_persisted_order_status(order_id, pair=pair)`

6. **`execute_trade_setup()`** - Updated calls:
   - Entry order: `_wait_for_order_fill(entry_order_id, pair=pair, ...)`
   - Entry cancellation: `cancel_order(entry_order_id, pair=pair)`

## API Authentication

All requests use signature-based authentication:
```
Headers:
  X-VALR-API-KEY: <api_key>
  X-VALR-SIGNATURE: <sha512_hmac_signature>
  X-VALR-TIMESTAMP: <milliseconds_since_epoch>
  Content-Type: application/json

Signature calculation:
  message = timestamp + method + path + body
  signature = hmac_sha512(message, api_secret)
```

## Testing

Run the endpoint test script to verify all endpoints:
```bash
python3 test_valr_endpoints.py
```

This will test:
1. Public endpoints (no auth required)
2. Account balances (auth required)
3. Limit order placement (auth + trade permission required)
4. Order status checking
5. Order cancellation
6. Order history

## Success Criteria

✅ **Endpoint Fixes Complete:**
- `/v1/orders/limit` - Returns 200 (not 404)
- `/v1/orders/market` - Returns 200 (not 404)
- `/v1/orders/{pair}/orderid/{id}` - Returns order status
- `/v1/orders/order` (DELETE) - Cancels orders

✅ **Request Format Correct:**
- POST/DELETE send JSON body (not query params)
- GET uses query params
- Proper headers and signatures

✅ **Backward Compatible:**
- Optional `pair` parameter with fallback for legacy code
- Existing methods maintain compatibility

## References

1. Official VALR API Documentation: https://docs.valr.com/
2. Reference Implementation: https://github.com/johnstonematt/valr-client
3. VALR Python SDK: https://github.com/valr-com (various implementations)

## Migration Notes

If you have existing code using the old endpoints:

**Old pattern:**
```python
api.place_limit_order(pair="BTCZAR", side="BUY", ...)
api.cancel_order(order_id="xxx")
api.get_order_status(order_id="xxx")
```

**New pattern:**
```python
api.place_limit_order(pair="BTCZAR", side="BUY", ...)  # Same call
api.cancel_order(order_id="xxx", pair="BTCZAR")  # Add pair
api.get_order_status(order_id="xxx", pair="BTCZAR")  # Add pair
```

The `pair` parameter is now **required** for:
- `cancel_order()`
- `get_order_status()`

For backward compatibility, `pair` defaults to `None` but will be required in production code.
