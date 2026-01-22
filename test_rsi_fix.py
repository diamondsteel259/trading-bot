#!/usr/bin/env python3
"""Test script to verify RSI scanner gets 15+ candles."""

import sys
from valr_api import VALRAPI
from config import Config
from rsi_scanner import RSIScanner
from logging_setup import setup_logging

def test_rsi_scanner():
    """Test RSI scanner candle initialization."""
    
    # Setup
    config = Config()
    setup_logging(config)
    
    # Create API client (without authentication for public endpoints)
    api = VALRAPI(config)
    
    # Create scanner
    scanner = RSIScanner(api, config)
    
    print("\n" + "="*70)
    print("Testing RSI Scanner - 15+ Candle Initialization")
    print("="*70 + "\n")
    
    test_pairs = ["BTCZAR", "ETHZAR", "XRPZAR", "ADAZAR", "SOLZAR"]
    
    for pair in test_pairs:
        print(f"\nTesting {pair}:")
        print("-" * 50)
        
        # Test RSI calculation
        rsi_value, last_price, history_len, error_msg = scanner.get_rsi(pair)
        
        status = "✅" if history_len >= 15 else "❌"
        
        print(f"  Candles: {history_len} {status}")
        print(f"  Last Price: R{last_price:,.2f}" if last_price else "  Last Price: N/A")
        
        if rsi_value is not None:
            print(f"  RSI: {rsi_value:.1f}")
            oversold = "YES" if rsi_value < config.RSI_THRESHOLD else "NO"
            print(f"  Oversold: {oversold}")
        else:
            print(f"  RSI: N/A ({error_msg})")
        
        # Check success
        if history_len >= 15:
            print(f"  ✅ SUCCESS: Got {history_len} candles (need 15)")
        else:
            print(f"  ❌ FAILED: Only got {history_len} candles (need 15)")
            if error_msg:
                print(f"  Error: {error_msg}")
    
    print("\n" + "="*70)
    print("Test Complete")
    print("="*70 + "\n")
    
    # Check if all tests passed
    stats = scanner.get_scan_statistics()
    history_lengths = stats.get("price_history_lengths", {})
    
    all_passed = all(length >= 15 for length in history_lengths.values())
    
    if all_passed:
        print("✅ All pairs have 15+ candles - RSI fix successful!\n")
        return 0
    else:
        print("❌ Some pairs still have < 15 candles - fix incomplete\n")
        return 1

if __name__ == "__main__":
    sys.exit(test_rsi_scanner())
