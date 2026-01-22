"""RSI scanner for VALR trading bot.

For high-frequency scalping, this module computes RSI locally using a rolling
window of last traded prices.

VALR's indicator endpoints are not consistently available across accounts/API
revisions; using market summary pricing is more reliable.
"""

from __future__ import annotations

from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone
import time

from valr_api import VALRAPI
from config import Config
from logging_setup import get_logger, get_valr_logger
from decimal_utils import DecimalUtils


class RSIScannerError(Exception):
    """Raised when RSI scanning operations fail."""


class RSIScanner:
    """RSI scanner for identifying oversold trading opportunities."""

    def __init__(self, api: VALRAPI, config: Config):
        self.api = api
        self.config = config
        self.logger = get_logger("rsi_scanner")
        self.valr_logger = get_valr_logger()

        self.last_scan_times: Dict[str, datetime] = {}
        self.scan_cooldown_seconds = config.RSI_PAIR_COOLDOWN_SECONDS

        self._price_history: Dict[str, List[float]] = {}
        self._max_history = 200

    def _add_price_point(self, pair: str, price: float) -> None:
        history = self._price_history.setdefault(pair, [])
        history.append(price)
        if len(history) > self._max_history:
            self._price_history[pair] = history[-self._max_history :]

    def _aggregate_trades_to_1m_candles(self, trades: List[Dict], min_candles: int = 15) -> List[float]:
        """Aggregate recent trades into 1-minute candles and return close prices.
        
        For RSI calculation on 1-minute timeframe, we need at least 15 close prices.
        This method groups trades by 1-minute intervals and extracts the close price
        (last trade price) from each candle.
        
        Args:
            trades: List of trade dictionaries from VALR API
            min_candles: Minimum number of candles to generate
            
        Returns:
            List of close prices for each 1-minute candle (oldest to newest)
        """
        if not trades:
            return []
        
        # Group trades by minute
        candles: Dict[str, List[Dict]] = {}
        
        for trade in trades:
            try:
                # Parse ISO timestamp to minute precision
                traded_at = trade.get("tradedAt", "")
                if not traded_at:
                    continue
                    
                # Parse and truncate to minute
                dt = datetime.fromisoformat(traded_at.replace("Z", "+00:00"))
                minute_key = dt.strftime("%Y-%m-%d %H:%M")
                
                if minute_key not in candles:
                    candles[minute_key] = []
                    
                candles[minute_key].append(trade)
            except Exception as e:
                self.logger.debug(f"Failed to parse trade timestamp: {e}")
                continue
        
        # Sort by minute key and extract close prices
        sorted_minutes = sorted(candles.keys())
        close_prices = []
        
        for minute_key in sorted_minutes:
            trades_in_minute = candles[minute_key]
            if trades_in_minute:
                # Close price is the last trade in the minute
                # Trades are sorted newest first from API, so take first one
                last_trade = trades_in_minute[0]
                close_price = float(last_trade.get("price", 0))
                if close_price > 0:
                    close_prices.append(close_price)
        
        # Return at least min_candles, but prefer all available
        if len(close_prices) >= min_candles:
            return close_prices
        
        # If we don't have enough candles from aggregation,
        # fall back to using individual trade prices (tick-level) with validation
        if len(trades) >= min_candles:
            self.logger.debug(f"Not enough 1m candles ({len(close_prices)}), using tick-level prices")

            # Validate tick-level data freshness (reject trades older than 5 minutes)
            now_utc = datetime.now(timezone.utc)
            max_age_seconds = 300  # 5 minutes

            tick_prices = []
            for trade in reversed(trades[-min_candles:]):  # Reverse to get oldest to newest
                try:
                    # Validate timestamp
                    traded_at = trade.get("tradedAt", "")
                    if traded_at:
                        dt = datetime.fromisoformat(traded_at.replace("Z", "+00:00"))
                        age_seconds = (now_utc - dt).total_seconds()

                        if age_seconds > max_age_seconds:
                            self.logger.debug(f"Skipping stale trade: {age_seconds:.0f}s old (>{max_age_seconds}s)")
                            continue

                    # Extract price
                    price = float(trade.get("price", 0))
                    if price > 0:
                        tick_prices.append(price)

                except Exception as e:
                    self.logger.debug(f"Error validating trade data: {e}")
                    continue

            if len(tick_prices) < min_candles:
                self.logger.warning(
                    f"Only {len(tick_prices)} fresh trades available after validation (need {min_candles})"
                )

            return tick_prices[-min_candles:] if len(tick_prices) >= min_candles else tick_prices
        
        return close_prices

    def _initialize_price_history(self, pair: str, min_candles: int = 15) -> bool:
        """Initialize price history for a pair if not enough data exists.
        
        Fetches recent trades and aggregates them into 1-minute candles
        to build initial price history for RSI calculation.
        
        Args:
            pair: Trading pair to initialize
            min_candles: Minimum number of candles needed
            
        Returns:
            True if successfully initialized with enough data, False otherwise
        """
        current_history = self._price_history.get(pair, [])
        if len(current_history) >= min_candles:
            return True  # Already have enough data
        
        try:
            self.logger.info(f"Fetching historical trades for {pair} to initialize RSI calculation...")
            trades = self.api.get_recent_trades(pair, limit=100)
            
            if not trades:
                self.logger.warning(f"No trades available for {pair}")
                return False
            
            close_prices = self._aggregate_trades_to_1m_candles(trades, min_candles)
            
            if len(close_prices) >= min_candles:
                self._price_history[pair] = close_prices
                self.logger.info(f"Initialized {pair} with {len(close_prices)} candles")
                return True
            else:
                self.logger.warning(f"Only got {len(close_prices)} candles for {pair}, need {min_candles}")
                # Store what we have anyway
                if close_prices:
                    self._price_history[pair] = close_prices
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to initialize price history for {pair}: {e}")
            return False

    def _calculate_rsi(self, prices: List[float], period: int = 14) -> Optional[float]:
        if len(prices) < period + 1:
            return None

        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [max(d, 0.0) for d in deltas]
        losses = [max(-d, 0.0) for d in deltas]

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    def get_rsi(self, pair: str, period: int = 14) -> Tuple[Optional[float], Optional[float], int, str]:
        """Get RSI data for scalp trading signals.
        
        Uses VALR's recent trades to build 1-minute candles for RSI calculation.
        Initializes price history automatically if not enough data is available.

        Returns:
            Tuple of (rsi_value, last_price, history_len, error_msg)
        """
        last_price = None
        history_len = 0
        min_candles = period + 1  # RSI needs period + 1 data points
        
        try:
            # Initialize price history if needed (first scan or insufficient data)
            current_history = self._price_history.get(pair, [])
            if len(current_history) < min_candles:
                self._initialize_price_history(pair, min_candles)
            
            # Get current price and add to history
            price_data = self.api.get_last_traded_price(pair)
            last_price = float(price_data)
            if last_price <= 0:
                return None, last_price, 0, "Invalid price"

            self._add_price_point(pair, last_price)
            history = self._price_history.get(pair, [])
            history_len = len(history)
            
            if history_len < min_candles:
                return None, last_price, history_len, f"Not enough candles ({history_len}/{min_candles})"
                
            rsi_value = self._calculate_rsi(history, period=period)
            if rsi_value is None:
                return None, last_price, history_len, "RSI calculation failed"
            
            return rsi_value, last_price, history_len, ""
        except Exception as e:
            return None, last_price, history_len, str(e)

    def scan_pair(self, pair: str) -> Tuple[bool, Optional[float]]:
        if self._is_in_cooldown(pair):
            self.logger.debug(f"Pair {pair} is in cooldown, skipping scan")
            return False, None

        rsi_value, last_price, history_len, error_msg = self.get_rsi(pair)
        
        is_oversold = False
        if rsi_value is not None:
            self.last_scan_times[pair] = datetime.now()
            is_oversold = rsi_value < self.config.RSI_THRESHOLD
            action = "BUY_SIGNAL" if is_oversold else "NO_SIGNAL"
            self.valr_logger.log_rsi_scan(pair, rsi_value, self.config.RSI_THRESHOLD, action)

        # Detailed logging for debugging RSI triggers
        price_display = f"R{last_price:,.2f}" if last_price is not None else "Unknown"
        rsi_display = f"{rsi_value:.1f}" if rsi_value is not None else "None"
        status_display = "YES" if is_oversold else "NO"

        log_msg = f"{pair}: Price={price_display} | Candles={history_len} | RSI={rsi_display} | Oversold={status_display}"
        
        if not is_oversold:
            if rsi_value is not None:
                log_msg += f" ({rsi_display} >= {self.config.RSI_THRESHOLD})"
            else:
                log_msg += f" ({error_msg})"
        
        self.logger.info(log_msg)

        return is_oversold, rsi_value

    def scan_pairs(self, pairs: Optional[List[str]] = None) -> List[Dict]:
        if pairs is None:
            pairs = self.config.TRADING_PAIRS

        self.logger.info(f"Scanning {len(pairs)} pairs for oversold conditions (Threshold: {self.config.RSI_THRESHOLD})")

        results: List[Dict] = []
        for pair in pairs:
            try:
                is_oversold, rsi_value = self.scan_pair(pair)
                results.append(
                    {
                        "pair": pair,
                        "rsi_value": rsi_value,
                        "is_oversold": is_oversold,
                        "threshold": self.config.RSI_THRESHOLD,
                        "timestamp": datetime.now().isoformat(),
                    }
                )
                time.sleep(0.05)
            except Exception as e:
                self.logger.error(f"Failed to scan pair {pair}: {e}")
                results.append(
                    {
                        "pair": pair,
                        "rsi_value": None,
                        "is_oversold": False,
                        "error": str(e),
                        "timestamp": datetime.now().isoformat(),
                    }
                )

        oversold_count = sum(1 for result in results if result.get("is_oversold", False))
        self.logger.info(f"RSI scan complete: {oversold_count}/{len(pairs)} pairs oversold")

        return results

    def _extract_levels(self, order_book: Dict, key: str) -> List[Dict]:
        for k in [key, key.capitalize(), key.upper()]:
            levels = order_book.get(k)
            if isinstance(levels, list):
                return [lvl for lvl in levels if isinstance(lvl, dict)]
        return []

    def find_best_entry(self, pair: str) -> Optional[Dict]:
        try:
            order_book = self.api.get_order_book(pair)
            asks = self._extract_levels(order_book, "asks")
            bids = self._extract_levels(order_book, "bids")

            if not asks and not bids:
                self.logger.warning(f"No order book levels available for {pair}")
                return None

            best_ask_price = float(asks[0]["price"]) if asks else None
            best_bid_price = float(bids[0]["price"]) if bids else None

            if best_bid_price is not None:
                recommended_entry = best_bid_price
            elif best_ask_price is not None:
                recommended_entry = best_ask_price * 0.999
            else:
                return None

            trade_amount_quote = self.config.BASE_TRADE_AMOUNT
            quantity = trade_amount_quote / DecimalUtils.to_decimal(recommended_entry)

            tick_size = self.config.get_pair_tick_size(pair)
            qty_decimals = self.config.get_pair_quantity_decimals(pair)

            formatted_quantity = DecimalUtils.format_quantity(quantity, qty_decimals)
            formatted_price = DecimalUtils.format_price(recommended_entry, tick_size)

            return {
                "pair": pair,
                "best_bid": best_bid_price,
                "best_ask": best_ask_price,
                "recommended_entry": float(formatted_price),
                "formatted_quantity": formatted_quantity,
                "formatted_price": formatted_price,
            }

        except Exception as e:
            self.logger.error(f"Failed to analyze entry for {pair}: {e}")
            return None

    def _is_in_cooldown(self, pair: str) -> bool:
        if self.scan_cooldown_seconds <= 0:
            return False
        last_scan = self.last_scan_times.get(pair)
        if not last_scan:
            return False
        return (datetime.now() - last_scan).total_seconds() < self.scan_cooldown_seconds

    def get_scan_statistics(self) -> Dict:
        now = datetime.now()
        scan_ages = {pair: (now - ts).total_seconds() for pair, ts in self.last_scan_times.items()}

        return {
            "total_pairs_scanned": len(self.last_scan_times),
            "pairs_in_cooldown": sum(1 for age in scan_ages.values() if age < self.scan_cooldown_seconds),
            "scan_cooldown_seconds": self.scan_cooldown_seconds,
            "last_scan_times": {pair: ts.isoformat() for pair, ts in self.last_scan_times.items()},
            "scan_ages_seconds": scan_ages,
            "price_history_lengths": {pair: len(hist) for pair, hist in self._price_history.items()},
        }

    def reset_cooldowns(self) -> None:
        self.last_scan_times.clear()
        self.logger.info("Reset all RSI scan cooldowns")
