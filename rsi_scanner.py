"""RSI scanner for VALR trading bot.

For high-frequency scalping, this module computes RSI locally using a rolling
window of last traded prices.

VALR's indicator endpoints are not consistently available across accounts/API
revisions; using market summary pricing is more reliable.
"""

from __future__ import annotations

from typing import List, Dict, Optional, Tuple
from datetime import datetime
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
        
        Uses VALR's market summary endpoint to get current prices
        and calculates RSI locally for oversold detection.

        Returns:
            Tuple of (rsi_value, last_price, history_len, error_msg)
        """
        last_price = None
        history_len = 0
        try:
            # Get current price for scalp trading entry calculation
            price_data = self.api.get_last_traded_price(pair)
            last_price = float(price_data)
            if last_price <= 0:
                return None, last_price, 0, "Invalid price"

            self._add_price_point(pair, last_price)
            history = self._price_history.get(pair, [])
            history_len = len(history)
            
            if history_len < period + 1:
                return None, last_price, history_len, f"Not enough candles ({history_len}/{period + 1})"
                
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
        status_display = "YES ✅" if is_oversold else "NO ❌"
        
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

            price_decimals = self.config.get_pair_price_decimals(pair)
            qty_decimals = self.config.get_pair_quantity_decimals(pair)

            formatted_quantity = DecimalUtils.format_quantity(quantity, qty_decimals)
            formatted_price = DecimalUtils.format_price(recommended_entry, price_decimals)

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
