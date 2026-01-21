"""
RSI scanner for VALR trading bot.
Identifies oversold conditions in trading pairs using RSI indicators.
"""

from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
import time

from valr_api import VALRAPI
from config import Config
from logging_setup import get_logger
from decimal_utils import DecimalUtils


class RSIScannerError(Exception):
    """Raised when RSI scanning operations fail."""
    pass


class RSIScanner:
    """RSI scanner for identifying oversold trading opportunities."""
    
    def __init__(self, api: VALRAPI, config: Config):
        """Initialize RSI scanner."""
        self.api = api
        self.config = config
        self.logger = get_logger("rsi_scanner")
        self.last_scan_times: Dict[str, datetime] = {}
        self.scan_cooldown_seconds = 300  # 5 minutes between scans per pair
    
    def get_rsi(self, pair: str, interval: str = "1m", limit: int = 100) -> Optional[float]:
        """
        Get the latest RSI value for a trading pair.
        
        Args:
            pair: Trading pair symbol (e.g., 'BTCZAR')
            interval: Time interval ('1m', '5m', '15m', '1h', '4h', '1d')
            limit: Number of data points to retrieve
            
        Returns:
            Latest RSI value or None if unavailable
        """
        try:
            self.logger.debug(f"Fetching RSI data for {pair} (interval: {interval})")
            
            rsi_data = self.api.get_rsi_data(pair, interval, limit)
            
            if not rsi_data:
                self.logger.warning(f"No RSI data available for {pair}")
                return None
            
            # Get the most recent RSI value
            latest_rsi = rsi_data[-1]
            rsi_value = latest_rsi.get('value')
            
            if rsi_value is None:
                self.logger.warning(f"RSI value is None for {pair}")
                return None
            
            return float(rsi_value)
            
        except Exception as e:
            self.logger.error(f"Failed to get RSI for {pair}: {e}")
            return None
    
    def scan_pair(self, pair: str, interval: str = "1m") -> Tuple[bool, Optional[float]]:
        """
        Scan a single trading pair for oversold conditions.
        
        Args:
            pair: Trading pair symbol
            interval: Time interval for RSI calculation
            
        Returns:
            Tuple of (is_oversold, rsi_value)
        """
        # Check cooldown for this pair
        if self._is_in_cooldown(pair):
            self.logger.debug(f"Pair {pair} is in cooldown, skipping scan")
            return False, None
        
        rsi_value = self.get_rsi(pair, interval)
        
        if rsi_value is None:
            return False, None
        
        # Update last scan time
        self.last_scan_times[pair] = datetime.now()
        
        # Check if oversold (RSI < threshold)
        is_oversold = rsi_value < self.config.RSI_THRESHOLD
        
        # Log the scan result
        action = "BUY_SIGNAL" if is_oversold else "NO_SIGNAL"
        self.logger.log_rsi_scan(pair, rsi_value, self.config.RSI_THRESHOLD, action)
        
        return is_oversold, rsi_value
    
    def scan_pairs(self, pairs: Optional[List[str]] = None, interval: str = "1m") -> List[Dict]:
        """
        Scan multiple trading pairs for oversold conditions.
        
        Args:
            pairs: List of trading pairs to scan. Uses config.TRADING_PAIRS if None.
            interval: Time interval for RSI calculation
            
        Returns:
            List of scan results with pair, RSI value, and oversold status
        """
        if pairs is None:
            pairs = self.config.TRADING_PAIRS
        
        self.logger.info(f"Scanning {len(pairs)} pairs for oversold conditions")
        
        results = []
        for pair in pairs:
            try:
                is_oversold, rsi_value = self.scan_pair(pair, interval)
                
                results.append({
                    "pair": pair,
                    "rsi_value": rsi_value,
                    "is_oversold": is_oversold,
                    "threshold": self.config.RSI_THRESHOLD,
                    "timestamp": datetime.now().isoformat()
                })
                
                # Small delay between pairs to avoid overwhelming the API
                time.sleep(0.1)
                
            except Exception as e:
                self.logger.error(f"Failed to scan pair {pair}: {e}")
                results.append({
                    "pair": pair,
                    "rsi_value": None,
                    "is_oversold": False,
                    "error": str(e),
                    "timestamp": datetime.now().isoformat()
                })
        
        oversold_count = sum(1 for result in results if result.get("is_oversold", False))
        self.logger.info(f"RSI scan complete: {oversold_count}/{len(pairs)} pairs oversold")
        
        return results
    
    def find_best_entry(self, pair: str) -> Optional[Dict]:
        """
        Find the best entry price for a trading pair using order book analysis.
        
        Args:
            pair: Trading pair symbol
            
        Returns:
            Dictionary with entry price and quantity information, or None
        """
        try:
            # Get order book for the pair
            order_book = self.api.get_order_book(pair, "both")
            
            # Get the best ask price (for buying)
            asks = order_book.get('asks', [])
            bids = order_book.get('bids', [])
            
            if not asks:
                self.logger.warning(f"No asks available for {pair}")
                return None
            
            # Use the best ask price (lowest price to buy)
            best_ask = asks[0]  # Asks are sorted from lowest to highest
            best_bid = bids[0] if bids else None
            
            # Calculate recommended entry (slightly below best ask for better price)
            best_ask_price = float(best_ask['price'])
            recommended_entry = best_ask_price * 0.999  # 0.1% below market
            
            # Calculate quantity based on base trade amount
            quantity = self.config.BASE_TRADE_AMOUNT / Decimal(str(recommended_entry))
            
            # Format according to pair precision
            price_decimals = self.config.get_pair_decimals(pair)
            quantity_decimals = 8  # Most crypto pairs support 8 decimal places
            
            formatted_quantity = DecimalUtils.format_quantity(quantity, quantity_decimals)
            formatted_price = DecimalUtils.format_price(recommended_entry, price_decimals)
            
            return {
                "pair": pair,
                "current_price": best_ask_price,
                "best_bid": float(best_bid['price']) if best_bid else None,
                "best_ask": best_ask_price,
                "recommended_entry": float(formatted_price),
                "formatted_quantity": formatted_quantity,
                "formatted_price": formatted_price,
                "available_ask_quantity": float(best_ask.get('quantity', '0'))
            }
            
        except Exception as e:
            self.logger.error(f"Failed to analyze entry for {pair}: {e}")
            return None
    
    def _is_in_cooldown(self, pair: str) -> bool:
        """Check if a pair is in cooldown period."""
        if pair not in self.last_scan_times:
            return False
        
        time_since_last_scan = datetime.now() - self.last_scan_times[pair]
        return time_since_last_scan.total_seconds() < self.scan_cooldown_seconds
    
    def get_scan_statistics(self) -> Dict:
        """Get statistics about RSI scanning."""
        now = datetime.now()
        
        # Calculate scan frequency per pair
        scan_frequencies = {}
        for pair, last_scan in self.last_scan_times.items():
            time_diff = (now - last_scan).total_seconds()
            scan_frequencies[pair] = time_diff
        
        return {
            "total_pairs_scanned": len(self.last_scan_times),
            "pairs_in_cooldown": sum(1 for freq in scan_frequencies.values() if freq < self.scan_cooldown_seconds),
            "scan_cooldown_seconds": self.scan_cooldown_seconds,
            "last_scan_times": {pair: last_scan.isoformat() for pair, last_scan in self.last_scan_times.items()},
            "scan_frequencies_seconds": scan_frequencies
        }
    
    def reset_cooldowns(self) -> None:
        """Reset all cooldowns (useful for testing or manual intervention)."""
        self.last_scan_times.clear()
        self.logger.info("Reset all RSI scan cooldowns")