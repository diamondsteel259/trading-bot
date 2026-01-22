"""
Trading engine for VALR trading bot.
Handles order placement, position management, and risk management.
"""

from typing import Dict, List, Optional, Tuple
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
    pass


class InsufficientBalanceError(TradingError):
    """Raised when account balance is insufficient for trading."""
    pass


class PositionManager:
    """Manages trading positions and their lifecycle."""
    
    def __init__(self, api: VALRAPI, config: Config):
        """Initialize position manager."""
        self.api = api
        self.config = config
        self.logger = get_logger("position_manager")
        self.valr_logger = get_valr_logger()
        self.active_positions: Dict[str, Dict] = {}
    
    def create_position(self, pair: str, quantity: Decimal, entry_price: Decimal,
                      stop_loss_price: Optional[Decimal] = None,
                      take_profit_price: Optional[Decimal] = None) -> str:
        """
        Create a new trading position.
        
        Args:
            pair: Trading pair symbol
            quantity: Position size
            entry_price: Entry price
            stop_loss_price: Optional stop loss price
            take_profit_price: Optional take profit price
            
        Returns:
            Position ID
        """
        position_id = f"{pair}_{int(time.time())}"
        
        position = {
            "id": position_id,
            "pair": pair,
            "quantity": quantity,
            "entry_price": entry_price,
            "stop_loss_price": stop_loss_price,
            "take_profit_price": take_profit_price,
            "created_at": datetime.now(),
            "status": "open",
            "orders": [],
            "total_filled": Decimal('0')
        }
        
        self.active_positions[position_id] = position
        
        self.valr_logger.log_position_update(
            pair=pair,
            position_type="created",
            quantity=float(quantity),
            entry_price=float(entry_price),
            current_price=float(entry_price),
            pnl=0.0
        )
        
        return position_id
    
    def update_position_fill(self, position_id: str, filled_quantity: Decimal,
                           fill_price: Decimal) -> None:
        """Update position based on order fill."""
        if position_id not in self.active_positions:
            self.logger.warning(f"Position {position_id} not found")
            return
        
        position = self.active_positions[position_id]
        position["total_filled"] += filled_quantity
        
        # Check if position is fully filled
        if position["total_filled"] >= position["quantity"]:
            position["status"] = "filled"
            self.logger.info(f"Position {position_id} fully filled")
        
        self.valr_logger.log_position_update(
            pair=position["pair"],
            position_type="filled",
            quantity=float(position["total_filled"]),
            entry_price=float(position["entry_price"]),
            current_price=float(fill_price)
        )
    
    def close_position(self, position_id: str, reason: str = "manual") -> None:
        """Close a position."""
        if position_id not in self.active_positions:
            return
        
        position = self.active_positions[position_id]
        position["status"] = "closed"
        position["closed_at"] = datetime.now()
        position["close_reason"] = reason
        
        self.valr_logger.log_position_update(
            pair=position["pair"],
            position_type="closed",
            quantity=float(position["total_filled"]),
            entry_price=float(position["entry_price"]),
            pnl=0.0  # TODO: Calculate actual PnL
        )
        
        # Remove from active positions
        del self.active_positions[position_id]
    
    def get_open_positions(self) -> List[Dict]:
        """Get all open positions."""
        return [pos for pos in self.active_positions.values() if pos["status"] == "open"]
    
    def get_position_by_id(self, position_id: str) -> Optional[Dict]:
        """Get position by ID."""
        return self.active_positions.get(position_id)


