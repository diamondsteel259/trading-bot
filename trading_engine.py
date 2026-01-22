"""Trading engine for VALR trading bot.

Handles order placement, scalp-specific order management, and risk management.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from decimal import Decimal
import time

from valr_api import VALRAPI, VALRAPIError
from config import Config
from logging_setup import get_logger, get_valr_logger
from decimal_utils import DecimalUtils
from order_persistence import get_order_persistence


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
        self.active_positions: Dict[str, Dict[str, Any]] = {}

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
            "created_at": datetime.now(),
            "entry_filled_at": entry_filled_at,
            "status": "open",
            "entry_order_id": entry_order_id,
            "take_profit_order_id": None,
            "stop_loss_order_id": None,
        }

        self.active_positions[position_id] = position
        self.valr_logger.log_position_update(
            pair=pair,
            position_type="opened",
            quantity=float(quantity),
            entry_price=float(entry_price),
            current_price=float(entry_price),
            pnl=0.0,
        )
        return position_id

    def attach_exit_orders(self, position_id: str, tp_order_id: str, sl_order_id: str) -> None:
        position = self.active_positions.get(position_id)
        if not position:
            return
        position["take_profit_order_id"] = tp_order_id
        position["stop_loss_order_id"] = sl_order_id

    def close_position(self, position_id: str, reason: str) -> None:
        position = self.active_positions.get(position_id)
        if not position:
            return
        position["status"] = "closed"
        position["closed_at"] = datetime.now()
        position["close_reason"] = reason

        self.valr_logger.log_position_update(
            pair=position["pair"],
            position_type="closed",
            quantity=float(position["quantity"]),
            entry_price=float(position["entry_price"]),
            pnl=0.0,
        )

        del self.active_positions[position_id]

    def get_open_positions(self) -> List[Dict[str, Any]]:
        return [pos for pos in self.active_positions.values() if pos.get("status") == "open"]


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
        self.last_trade_date = datetime.now().date()
        self.daily_pnl = Decimal("0")

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

    def _wait_for_order_fill(self, order_id: str, timeout_seconds: int, poll_seconds: float = 2.0) -> Tuple[str, Decimal, Optional[Decimal]]:
        start = time.time()
        last_status = ""

        while True:
            order_data = self.api.get_order_status(order_id)
            status = self._extract_order_status(order_data)
            last_status = status or last_status

            filled_qty = self._extract_filled_quantity(order_data)
            avg_fill_price = self._extract_avg_fill_price(order_data)

            if _status_is_filled(status):
                if filled_qty == 0:
                    filled_qty, avg_fill_price = self._fetch_fill_details(order_id)
                return "FILLED", filled_qty, avg_fill_price

            if _status_is_cancelled(status):
                return "CANCELLED", filled_qty, avg_fill_price

            if time.time() - start >= timeout_seconds:
                if filled_qty > 0:
                    return "PARTIALLY_FILLED", filled_qty, avg_fill_price
                return "TIMEOUT", filled_qty, avg_fill_price

            time.sleep(poll_seconds)

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
        try:
            if self._is_daily_limit_reached():
                self.logger.warning(f"Daily trade limit reached, skipping {pair}")
                return None

            quote_currency = self._get_quote_currency(pair)

            best_bid, best_ask = self._get_best_bid_ask(pair)
            if best_bid is None and best_ask is None:
                self.logger.warning(f"No order book available for {pair}")
                return None

            entry_price = best_bid if best_bid is not None else best_ask
            if entry_price is None or entry_price <= 0:
                return None

            trade_amount_quote = self.config.BASE_TRADE_AMOUNT
            qty = trade_amount_quote / entry_price

            price_decimals = self.config.get_pair_price_decimals(pair)
            qty_decimals = self.config.get_pair_quantity_decimals(pair)

            formatted_price = DecimalUtils.format_price(entry_price, price_decimals)
            formatted_qty = DecimalUtils.format_quantity(qty, qty_decimals)

            required_quote = trade_amount_quote + (trade_amount_quote * (self.config.MAKER_FEE_PERCENT / Decimal("100")))
            if not self.check_balance(quote_currency, required_quote):
                available = self.get_available_balance(quote_currency)
                raise InsufficientBalanceError(
                    f"Insufficient {quote_currency}. Required ~{required_quote}, available={available}"
                )

            self.logger.info(
                f"Oversold signal {pair}: RSI={rsi_value:.2f}. Placing {quote_currency} {trade_amount_quote} entry @ {formatted_price}"
            )

            entry_order_result = self.api.place_limit_order(
                pair=pair,
                side="BUY",
                quantity=formatted_qty,
                price=formatted_price,
                post_only=True,
            )
            entry_order_id = str(entry_order_result.get("id") or entry_order_result.get("orderId") or "")
            if not entry_order_id:
                self.logger.error(f"Entry order placement succeeded but no order id returned: {entry_order_result}")
                return None

            self.order_persistence.add_order(
                order_id=entry_order_id,
                pair=pair,
                side="buy",
                quantity=Decimal(formatted_qty),
                entry_price=Decimal(formatted_price),
                order_type="entry",
            )

            self.valr_logger.log_order_event(
                event_type="ENTRY_PLACED",
                order_id=entry_order_id,
                pair=pair,
                side="buy",
                quantity=float(Decimal(formatted_qty)),
                price=float(Decimal(formatted_price)),
                status="PENDING",
            )

            self.logger.info(f"Waiting for entry fill ({self.config.ENTRY_ORDER_TIMEOUT_SECONDS}s timeout)...")
            fill_state, filled_qty, avg_fill_price = self._wait_for_order_fill(
                entry_order_id, timeout_seconds=self.config.ENTRY_ORDER_TIMEOUT_SECONDS, poll_seconds=2.0
            )

            if fill_state in ["TIMEOUT", "CANCELLED"]:
                self.logger.info(f"Entry order not filled ({fill_state}). Cancelling {entry_order_id}...")
                try:
                    self.api.cancel_order(entry_order_id)
                finally:
                    self.order_persistence.update_order_status(entry_order_id, "cancelled")
                return None

            if fill_state == "PARTIALLY_FILLED":
                self.logger.info(f"Entry partially filled (qty={filled_qty}). Cancelling remainder...")
                try:
                    self.api.cancel_order(entry_order_id)
                finally:
                    self.order_persistence.update_order_status(entry_order_id, "filled")

            if filled_qty <= 0:
                self.logger.warning(f"Entry order marked {fill_state} but filled qty is {filled_qty}.")
                return None

            self.order_persistence.update_order_status(entry_order_id, "filled")

            effective_entry_price = avg_fill_price or Decimal(formatted_price)

            tp_price = DecimalUtils.calculate_take_profit_price(
                effective_entry_price, self.config.TAKE_PROFIT_PERCENTAGE
            )
            sl_price = DecimalUtils.calculate_stop_loss_price(
                effective_entry_price, self.config.STOP_LOSS_PERCENTAGE
            )

            formatted_tp = DecimalUtils.format_price(tp_price, price_decimals)
            formatted_sl = DecimalUtils.format_price(sl_price, price_decimals)
            formatted_filled_qty = DecimalUtils.format_quantity(filled_qty, qty_decimals)

            self.logger.info(f"Entry filled: qty={formatted_filled_qty} @ {effective_entry_price}. Placing TP/SL...")

            tp_order = self.api.place_limit_order(
                pair=pair,
                side="SELL",
                quantity=formatted_filled_qty,
                price=formatted_tp,
                post_only=False,
            )
            sl_order = self.api.place_limit_order(
                pair=pair,
                side="SELL",
                quantity=formatted_filled_qty,
                price=formatted_sl,
                post_only=False,
            )

            tp_order_id = str(tp_order.get("id") or tp_order.get("orderId") or "")
            sl_order_id = str(sl_order.get("id") or sl_order.get("orderId") or "")

            if tp_order_id:
                self.order_persistence.add_order(
                    order_id=tp_order_id,
                    pair=pair,
                    side="sell",
                    quantity=Decimal(formatted_filled_qty),
                    entry_price=Decimal(formatted_tp),
                    order_type="take_profit",
                )

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
                take_profit_price=Decimal(formatted_tp),
                entry_filled_at=datetime.now(),
            )
            if tp_order_id and sl_order_id:
                self.position_manager.attach_exit_orders(position_id, tp_order_id, sl_order_id)

            self._increment_trade_count()

            self.logger.info(f"Trade active for {pair}: TP={formatted_tp} SL={formatted_sl}")
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

    def _cancel_if_open(self, order_id: Optional[str]) -> None:
        if not order_id:
            return
        try:
            status_data = self.api.get_order_status(order_id)
            status = self._extract_order_status(status_data)
            if _status_is_filled(status) or _status_is_cancelled(status):
                return
            self.api.cancel_order(order_id)
        except Exception:
            return

    def _sync_persisted_order_status(self, order_id: str) -> None:
        try:
            status_data = self.api.get_order_status(order_id)
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
        self._cancel_if_open(tp_id)
        self._cancel_if_open(sl_id)
        if tp_id:
            self._sync_persisted_order_status(tp_id)
        if sl_id:
            self._sync_persisted_order_status(sl_id)

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

            price_decimals = self.config.get_pair_price_decimals(pair)
            aggressive_price = DecimalUtils.format_price(best_bid, price_decimals)
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
        pair = position["pair"]
        position_id = position["id"]

        entry_filled_at: datetime = position.get("entry_filled_at") or position.get("created_at")

        if datetime.now() > entry_filled_at + timedelta(minutes=self.config.POSITION_TIMEOUT_MINUTES):
            self._close_position_at_market(position, reason="position_timeout")
            return

        if datetime.now() > entry_filled_at + timedelta(minutes=self.config.EXIT_ORDER_TIMEOUT_MINUTES):
            self._close_position_at_market(position, reason="exit_orders_timeout")
            return

        tp_id = position.get("take_profit_order_id")
        sl_id = position.get("stop_loss_order_id")

        tp_status = None
        sl_status = None

        if tp_id:
            try:
                tp_data = self.api.get_order_status(tp_id)
                tp_status = self._extract_order_status(tp_data)
            except Exception:
                tp_status = None

        if sl_id:
            try:
                sl_data = self.api.get_order_status(sl_id)
                sl_status = self._extract_order_status(sl_data)
            except Exception:
                sl_status = None

        if tp_status and _status_is_filled(tp_status):
            self.logger.info(f"Take profit filled for {pair}. Cancelling stop loss...")
            if tp_id:
                self.order_persistence.update_order_status(tp_id, "filled")
            self._cancel_if_open(sl_id)
            if sl_id:
                self.order_persistence.update_order_status(sl_id, "cancelled")
            self.position_manager.close_position(position_id, "take_profit")
            return

        if sl_status and _status_is_filled(sl_status):
            self.logger.info(f"Stop loss filled for {pair}. Cancelling take profit...")
            if sl_id:
                self.order_persistence.update_order_status(sl_id, "filled")
            self._cancel_if_open(tp_id)
            if tp_id:
                self.order_persistence.update_order_status(tp_id, "cancelled")
            self.position_manager.close_position(position_id, "stop_loss")
            return

    def _is_daily_limit_reached(self) -> bool:
        current_date = datetime.now().date()
        if current_date != self.last_trade_date:
            self.trades_today = 0
            self.daily_pnl = Decimal("0")
            self.last_trade_date = current_date
        return self.trades_today >= self.config.MAX_DAILY_TRADES

    def _increment_trade_count(self) -> None:
        self.trades_today += 1
        self.logger.debug(f"Trade count today: {self.trades_today}/{self.config.MAX_DAILY_TRADES}")

    def get_trading_statistics(self) -> Dict:
        open_positions = self.position_manager.get_open_positions()
        return {
            "trades_today": self.trades_today,
            "max_daily_trades": self.config.MAX_DAILY_TRADES,
            "daily_limit_reached": self._is_daily_limit_reached(),
            "open_positions": len(open_positions),
            "daily_pnl": str(self.daily_pnl),
            "last_trade_date": self.last_trade_date.isoformat(),
        }
