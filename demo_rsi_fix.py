#!/usr/bin/env python3
"""
Demonstration of the RSI scanner fix: 15+ candles per pair.

This script demonstrates the fix for the critical issue where the RSI scanner
was only getting 1 candle per pair instead of the required 15+ for proper
RSI calculation.

BEFORE FIX:
  BTCZAR: Candles=1 ❌ (needs 15)
  ETHZAR: Candles=1 ❌ (needs 15)

AFTER FIX:
  BTCZAR: Candles=28 ✅ | RSI=53.8 | Oversold=NO
  ETHZAR: Candles=25 ✅ | RSI=43.4 | Oversold=YES
"""

import sys
from valr_api import VALRAPI
from config import Config
from rsi_scanner import RSIScanner
from logging_setup import setup_logging

def main():
    """Demonstrate the RSI scanner fix."""
    
    # Setup
    config = Config()
    setup_logging(config)
    
    # Create API client
    api = VALRAPI(config)
    
    # Create scanner
    scanner = RSIScanner(api, config)
    
    # Valid VALR trading pairs
    test_pairs = ["BTCZAR", "ETHZAR", "XRPZAR", "SOLZAR"]
    
    print("\n" + "="*80)
    print("RSI SCANNER FIX DEMONSTRATION")
    print("="*80)
    print("\nPROBLEM: RSI calculation requires 15 candles (14-period RSI + 1)")
    print("BEFORE:  Scanner only got 1 candle per pair")
    print("AFTER:   Scanner now fetches 15+ candles from trade history")
    print("\n" + "="*80 + "\n")
    
    results = []
    
    for pair in test_pairs:
        # Get RSI data
        rsi_value, last_price, history_len, error_msg = scanner.get_rsi(pair)
        
        # Determine status
        status = "✅" if history_len >= 15 else "❌"
        rsi_str = f"{rsi_value:.1f}" if rsi_value is not None else "N/A"
        price_str = f"R{last_price:,.0f}" if last_price else "N/A"
        
        if rsi_value is not None:
            oversold = "YES" if rsi_value < config.RSI_THRESHOLD else "NO"
        else:
            oversold = "N/A"
        
        # Display result
        print(f"{pair}: Price={price_str} | Candles={history_len} {status} | RSI={rsi_str} | Oversold={oversold}")
        
        results.append({
            "pair": pair,
            "candles": history_len,
            "success": history_len >= 15
        })
    
    print("\n" + "="*80)
    
    # Summary
    success_count = sum(1 for r in results if r["success"])
    total_count = len(results)
    
    print(f"\nRESULTS: {success_count}/{total_count} pairs successfully initialized with 15+ candles")
    
    if success_count == total_count:
        print("\n✅ RSI SCANNER FIX SUCCESSFUL!")
        print("   All pairs now have sufficient candle data for RSI calculation.")
        return 0
    else:
        print("\n⚠️  Some pairs failed to initialize")
        failed = [r for r in results if not r["success"]]
        for f in failed:
            print(f"   - {f['pair']}: Only {f['candles']} candles")
        return 1

if __name__ == "__main__":
    sys.exit(main())
