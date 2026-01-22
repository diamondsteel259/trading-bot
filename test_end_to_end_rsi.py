#!/usr/bin/env python3
"""
End-to-end test of RSI scanner fix integrated with bot flow.

This test simulates the actual bot's scanning behavior to ensure the
RSI calculation works correctly with 15+ candles per pair.
"""

import sys
from config import Config
from logging_setup import setup_logging, get_logger
from valr_api import VALRAPI
from rsi_scanner import RSIScanner

def test_bot_scan_flow():
    """Test the full RSI scanning flow as the bot would use it."""
    
    # Initialize like the bot does
    config = Config()
    setup_logging(config)
    logger = get_logger("test")
    
    logger.info("="*70)
    logger.info("END-TO-END RSI SCANNER TEST")
    logger.info("="*70)
    
    # Initialize API and scanner
    api = VALRAPI(config)
    scanner = RSIScanner(api, config)
    
    # Use the actual trading pairs from config
    pairs = config.TRADING_PAIRS
    logger.info(f"Testing {len(pairs)} trading pairs from config")
    
    # Run a full scan like the bot would
    logger.info(f"Running full RSI scan (threshold: {config.RSI_THRESHOLD})...")
    results = scanner.scan_pairs(pairs)
    
    # Analyze results
    logger.info("\n" + "="*70)
    logger.info("SCAN RESULTS")
    logger.info("="*70)
    
    valid_pairs = 0
    sufficient_candles = 0
    oversold_signals = 0
    
    for result in results:
        pair = result.get("pair")
        rsi = result.get("rsi_value")
        is_oversold = result.get("is_oversold", False)
        error = result.get("error")
        
        if error:
            logger.warning(f"{pair}: ERROR - {error}")
            continue
            
        valid_pairs += 1
        
        # Check candle count from scanner statistics
        stats = scanner.get_scan_statistics()
        history_lengths = stats.get("price_history_lengths", {})
        candle_count = history_lengths.get(pair, 0)
        
        if candle_count >= 15:
            sufficient_candles += 1
            status = "✅"
        else:
            status = "❌"
        
        if is_oversold:
            oversold_signals += 1
            signal = "🎯 OVERSOLD"
        else:
            signal = "NO SIGNAL"
        
        rsi_str = f"{rsi:.1f}" if rsi is not None else "N/A"
        logger.info(f"{pair}: Candles={candle_count} {status} | RSI={rsi_str} | {signal}")
    
    # Summary
    logger.info("\n" + "="*70)
    logger.info("TEST SUMMARY")
    logger.info("="*70)
    logger.info(f"Valid pairs tested: {valid_pairs}")
    logger.info(f"Pairs with 15+ candles: {sufficient_candles}/{valid_pairs}")
    logger.info(f"Oversold signals detected: {oversold_signals}")
    
    # Determine pass/fail
    if valid_pairs > 0 and sufficient_candles == valid_pairs:
        logger.info("\n✅ TEST PASSED: All valid pairs have 15+ candles!")
        logger.info("   RSI scanner is ready for production use.")
        return 0
    elif sufficient_candles > 0:
        logger.warning(f"\n⚠️  TEST PARTIAL: {sufficient_candles}/{valid_pairs} pairs have 15+ candles")
        return 1
    else:
        logger.error("\n❌ TEST FAILED: No pairs have sufficient candles")
        return 1

if __name__ == "__main__":
    try:
        sys.exit(test_bot_scan_flow())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ Test failed with exception: {e}")
        sys.exit(1)
