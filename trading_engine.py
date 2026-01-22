"""Trading engine for VALR trading bot.

Handles order placement, scalp-specific order management, and risk management.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import time

from valr_api import VALRAPI, VALRAPIError
from config import Config
from logging_setup import get_logger, get_valr_logger
from decimal_utils import DecimalUtils
from order_persistence import get_order_persistence
from position_persistence import get_position_persistence
from position_recovery import recover_positions_from_valr


class TradingError(Exception):
    """Raised when trading operations fail."""


class InsufficientBalanceError(TradingError):
    """Raised when account balance is insufficient for trading."""


def _normalize_status(value: Optional[str]) -> str:
    if not value:
        return ""
    return str(value).strip().upper()


def _status_is_filled(status: str) -> bool:
    return any(token in status for token in ["FILLED", "COMPLETE", "COMPLETED", "DONE"])


def _status_is_cancelled(status: str) -> bool:
    return any(token in status for token in ["CANCELLED", "CANCELED", "REJECTED", "EXPIRED"])


class PositionManager:
    """Manages trading positions and their lifecycle."""

    def __init__(self, api: VALRAPI, config: Config):
        self.api = api
        self.config = config
        self.logger = get_logger("position_manager")
        self.valr_logger = get_valr_logger()
        self.position_persistence = get_position_persistence()
        self.active_positions: Dict[str, Dict[str, Any]] = {}

        # Load existing positions on startup
        self._load_positions()

    def create_position(
        self,
        pair: str,
        quantity: Decimal,
        entry_price: Decimal,
        entry_order_id: str,
        stop_loss_price: Decimal,
        take_profit_price: Decimal,
        entry_filled_at: datetime,
    ) -> str:
        position_id = f"{pair}_{int(time.time())}"

        position: Dict[str, Any] = {
            "id": position_id,
            "pair": pair,
            "quantity": quantity,
            "entry_price": entry_price,
            "stop_loss_price": stop_loss_price,
            "take_profit_price": take_profit_price,
            "created_at": datetime.now(timezone.utc),
            "entry_filled_at": entry_filled_at,
            "status": "open",
            "entry_order_id": entry_order_id,
            "take_profit_order_id": None,
            "stop_loss_order_id": None,
        }

        self.active_positions[position_id] = position
        self._save_positions()

        self.valr_logger.log_position_update(
            pair=pair,
            position_type="opened",
            quantity=float(quantity),
            entry_price=float(entry_price),
            current_price=float(entry_price),
            pnl=0.0,
        )
        return position_id

    def _load_positions(self) -> None:
        """Load positions from persistence on startup."""
        loaded_positions = self.position_persistence.load_positions()
        if loaded_positions:
            self.active_positions = loaded_positions
            self.logger.info(f"Restored {len(loaded_positions)} positions from persistence")
        else:
            # No persisted positions - try to recover from VALR API
            self.logger.info("No persisted positions found. Attempting recovery from VALR API...")
            recovered = recover_positions_from_valr(self.api)
            if recovered:
                for position in recovered:
                    self.active_positions[position["id"]] = position
                self._save_positions()
                self.logger.info(f"Recovered and saved {len(recovered)} positions from VALR")

    def _save_positions(self) -> None:
        """Save positions to persistence."""
        self.position_persistence.save_positions(self.active_positions)

    def attach_exit_orders(self, position_id: str, tp_order_id: Optional[str], sl_order_id: str) -> None:
        position = self.active_positions.get(position_id)
        if not position:
            return
        position["take_profit_order_id"] = tp_order_id  # Can be None now
        position["stop_loss_order_id"] = sl_order_id
        self._save_positions()

    def close_position(self, position_id: str, reason: str, exit_price: Optional[Decimal] = None) -> Optional[Decimal]:
        """Close position and return PnL."""
        position = self.active_positions.get(position_id)
        if not position:
            return None

        # Calculate PnL
        pnl = None
        if exit_price:
            entry_price = position["entry_price"]
            quantity = position["quantity"]
            # PnL = (exit_price - entry_price) * quantity
            pnl = (exit_price - entry_price) * quantity

        position["status"] = "closed"
        position["closed_at"] = datetime.now(timezone.utc)
        position["close_reason"] = reason
        if exit_price:
            position["exit_price"] = exit_price
        if pnl:
            position["pnl"] = pnl

        self.valr_logger.log_position_update(
            pair=position["pair"],
            position_type="closed",
            quantity=float(position["quantity"]),
            entry_price=float(position["entry_price"]),
            pnl=float(pnl) if pnl else 0.0,
        )

        del self.active_positions[position_id]
        self.position_persistence.delete_position(position_id)

        return pnl

    def get_open_positions(self) -> List[Dict[str, Any]]:
        return [pos for pos in self.active_positions.values() if pos.get("status") == "open"]

    def check_take_profit_opportunities(self) -> List[str]:
        """Check all active positions and close those that reached take-profit target.

        Returns list of position IDs that were closed.

        This replaces the removed TP limit orders by actively monitoring positions
        and executing market sells when profit target is reached.
        """
        closed_positions = []

        for position_id, position in list(self.active_positions.items()):
            if position.get("status") != "open":
                continue

            pair = position.get("pair")
            entry_price = position.get("entry_price")
            tp_price = position.get("take_profit_price")
            quantity = position.get("quantity")

            if not all([pair, entry_price, tp_price, quantity]):
                continue

            try:
                # Get current market price
                order_book = self.api.get_order_book(pair)
                bids = order_book.get("bids") or order_book.get("Bids") or []

                if not bids:
                    continue

                current_bid = Decimal(str(bids[0]["price"]))

                # Check if current price >= take-profit target
                if current_bid >= tp_price:
                    self.logger.info(
                        f"Take-profit target reached for {pair}: "
                        f"current={current_bid}, target={tp_price}, entry={entry_price}"
                    )

                    # Close position with market order
                    try:
                        qty_decimals = self.config.get_pair_quantity_decimals(pair)
                        formatted_qty = DecimalUtils.format_quantity(quantity, qty_decimals)

                        self.api.place_market_order(
                            pair=pair,
                            side="SELL",
                            quantity=formatted_qty
                        )

                        # Cancel stop-loss order if it exists
                        sl_order_id = position.get("stop_loss_order_id")
                        if sl_order_id:
                            try:
                                self.api.cancel_order(sl_order_id, pair=pair)
                            except Exception as cancel_error:
                                self.logger.warning(f"Failed to cancel SL order {sl_order_id}: {cancel_error}")

                        # Update position status
                        position["status"] = "closed"
                        position["exit_filled_at"] = datetime.now(timezone.utc)
                        position["exit_reason"] = "take_profit_reached"

                        closed_positions.append(position_id)

                        self.logger.info(f"Successfully closed position {position_id} at take-profit")

                    except Exception as close_error:
                        self.logger.error(f"Failed to close position {position_id} at take-profit: {close_error}")

            except Exception as e:
                self.logger.error(f"Error checking take-profit for position {position_id}: {e}")
                continue

        if closed_positions:
            self._save_positions()

        return closed_positions


class VALRTradingEngine:
    """Main trading engine for VALR exchange."""

    def __init__(self, api: VALRAPI, config: Config):
        self.api = api
        self.config = config
        self.logger = get_logger("trading_engine")
        self.valr_logger = get_valr_logger()

        self.position_manager = PositionManager(api, config)
        self.order_persistence = get_order_persistence()

        self.trades_today = 0
        self.last_trade_date = datetime.now(timezone.utc).date()
        self.daily_pnl = Decimal("0")

        # Win/loss tracking
        self.wins_today = 0
        self.losses_today = 0

        # Reference to parent bot for shutdown detection
        self.bot = None

    def _get_quote_currency(self, pair: str) -> str:
        for quote in ["ZAR", "USDT", "USD"]:
            if pair.endswith(quote):
                return quote
        return "ZAR"

    def get_available_balance(self, currency: str) -> Decimal:
        balances = self.api.get_account_balances()
        return balances.get(currency, Decimal("0"))

    def check_balance(self, currency: str, required_amount: Decimal) -> bool:
        try:
            available = self.get_available_balance(currency)
            sufficient = available >= required_amount
            self.logger.debug(
                f"Balance check for {currency}: available={available}, required={required_amount}, sufficient={sufficient}"
            )
            return sufficient
        except Exception as e:
            self.logger.error(f"Failed to check balance for {currency}: {e}")
            return False

    def _extract_order_status(self, order_data: Dict[str, Any]) -> str:
        return _normalize_status(
            order_data.get("status")
            or order_data.get("state")
            or order_data.get("orderStatusType")
            or order_data.get("orderStatus")
        )

    def _extract_filled_quantity(self, order_data: Dict[str, Any]) -> Decimal:
        candidates = [
            "filledQuantity",
            "quantityFilled",
            "baseFilled",
            "baseAmountFilled",
            "executedQuantity",
            "filledBaseAmount",
        ]
        for key in candidates:
            if key in order_data and order_data[key] is not None:
                try:
                    return Decimal(str(order_data[key]))
                except Exception:
                    continue
        return Decimal("0")

    def _extract_order_price(self, order_data: Dict[str, Any]) -> Optional[Decimal]:
        for key in ["price", "limitPrice", "orderPrice"]:
            if key in order_data and order_data[key] is not None:
                try:
                    return Decimal(str(order_data[key]))
                except Exception:
                    continue
        return None

    def _extract_avg_fill_price(self, order_data: Dict[str, Any]) -> Optional[Decimal]:
        for key in ["averagePrice", "avgPrice", "price"]:
            if key in order_data and order_data[key] is not None:
                try:
                    return Decimal(str(order_data[key]))
                except Exception:
                    continue
        return None

    def _fetch_fill_details(self, order_id: str) -> Tuple[Decimal, Optional[Decimal]]:
        try:
            fills = self.api.get_order_fills(order_id)
            total_qty = Decimal("0")
            total_cost = Decimal("0")
            for fill in fills:
                qty = None
                price = None
                for q_key in ["quantity", "filledQuantity", "baseAmount", "baseAmountFilled"]:
                    if q_key in fill:
                        try:
                            qty = Decimal(str(fill[q_key]))
                            break
                        except Exception:
                            continue
                for p_key in ["price", "fillPrice"]:
                    if p_key in fill:
                        try:
                            price = Decimal(str(fill[p_key]))
                            break
                        except Exception:
                            continue
                if qty is None or price is None:
                    continue

                total_qty += qty
                total_cost += qty * price

            avg_price = (total_cost / total_qty) if total_qty > 0 else None
            return total_qty, avg_price
        except Exception:
            return Decimal("0"), None

    def _wait_for_order_fill(self, order_id: str, pair: str, timeout_seconds: int) -> Tuple[str, Decimal, Optional[Decimal]]:
        """Wait for order to fill with exponential backoff polling to reduce API calls.

        Polling strategy:
        - First 10s: Poll every 0.5s (20 calls)
        - Next 20s: Poll every 1s (20 calls)
        - Last 30s: Poll every 2s (15 calls)
        - Total: ~55 API calls (more responsive to shutdown)
        """
        start = time.time()
        last_status = ""
        original_qty = Decimal("0")
        original_price = Decimal("0")

        while True:
            # Check if bot is shutting down
            if self.bot and hasattr(self.bot, 'running') and not self.bot.running:
                self.logger.info(f"Shutdown detected during order wait. Cancelling order {order_id}...")
                return "SHUTDOWN", Decimal("0"), None

            elapsed = time.time() - start

            # Check order status
            order_data = self.api.get_order_status(order_id, pair=pair)
            status = self._extract_order_status(order_data)
            last_status = status or last_status

            # Get original order details for fallback
            if original_qty == 0:
                orig_qty_raw = order_data.get("originalQuantity") or order_data.get("quantity")
                if orig_qty_raw:
                    try:
                        original_qty = Decimal(str(orig_qty_raw))
                    except:
                        pass

            if original_price == 0:
                orig_price_raw = order_data.get("originalPrice") or order_data.get("price")
                if orig_price_raw:
                    try:
                        original_price = Decimal(str(orig_price_raw))
                    except:
                        pass

            filled_qty = self._extract_filled_quantity(order_data)
            avg_fill_price = self._extract_avg_fill_price(order_data)

            if _status_is_filled(status):
                # If order is marked FILLED but we can't extract quantity, use original order quantity
                if filled_qty == 0 and original_qty > 0:
                    self.logger.warning(f"Order {order_id} marked FILLED but qty extraction failed. Using original qty={original_qty}")
                    filled_qty = original_qty
                if avg_fill_price is None and original_price > 0:
                    avg_fill_price = original_price
                return "FILLED", filled_qty, avg_fill_price

            if _status_is_cancelled(status):
                return "CANCELLED", filled_qty, avg_fill_price

            if elapsed >= timeout_seconds:
                if filled_qty > 0:
                    return "PARTIALLY_FILLED", filled_qty, avg_fill_price
                return "TIMEOUT", filled_qty, avg_fill_price

            # Exponential backoff: faster polling initially, slower as time passes
            # Use shorter sleeps to be more responsive to shutdown signals
            if elapsed < 10:
                time.sleep(0.5)  # First 10s: check every 0.5s (was 1s)
            elif elapsed < 30:
                time.sleep(1.0)  # Next 20s: check every 1s (was 2s)
            else:
                time.sleep(2.0)  # Last 30s: check every 2s (was 5s)

    def _get_best_bid_ask(self, pair: str) -> Tuple[Optional[Decimal], Optional[Decimal]]:
        book = self.api.get_order_book(pair)
        bids = book.get("bids") or book.get("Bids") or []
        asks = book.get("asks") or book.get("Asks") or []

        best_bid = None
        best_ask = None

        if isinstance(bids, list) and bids:
            try:
                best_bid = Decimal(str(bids[0]["price"]))
            except Exception:
                best_bid = None
        if isinstance(asks, list) and asks:
            try:
                best_ask = Decimal(str(asks[0]["price"]))
            except Exception:
                best_ask = None

        return best_bid, best_ask

    def execute_trade_setup(self, pair: str, rsi_value: float) -> Optional[str]:
        """Execute scalp trade setup with R30 position sizing.

        For high-frequency scalp trading:
        1. Check ZAR balance (R30 + fees required)
        2. Place market order for immediate guaranteed fill (taker fees)
        3. Wait for fill confirmation (2s timeout)
        4. If filled, place stop-loss order at -2.5%
        5. Monitor position for manual take-profit at +1.5%
        6. SL protects downside, manual exit captures upside

        Note: Only SL order placed due to VALR limitation (can't have both TP+SL on same balance)
        """
        try:
            if self._is_daily_limit_reached():
                self.logger.warning(f"Daily trade limit reached, skipping {pair}")
                return None

            quote_currency = self._get_quote_currency(pair)

            best_bid, best_ask = self._get_best_bid_ask(pair)
            if best_bid is None and best_ask is None:
                self.logger.warning(f"No order book available for {pair}")
                return None

            # For scalping: use market orders for guaranteed immediate fill
            # Market orders execute at best available price (typically within 1 tick of ask)
            entry_price = best_ask if best_ask is not None else best_bid
            if entry_price is None or entry_price <= 0:
                return None

            # Calculate R30 position sizing (estimate for validation only, market order will use base_amount)
            trade_amount_quote = self.config.BASE_TRADE_AMOUNT

            qty_decimals = self.config.get_pair_quantity_decimals(pair)

            # Check balance: R30 + taker fee (from config) + safety buffer
            # Market orders use VALR taker fee (0.35% based on config)
            BALANCE_SAFETY_BUFFER = Decimal("0.05")  # 5 cents safety margin
            required_quote = trade_amount_quote + (trade_amount_quote * (self.config.TAKER_FEE_PERCENT / Decimal("100"))) + BALANCE_SAFETY_BUFFER

            if not self.check_balance(quote_currency, required_quote):
                available = self.get_available_balance(quote_currency)
                self.logger.debug(
                    f"Balance check failed: required={required_quote} (includes {BALANCE_SAFETY_BUFFER} buffer), "
                    f"available={available}, shortfall={required_quote - available}"
                )
                raise InsufficientBalanceError(
                    f"Insufficient {quote_currency}. Required ~{required_quote}, available={available}"
                )

            self.logger.info(
                f"Oversold signal {pair}: RSI={rsi_value:.2f}. Placing R{trade_amount_quote} entry (market order)"
            )

            # Use market order for guaranteed immediate fill
            # Accepts current best ask (market price) automatically
            # Higher fee (0.35% taker) but eliminates timeout issues
            entry_order_result = self.api.place_market_order(
                pair=pair,
                side="BUY",
                base_amount=str(trade_amount_quote),  # R30 in quote currency
            )

            # CRITICAL: Wait 1 second after order placement to avoid 404 errors when checking status
            time.sleep(1.0)

            entry_order_id = str(entry_order_result.get("id") or entry_order_result.get("orderId") or "")
            if not entry_order_id:
                self.logger.error(f"Entry order placement succeeded but no order id returned: {entry_order_result}")
                return None

            self.order_persistence.add_order(
                order_id=entry_order_id,
                pair=pair,
                side="buy",
                quantity=Decimal(str(trade_amount_quote)),  # Market order uses base_amount
                entry_price=entry_price,  # Estimated price
                order_type="entry",
            )

            self.valr_logger.log_order_event(
                event_type="ENTRY_PLACED",
                order_id=entry_order_id,
                pair=pair,
                side="buy",
                quantity=float(trade_amount_quote),
                price=float(entry_price),
                status="PENDING",
            )

            # Market orders fill instantly, check after 2 seconds for API propagation
            self.logger.info(f"Waiting for market order fill (2s timeout)...")
            fill_state, filled_qty, avg_fill_price = self._wait_for_order_fill(
                entry_order_id, pair=pair, timeout_seconds=2
            )

            # Critical: Handle shutdown signal immediately
            if fill_state == "SHUTDOWN":
                self.logger.info(f"Shutdown signal received. Cancelling entry order {entry_order_id}...")
                try:
                    self.api.cancel_order(entry_order_id, pair=pair)
                except Exception as e:
                    self.logger.error(f"Error cancelling order during shutdown: {e}")
                finally:
                    self.order_persistence.update_order_status(entry_order_id, "cancelled")
                return None

            # Critical: Only proceed if order is actually FILLED
            if fill_state != "FILLED":
                self.logger.warning(f"Entry order not filled ({fill_state}). Cancelling {entry_order_id}...")
                try:
                    self.api.cancel_order(entry_order_id, pair=pair)
                finally:
                    self.order_persistence.update_order_status(entry_order_id, "cancelled")
                return None

            self.order_persistence.update_order_status(entry_order_id, "filled")
            effective_entry_price = avg_fill_price or Decimal(formatted_price)

            # SIMPLE: Wait 5 seconds for settlement, then check actual wallet balance
            self.logger.info(f"Entry order filled. Waiting 5s for settlement...")
            time.sleep(5.0)

            # Check actual wallet balance to get exact filled quantity
            base_currency = pair.replace("ZAR", "")
            actual_balance = self.get_available_balance(base_currency)

            if actual_balance <= 0:
                self.logger.error(f"No {base_currency} balance after order fill. Order may not have filled.")
                return None

            self.logger.info(f"Balance confirmed: {base_currency}={actual_balance}. Placing TP/SL...")

            # Use actual balance as quantity for TP/SL orders
            filled_qty = actual_balance
            formatted_filled_qty = DecimalUtils.format_quantity(filled_qty, qty_decimals)

            # Calculate TP/SL prices
            tp_price = DecimalUtils.calculate_take_profit_price(
                effective_entry_price, self.config.TAKE_PROFIT_PERCENTAGE
            )
            sl_price = DecimalUtils.calculate_stop_loss_price(
                effective_entry_price, self.config.STOP_LOSS_PERCENTAGE
            )

            tick_size = self.config.get_pair_tick_size(pair)
            formatted_tp = DecimalUtils.format_price(tp_price, tick_size)
            formatted_sl = DecimalUtils.format_price(sl_price, tick_size)

            # Place only Stop-Loss order to protect against downside
            # Take-profit will be handled manually via position monitoring
            # This avoids VALR's limitation of not supporting multiple sell orders on same balance
            sl_order_id = ""
            try:
                # Place stop-loss order to protect against 2.5% downside
                sl_order = self.api.place_limit_order(
                    pair=pair,
                    side="SELL",
                    quantity=formatted_filled_qty,
                    price=formatted_sl,
                    post_only=False,
                )

                time.sleep(1.0)

                sl_order_id = str(sl_order.get("id") or sl_order.get("orderId") or "")

                if not sl_order_id:
                    raise TradingError("SL order placement returned no order ID")

                # Verify order was accepted
                sl_status_check = self.api.get_order_status(sl_order_id, pair=pair)
                sl_status_type = sl_status_check.get("orderStatusType", "")
                if sl_status_type == "Failed":
                    fail_reason = sl_status_check.get("failedReason", "Unknown")
                    raise TradingError(f"SL order failed: {fail_reason}")

            except Exception as e:
                self.logger.error(f"CRITICAL: Failed to place SL order for {pair}: {e}. Closing position immediately.")
                # Close position at market - cannot hold unprotected position
                try:
                    self.api.place_market_order(pair=pair, side="SELL", quantity=formatted_filled_qty)
                    self.order_persistence.update_order_status(entry_order_id, "closed")
                except Exception as close_error:
                    self.logger.error(f"CRITICAL: Failed to close unprotected position for {pair}: {close_error}")
                return None

            # Record stop-loss order
            if sl_order_id:
                self.order_persistence.add_order(
                    order_id=sl_order_id,
                    pair=pair,
                    side="sell",
                    quantity=Decimal(formatted_filled_qty),
                    entry_price=Decimal(formatted_sl),
                    order_type="stop_loss",
                )

            position_id = self.position_manager.create_position(
                pair=pair,
                quantity=Decimal(formatted_filled_qty),
                entry_price=effective_entry_price,
                entry_order_id=entry_order_id,
                stop_loss_price=Decimal(formatted_sl),
                take_profit_price=Decimal(formatted_tp),  # Still calculate TP for monitoring, just don't place order
                entry_filled_at=datetime.now(timezone.utc),
            )
            # Attach only stop-loss order (no TP order placed)
            if sl_order_id:
                self.position_manager.attach_exit_orders(position_id, None, sl_order_id)

            self._increment_trade_count()

            self.logger.info(f"Position active for {pair}: SL={formatted_sl} (TP monitoring active @ {formatted_tp})")
            return entry_order_id

        except InsufficientBalanceError as e:
            self.logger.warning(str(e))
            return None
        except VALRAPIError as e:
            self.logger.error(f"API error executing trade setup for {pair}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error executing trade setup for {pair}: {e}")
            return None

    def _cancel_if_open(self, order_id: Optional[str], pair: Optional[str] = None, max_retries: int = 3) -> bool:
        """Cancel an order if it's still open.

        Returns:
            True if order was cancelled or already filled/cancelled, False if cancellation failed
        """
        if not order_id:
            return True

        for attempt in range(max_retries):
            try:
                # Check current status first
                status_data = self.api.get_order_status(order_id, pair=pair) if pair else self.api.get_order_status(order_id)
                status = self._extract_order_status(status_data)

                # If already filled or cancelled, no need to cancel
                if _status_is_filled(status) or _status_is_cancelled(status):
                    return True

                # Attempt cancellation
                if pair:
                    self.api.cancel_order(order_id, pair=pair)
                else:
                    self.api.cancel_order(order_id)

                self.logger.debug(f"Successfully cancelled order {order_id}")
                return True

            except VALRAPIError as e:
                # Log specific API errors
                if attempt < max_retries - 1:
                    self.logger.warning(f"Failed to cancel order {order_id} (attempt {attempt + 1}/{max_retries}): {e}. Retrying...")
                    time.sleep(0.5 * (2 ** attempt))  # Exponential backoff: 0.5s, 1s, 2s
                else:
                    self.logger.error(f"CRITICAL: Failed to cancel order {order_id} after {max_retries} attempts: {e}")
                    return False

            except Exception as e:
                # Log unexpected errors
                if attempt < max_retries - 1:
                    self.logger.warning(f"Unexpected error cancelling order {order_id} (attempt {attempt + 1}/{max_retries}): {e}. Retrying...")
                    time.sleep(0.5 * (2 ** attempt))
                else:
                    self.logger.error(f"CRITICAL: Unexpected error cancelling order {order_id} after {max_retries} attempts: {e}")
                    return False

        return False

    def _sync_persisted_order_status(self, order_id: str, pair: Optional[str] = None) -> None:
        try:
            status_data = self.api.get_order_status(order_id, pair=pair) if pair else self.api.get_order_status(order_id)
            status = self._extract_order_status(status_data)
            if _status_is_filled(status):
                self.order_persistence.update_order_status(order_id, "filled")
            elif _status_is_cancelled(status):
                self.order_persistence.update_order_status(order_id, "cancelled")
        except Exception:
            return

    def _close_position_at_market(self, position: Dict[str, Any], reason: str) -> None:
        pair = position["pair"]
        position_id = position["id"]

        tp_id = position.get("take_profit_order_id")
        sl_id = position.get("stop_loss_order_id")
        self._cancel_if_open(tp_id, pair=pair)
        self._cancel_if_open(sl_id, pair=pair)
        if tp_id:
            self._sync_persisted_order_status(tp_id, pair=pair)
        if sl_id:
            self._sync_persisted_order_status(sl_id, pair=pair)

        qty_decimals = self.config.get_pair_quantity_decimals(pair)
        formatted_qty = DecimalUtils.format_quantity(position["quantity"], qty_decimals)

        try:
            self.api.place_market_order(pair=pair, side="SELL", quantity=formatted_qty)
            self.logger.info(f"Closed {pair} position at market (qty={formatted_qty}) due to {reason}")
        except Exception:
            best_bid, _ = self._get_best_bid_ask(pair)
            if best_bid is None:
                self.logger.warning(f"Could not close {pair} position due to missing market data")
                self.position_manager.close_position(position_id, reason)
                return

            tick_size = self.config.get_pair_tick_size(pair)
            aggressive_price = DecimalUtils.format_price(best_bid, tick_size)
            try:
                self.api.place_limit_order(
                    pair=pair,
                    side="SELL",
                    quantity=formatted_qty,
                    price=aggressive_price,
                    post_only=False,
                )
                self.logger.info(
                    f"Closed {pair} position with aggressive limit sell @ {aggressive_price} (qty={formatted_qty}) due to {reason}"
                )
            except Exception as e:
                self.logger.error(f"Failed to close {pair} position (reason={reason}): {e}")

        self.position_manager.close_position(position_id, reason)

    def monitor_positions(self) -> None:
        open_positions = self.position_manager.get_open_positions()
        if not open_positions:
            return

        for position in open_positions:
            self._monitor_single_position(position)

    def _monitor_single_position(self, position: Dict[str, Any]) -> None:
        """Monitor position for scalp trading with proper timeouts.

        For scalp trading, positions should be closed quickly:
        - Position timeout: 30 minutes maximum
        - Exit order timeout: 10 minutes (TP/SL must fill or position closed)

        CRITICAL FIX: Fetch both TP and SL statuses atomically before taking action
        to prevent race condition where both orders fill simultaneously.
        """
        pair = position["pair"]
        position_id = position["id"]

        entry_filled_at: datetime = position.get("entry_filled_at") or position.get("created_at")

        # Scalp trading: close position after 30 minutes maximum
        if datetime.now(timezone.utc) > entry_filled_at + timedelta(minutes=self.config.POSITION_TIMEOUT_MINUTES):
            self.logger.warning(f"Position timeout for {pair} (30min max). Closing at market...")
            self._close_position_at_market(position, reason="position_timeout")
            return

        # Exit orders must fill within 10 minutes or close position
        if datetime.now(timezone.utc) > entry_filled_at + timedelta(minutes=self.config.EXIT_ORDER_TIMEOUT_MINUTES):
            self.logger.warning(f"Exit orders timeout for {pair} (10min max). Closing position...")
            self._close_position_at_market(position, reason="exit_orders_timeout")
            return

        tp_id = position.get("take_profit_order_id")
        sl_id = position.get("stop_loss_order_id")

        # CRITICAL: Check if TP/SL orders still exist on exchange
        # If orders are missing from VALR (filled or cancelled), close the position
        if tp_id or sl_id:
            # Get all open orders from VALR to verify TP/SL still exist
            try:
                open_orders = self.api.get_open_orders(pair=pair)
                open_order_ids = {str(order.get("orderId") or order.get("id") or "") for order in open_orders}

                tp_exists = tp_id in open_order_ids if tp_id else False
                sl_exists = sl_id in open_order_ids if sl_id else False

                # If NEITHER TP nor SL exist on exchange, position was exited but coins may still be in wallet
                # We need to close position at market to sell the coins
                if not tp_exists and not sl_exists:
                    self.logger.warning(
                        f"Position {pair} has no TP/SL orders on VALR. Orders were filled or cancelled. "
                        f"Selling coins at market price (TP={tp_id}, SL={sl_id})"
                    )
                    self._close_position_at_market(position, reason="orders_not_found_on_exchange")
                    return

                # If only ONE order is missing, one exit order was filled - position was sold
                # Cancel the remaining order and close position tracking (coins already sold)
                if not tp_exists and sl_exists:
                    self.logger.info(f"TP order {tp_id} not found on VALR for {pair}. Likely filled. Cancelling SL...")
                    self._cancel_if_open(sl_id, pair=pair)
                    if sl_id:
                        self.order_persistence.update_order_status(sl_id, "cancelled")
                    # Position already sold via TP, just close tracking
                    self.position_manager.close_position(position_id, "take_profit")
                    return

                if not sl_exists and tp_exists:
                    self.logger.info(f"SL order {sl_id} not found on VALR for {pair}. Likely filled. Cancelling TP...")
                    self._cancel_if_open(tp_id, pair=pair)
                    if tp_id:
                        self.order_persistence.update_order_status(tp_id, "cancelled")
                    # Position already sold via SL, just close tracking
                    self.position_manager.close_position(position_id, "stop_loss")
                    return

            except Exception as e:
                self.logger.error(f"Failed to check if TP/SL orders exist for {pair}: {e}")
                # Continue with normal flow if check fails

        # CRITICAL: Fetch BOTH order statuses before taking any action (prevents race condition)
        tp_status = None
        sl_status = None

        if tp_id:
            try:
                tp_data = self.api.get_order_status(tp_id, pair=pair)
                tp_status = self._extract_order_status(tp_data)
            except Exception:
                tp_status = None

        if sl_id:
            try:
                sl_data = self.api.get_order_status(sl_id, pair=pair)
                sl_status = self._extract_order_status(sl_data)
            except Exception:
                sl_status = None

        # Check if both statuses are filled (race condition detected)
        tp_filled = tp_status and _status_is_filled(tp_status)
        sl_filled = sl_status and _status_is_filled(sl_status)

        if tp_filled and sl_filled:
            # CRITICAL: Both orders filled simultaneously - this should not happen but handle gracefully
            self.logger.error(
                f"RACE CONDITION DETECTED: Both TP and SL filled for {pair}. "
                f"TP: {tp_id}, SL: {sl_id}. Closing position immediately."
            )
            if tp_id:
                self.order_persistence.update_order_status(tp_id, "filled")
            if sl_id:
                self.order_persistence.update_order_status(sl_id, "filled")
            self.position_manager.close_position(position_id, "both_orders_filled")
            return

        # Normal flow: exactly one order filled
        if tp_filled:
            self.logger.info(f"Take profit filled for {pair}. Cancelling stop loss...")
            if tp_id:
                self.order_persistence.update_order_status(tp_id, "filled")
            self._cancel_if_open(sl_id)
            if sl_id:
                self.order_persistence.update_order_status(sl_id, "cancelled")

            # Calculate PnL for TP exit
            tp_price = position.get("take_profit_price")
            pnl = self.position_manager.close_position(position_id, "take_profit", tp_price)

            # Track as win
            if pnl and pnl > 0:
                self.wins_today += 1
                self.daily_pnl += pnl
                self.logger.info(f"WIN: {pair} closed at TP. PnL: +R{pnl:.2f}")
            return

        if sl_filled:
            self.logger.info(f"Stop loss filled for {pair}. Cancelling take profit...")
            if sl_id:
                self.order_persistence.update_order_status(sl_id, "filled")
            self._cancel_if_open(tp_id)
            if tp_id:
                self.order_persistence.update_order_status(tp_id, "cancelled")

            # Calculate PnL for SL exit
            sl_price = position.get("stop_loss_price")
            pnl = self.position_manager.close_position(position_id, "stop_loss", sl_price)

            # Track as loss
            if pnl and pnl < 0:
                self.losses_today += 1
                self.daily_pnl += pnl
                self.logger.info(f"LOSS: {pair} closed at SL. PnL: R{pnl:.2f}")
            return

    def _is_daily_limit_reached(self) -> bool:
        current_date = datetime.now(timezone.utc).date()
        if current_date != self.last_trade_date:
            self.trades_today = 0
            self.wins_today = 0
            self.losses_today = 0
            self.daily_pnl = Decimal("0")
            self.last_trade_date = current_date
        return self.trades_today >= self.config.MAX_DAILY_TRADES

    def _increment_trade_count(self) -> None:
        self.trades_today += 1
        self.logger.debug(f"Trade count today: {self.trades_today}/{self.config.MAX_DAILY_TRADES}")

    def get_trading_statistics(self) -> Dict:
        open_positions = self.position_manager.get_open_positions()
        total_closed = self.wins_today + self.losses_today
        win_rate = (self.wins_today / total_closed * 100) if total_closed > 0 else 0.0

        return {
            "trades_today": self.trades_today,
            "max_daily_trades": self.config.MAX_DAILY_TRADES,
            "daily_limit_reached": self._is_daily_limit_reached(),
            "open_positions": len(open_positions),
            "wins_today": self.wins_today,
            "losses_today": self.losses_today,
            "win_rate": f"{win_rate:.1f}%",
            "daily_pnl": f"R{self.daily_pnl:.2f}",
            "last_trade_date": self.last_trade_date.isoformat(),
        }
