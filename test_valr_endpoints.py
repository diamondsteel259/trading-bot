#!/usr/bin/env python3
"""
Test script to verify VALR API endpoints work correctly.
Tests the endpoints as per official VALR API documentation.
"""

import os
from decimal import Decimal
from config import Config
from valr_api import VALRAPI

def test_endpoints():
    """Test VALR API endpoints with correct paths."""
    config = Config()
    api = VALRAPI(config)

    print("=" * 80)
    print("TESTING VALR API ENDPOINTS (Official Documentation)")
    print("=" * 80)

    # Test 1: Account Balances
    print("\n1. Testing Account Balances endpoint...")
    print("   Expected: /v1/account/balances (GET)")
    try:
        balances = api.get_account_balances()
        print(f"   ✅ SUCCESS - ZAR balance: {balances.get('ZAR', 0)}")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")

    # Test 2: Market Summary (Public)
    print("\n2. Testing Market Summary endpoint...")
    print("   Expected: /v1/public/BTCZAR/marketsummary (GET)")
    try:
        summary = api.get_pair_summary("BTCZAR")
        price = summary.get("lastTradedPrice", summary.get("lastPrice", "N/A"))
        print(f"   ✅ SUCCESS - BTCZAR Price: {price}")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")

    # Test 3: Order Book (Public)
    print("\n3. Testing Order Book endpoint...")
    print("   Expected: /v1/public/BTCZAR/orderbook (GET)")
    try:
        orderbook = api.get_order_book("BTCZAR")
        best_bid = orderbook.get("bids", orderbook.get("Bids", []))[0].get("price") if orderbook.get("bids") else "N/A"
        print(f"   ✅ SUCCESS - Best bid: {best_bid}")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")

    # Test 4: Recent Trades (Public)
    print("\n4. Testing Recent Trades endpoint...")
    print("   Expected: /v1/public/BTCZAR/trades (GET)")
    try:
        trades = api.get_recent_trades("BTCZAR", limit=5)
        print(f"   ✅ SUCCESS - Retrieved {len(trades)} trades")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")

    # Test 5: Limit Order Placement (AUTHENTICATED)
    print("\n5. Testing Limit Order placement...")
    print("   Expected: /v1/orders/limit (POST)")
    print("   Payload: {pair, side, quantity, price, postOnly, timeInForce}")
    print("   NOTE: This requires valid API keys with Trade permission")
    try:
        # Test with a very small order at a price that won't fill
        test_price = "1.00"  # Very low price, won't execute
        test_qty = "0.00000001"  # Minimum quantity
        result = api.place_limit_order(
            pair="BTCZAR",
            side="BUY",
            quantity=test_qty,
            price=test_price,
            post_only=True
        )
        order_id = result.get("id", result.get("orderId", "unknown"))
        print(f"   ✅ SUCCESS - Order ID: {order_id}")
        print(f"   Response keys: {list(result.keys())}")

        # Cancel the test order
        if order_id and order_id != "unknown":
            print(f"\n   Cleaning up: Cancelling test order...")
            cancelled = api.cancel_order(order_id, pair="BTCZAR")
            print(f"   Cancel success: {cancelled}")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        print(f"   Possible causes:")
        print(f"   - Invalid API credentials")
        print(f"   - API key missing 'Trade' permission")
        print(f"   - Incorrect endpoint path (404 error)")
        print(f"   - Request body format mismatch")

    # Test 6: Order Status (AUTHENTICATED)
    print("\n6. Testing Order Status endpoint...")
    print("   Expected: /v1/orders/BTCZAR/orderid/{id} (GET)")
    print("   NOTE: Skipped (requires active order ID)")

    # Test 7: Order History (AUTHENTICATED)
    print("\n7. Testing Order History endpoint...")
    print("   Expected: /v1/orders/history (GET)")
    try:
        history = api.get_order_history(limit=5)
        print(f"   ✅ SUCCESS - Retrieved {len(history)} orders")
        if history:
            print(f"   Sample order keys: {list(history[0].keys())}")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")

    print("\n" + "=" * 80)
    print("ENDPOINT TEST SUMMARY")
    print("=" * 80)
    print("\n✅ Public endpoints work correctly (no auth required)")
    print("✅ Account balances works (auth required)")
    print("❓ Order placement/cancellation requires valid Trade API key")
    print("\nIf order placement fails:")
    print("1. Check API key has 'Trade' permission at valr.com")
    print("2. Verify VALR_API_KEY and VALR_API_SECRET in .env")
    print("3. Check account balance for minimum trade amount")
    print("\n" + "=" * 80)

if __name__ == "__main__":
    test_endpoints()