class VALRTradingEngine:
    """Main trading engine for VALR exchange."""
    
    def __init__(self, api: VALRAPI, config: Config):
        """Initialize trading engine."""
        self.api = api
        self.config = config
        self.logger = get_logger("trading_engine")
        self.valr_logger = get_valr_logger()
        self.position_manager = PositionManager(api, config)
        self.order_persistence = get_order_persistence()
        
        # Statistics
        self.trades_today = 0
        self.last_trade_date = datetime.now().date()
        self.daily_pnl = Decimal('0')
    
    def check_balance(self, currency: str, required_amount: Decimal) -> bool:
        """
        Check if sufficient balance is available.
        
        Args:
            currency: Currency symbol (e.g., 'ZAR', 'USDT')
            required_amount: Required amount
            
        Returns:
            True if sufficient balance, False otherwise
        """
        try:
            balances = self.api.get_account_balances()
            available_balance = balances.get(currency, Decimal('0'))
            
            sufficient = available_balance >= required_amount
            
            self.logger.debug(f"Balance check for {currency}: available={available_balance}, required={required_amount}, sufficient={sufficient}")
            return sufficient
            
        except Exception as e:
            self.logger.error(f"Failed to check balance for {currency}: {e}")
            return False
    
    def calculate_position_size(self, pair: str, available_balance: Decimal) -> Tuple[Decimal, str]:
        """
        Calculate position size based on available balance and risk management.
        
        Args:
            pair: Trading pair
            available_balance: Available balance
            
        Returns:
            Tuple of (quantity, formatted_quantity)
        """
        # Ensure we don't exceed maximum position size
        max_quantity = self.config.MAX_POSITION_SIZE / Decimal('1')  # Assume price of 1 for now
        
        # Use the smaller of available balance and max position size
        calculated_quantity = min(self.config.BASE_TRADE_AMOUNT, available_balance, max_quantity)
        
        # Format according to pair precision
        quantity_decimals = 8  # Most crypto pairs support 8 decimal places
        formatted_quantity = DecimalUtils.format_quantity(calculated_quantity, quantity_decimals)
        
        return Decimal(formatted_quantity), formatted_quantity
    
    def place_entry_order(self, pair: str, entry_price: str, quantity: str,
                         order_type: str = "limit") -> Optional[str]:
        """
        Place entry order for a position.
        
        Args:
            pair: Trading pair
            entry_price: Entry price
            quantity: Order quantity
            order_type: Order type ('limit', 'post_only_limit')
            
        Returns:
            Order ID if successful, None otherwise
        """
        try:
            # Determine quote currency and check balance
            if pair.endswith('ZAR'):
                quote_currency = 'ZAR'
            elif pair.endswith('USDT'):
                quote_currency = 'USDT'
            elif pair.endswith('USD'):
                quote_currency = 'USD'
            else:
                quote_currency = 'USDT'  # Default assumption
            
            # Calculate required balance
            required_balance = Decimal(entry_price) * Decimal(quantity)
            
            # Check balance
            if not self.check_balance(quote_currency, required_balance):
                raise InsufficientBalanceError(
                    f"Insufficient {quote_currency} balance. Required: {required_balance}, "
                    f"Available: Check account balance"
                )
            
            # Place the order
            order_result = self.api.place_limit_order(
                pair=pair,
                side="buy",
                quantity=quantity,
                price=entry_price,
                post_only=True  # Always use post-only to avoid taker fees
            )
            
            order_id = order_result.get('id')
            if order_id:
                # Add to order persistence
                self.order_persistence.add_order(
                    order_id=order_id,
                    pair=pair,
                    side="buy",
                    quantity=Decimal(quantity),
                    entry_price=Decimal(entry_price),
                    order_type=order_type
                )
                
                # Create position tracking
                self.position_manager.create_position(
                    pair=pair,
                    quantity=Decimal(quantity),
                    entry_price=Decimal(entry_price)
                )
                
                self.valr_logger.log_order_event(
                    event_type="ENTRY_PLACED",
                    order_id=order_id,
                    pair=pair,
                    side="buy",
                    quantity=float(quantity),
                    price=float(entry_price)
                )
            
            return order_id
            
        except VALRAPIError as e:
            self.logger.error(f"API error placing entry order for {pair}: {e}")
            return None
        except InsufficientBalanceError as e:
            self.logger.warning(f"Insufficient balance for {pair}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error placing entry order for {pair}: {e}")
            return None
    
    def place_take_profit_order(self, pair: str, quantity: str, 
                               take_profit_price: str, order_id: str) -> Optional[str]:
        """
        Place take profit order.
        
        Args:
            pair: Trading pair
            quantity: Quantity to sell
            take_profit_price: Take profit price
            order_id: Reference order ID for tracking
            
        Returns:
            Take profit order ID if successful
        """
        try:
            order_result = self.api.place_limit_order(
                pair=pair,
                side="sell",
                quantity=quantity,
                price=take_profit_price,
                post_only=True
            )
            
            tp_order_id = order_result.get('id')
            
            self.valr_logger.log_order_event(
                event_type="TAKE_PROFIT_PLACED",
                order_id=tp_order_id or "unknown",
                pair=pair,
                side="sell",
                quantity=float(quantity),
                price=float(take_profit_price)
            )
            
            return tp_order_id
            
        except Exception as e:
            self.logger.error(f"Failed to place take profit order for {pair}: {e}")
            return None
    
    def place_stop_loss_order(self, pair: str, quantity: str,
                             stop_loss_price: str, order_id: str) -> Optional[str]:
        """
        Place stop loss order.
        
        Args:
            pair: Trading pair
            quantity: Quantity to sell
            stop_loss_price: Stop loss price
            order_id: Reference order ID for tracking
            
        Returns:
            Stop loss order ID if successful
        """
        try:
            # Note: VALR may not support true stop orders, so we'll use limit orders
            # In practice, you might want to monitor prices and place market orders
            order_result = self.api.place_limit_order(
                pair=pair,
                side="sell",
                quantity=quantity,
                price=stop_loss_price,
                post_only=False  # Use regular limit for stop loss to ensure execution
            )
            
            sl_order_id = order_result.get('id')
            
            self.valr_logger.log_order_event(
                event_type="STOP_LOSS_PLACED",
                order_id=sl_order_id or "unknown",
                pair=pair,
                side="sell",
                quantity=float(quantity),
                price=float(stop_loss_price)
            )
            
            return sl_order_id
            
        except Exception as e:
            self.logger.error(f"Failed to place stop loss order for {pair}: {e}")
            return None
    
    def execute_trade_setup(self, pair: str, rsi_value: float) -> Optional[str]:
        """
        Execute complete trade setup based on RSI signal.
        
        Args:
            pair: Trading pair
            rsi_value: RSI value that triggered the signal
            
        Returns:
            Entry order ID if successful
        """
        try:
            # Check daily trade limits
            if self._is_daily_limit_reached():
                self.logger.warning(f"Daily trade limit reached, skipping {pair}")
                return None
            
            # Get current market price and analysis
            from rsi_scanner import RSIScanner
            scanner = RSIScanner(self.api, self.config)
            entry_analysis = scanner.find_best_entry(pair)
            
            if not entry_analysis:
                self.logger.error(f"Could not analyze entry for {pair}")
                return None
            
            # Calculate take profit and stop loss prices
            entry_price = entry_analysis["recommended_entry"]
            tp_price = DecimalUtils.calculate_take_profit_price(
                entry_price, self.config.TAKE_PROFIT_PERCENTAGE
            )
            sl_price = DecimalUtils.calculate_stop_loss_price(
                entry_price, self.config.STOP_LOSS_PERCENTAGE
            )
            
            # Format prices according to pair precision
            price_decimals = self.config.get_pair_decimals(pair)
            formatted_tp_price = DecimalUtils.format_price(tp_price, price_decimals)
            formatted_sl_price = DecimalUtils.format_price(sl_price, price_decimals)
            
            self.logger.info(
                f"Trade setup for {pair}: RSI={rsi_value:.2f}, "
                f"Entry={entry_price:.6f}, TP={formatted_tp_price}, SL={formatted_sl_price}"
            )
            
            # Place entry order
            entry_order_id = self.place_entry_order(
                pair=pair,
                entry_price=str(entry_analysis["formatted_price"]),
                quantity=entry_analysis["formatted_quantity"]
            )
            
            if entry_order_id:
                # Schedule take profit and stop loss orders (in a real system, 
                # these would be placed after entry order fills)
                self.logger.info(
                    f"Entry order placed for {pair}: {entry_order_id}. "
                    f"TP: {formatted_tp_price}, SL: {formatted_sl_price}"
                )
                
                # Update trade statistics
                self._increment_trade_count()
                
            return entry_order_id
            
        except Exception as e:
            self.logger.error(f"Failed to execute trade setup for {pair}: {e}")
            return None
    
    def monitor_positions(self) -> None:
        """Monitor all open positions for take profit, stop loss, and timeout conditions."""
        open_positions = self.position_manager.get_open_positions()
        
        if not open_positions:
            return
        
        self.logger.debug(f"Monitoring {len(open_positions)} open positions")
        
        for position in open_positions:
            self._check_position_conditions(position)
    
    def _check_position_conditions(self, position: Dict) -> None:
        """Check if position meets any exit conditions."""
        pair = position["pair"]
        position_id = position["id"]
        created_at = position["created_at"]
        
        # Check timeout condition
        timeout_threshold = created_at + timedelta(minutes=self.config.ORDER_TIMEOUT_MINUTES)
        if datetime.now() > timeout_threshold:
            self.logger.info(f"Position {position_id} timed out, closing")
            # In a real system, you would cancel orders and close position
            self.position_manager.close_position(position_id, "timeout")
            return
        
        # Get current market price for PnL calculation
        try:
            pair_summary = self.api.get_pair_summary(pair)
            current_price = float(pair_summary.get('lastTradedPrice', 0))
            
            if current_price > 0:
                entry_price = float(position["entry_price"])
                pnl_pct = DecimalUtils.calculate_pnl_percentage(entry_price, current_price)
                
                # Check take profit condition
                if position.get("take_profit_price"):
                    tp_price = float(position["take_profit_price"])
                    if current_price >= tp_price:
                        self.logger.info(f"Take profit triggered for {pair}: {current_price} >= {tp_price}")
                        self.position_manager.close_position(position_id, "take_profit")
                        return
                
                # Check stop loss condition
                if position.get("stop_loss_price"):
                    sl_price = float(position["stop_loss_price"])
                    if current_price <= sl_price:
                        self.logger.info(f"Stop loss triggered for {pair}: {current_price} <= {sl_price}")
                        self.position_manager.close_position(position_id, "stop_loss")
                        return
                
        except Exception as e:
            self.logger.error(f"Failed to check position conditions for {pair}: {e}")
    
    def _is_daily_limit_reached(self) -> bool:
        """Check if daily trade limit has been reached."""
        current_date = datetime.now().date()
        
        if current_date != self.last_trade_date:
            # New day, reset counters
            self.trades_today = 0
            self.daily_pnl = Decimal('0')
            self.last_trade_date = current_date
        
        return self.trades_today >= self.config.MAX_DAILY_TRADES
    
    def _increment_trade_count(self) -> None:
        """Increment today's trade count."""
        self.trades_today += 1
        self.logger.debug(f"Trade count today: {self.trades_today}/{self.config.MAX_DAILY_TRADES}")
    
    def get_trading_statistics(self) -> Dict:
        """Get trading performance statistics."""
        open_positions = self.position_manager.get_open_positions()
        
        return {
            "trades_today": self.trades_today,
            "max_daily_trades": self.config.MAX_DAILY_TRADES,
            "daily_limit_reached": self._is_daily_limit_reached(),
            "open_positions": len(open_positions),
            "daily_pnl": str(self.daily_pnl),
            "last_trade_date": self.last_trade_date.isoformat()
        }