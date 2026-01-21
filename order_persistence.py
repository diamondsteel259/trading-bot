"""
Order persistence module for VALR trading bot.
Handles saving and loading active orders for crash recovery.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from decimal import Decimal

from config import Config
from logging_setup import get_logger


class OrderPersistenceError(Exception):
    """Raised when order persistence operations fail."""
    pass


class OrderRecord:
    """Represents a persisted order record."""
    
    def __init__(self, order_id: str, pair: str, side: str, quantity: Decimal, 
                 entry_price: Decimal, order_type: str, created_at: datetime,
                 stop_loss_price: Optional[Decimal] = None,
                 take_profit_price: Optional[Decimal] = None,
                 status: str = "active"):
        self.order_id = order_id
        self.pair = pair
        self.side = side
        self.quantity = quantity
        self.entry_price = entry_price
        self.order_type = order_type
        self.created_at = created_at
        self.stop_loss_price = stop_loss_price
        self.take_profit_price = take_profit_price
        self.status = status
        self.last_updated = created_at
    
    def to_dict(self) -> Dict:
        """Convert order record to dictionary for JSON serialization."""
        return {
            "order_id": self.order_id,
            "pair": self.pair,
            "side": self.side,
            "quantity": str(self.quantity),
            "entry_price": str(self.entry_price),
            "order_type": self.order_type,
            "created_at": self.created_at.isoformat(),
            "stop_loss_price": str(self.stop_loss_price) if self.stop_loss_price else None,
            "take_profit_price": str(self.take_profit_price) if self.take_profit_price else None,
            "status": self.status,
            "last_updated": self.last_updated.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'OrderRecord':
        """Create order record from dictionary."""
        return cls(
            order_id=data["order_id"],
            pair=data["pair"],
            side=data["side"],
            quantity=Decimal(data["quantity"]),
            entry_price=Decimal(data["entry_price"]),
            order_type=data["order_type"],
            created_at=datetime.fromisoformat(data["created_at"]),
            stop_loss_price=Decimal(data["stop_loss_price"]) if data.get("stop_loss_price") else None,
            take_profit_price=Decimal(data["take_profit_price"]) if data.get("take_profit_price") else None,
            status=data["status"]
        )
    
    def __repr__(self) -> str:
        """String representation of order record."""
        return (f"OrderRecord(id={self.order_id}, pair={self.pair}, side={self.side}, "
                f"quantity={self.quantity}, price={self.entry_price}, status={self.status})")


class OrderPersistence:
    """Handles persistence of active orders for crash recovery."""
    
    def __init__(self, config: Config):
        """Initialize order persistence handler."""
        self.config = config
        self.logger = get_logger("order_persistence")
        self.orders_file = Path(config.ORDERS_FILE_PATH)
        self.active_orders: Dict[str, OrderRecord] = {}
        
        # Create data directory if it doesn't exist
        self.orders_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing orders on initialization
        if config.ENABLE_ORDER_PERSISTENCE:
            self.load_orders()
    
    def add_order(self, order_id: str, pair: str, side: str, quantity: Decimal,
                  entry_price: Decimal, order_type: str = "limit",
                  stop_loss_price: Optional[Decimal] = None,
                  take_profit_price: Optional[Decimal] = None) -> None:
        """Add an order to the active orders tracking."""
        if not self.config.ENABLE_ORDER_PERSISTENCE:
            return
        
        order_record = OrderRecord(
            order_id=order_id,
            pair=pair,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            order_type=order_type,
            created_at=datetime.now(timezone.utc),
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            status="active"
        )
        
        self.active_orders[order_id] = order_record
        self.logger.debug(f"Added order to persistence: {order_record}")
        
        # Save immediately
        self.save_orders()
    
    def update_order_status(self, order_id: str, status: str) -> None:
        """Update the status of an order."""
        if not self.config.ENABLE_ORDER_PERSISTENCE or order_id not in self.active_orders:
            return
        
        self.active_orders[order_id].status = status
        self.active_orders[order_id].last_updated = datetime.now(timezone.utc)
        
        # Remove from active orders if completed or cancelled
        if status in ["filled", "cancelled", "rejected"]:
            self.remove_order(order_id)
        else:
            self.save_orders()
    
    def remove_order(self, order_id: str) -> bool:
        """Remove an order from active tracking."""
        if not self.config.ENABLE_ORDER_PERSISTENCE or order_id not in self.active_orders:
            return False
        
        removed_order = self.active_orders.pop(order_id)
        self.logger.debug(f"Removed order from persistence: {removed_order}")
        self.save_orders()
        return True
    
    def get_active_orders(self) -> List[OrderRecord]:
        """Get all active orders."""
        return list(self.active_orders.values())
    
    def get_order_by_id(self, order_id: str) -> Optional[OrderRecord]:
        """Get a specific order by ID."""
        return self.active_orders.get(order_id)
    
    def get_orders_by_pair(self, pair: str) -> List[OrderRecord]:
        """Get all active orders for a specific trading pair."""
        return [order for order in self.active_orders.values() if order.pair == pair]
    
    def save_orders(self) -> None:
        """Save active orders to file."""
        if not self.config.ENABLE_ORDER_PERSISTENCE:
            return
        
        try:
            orders_data = {
                "version": "1.0",
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "orders": [order.to_dict() for order in self.active_orders.values()]
            }
            
            # Write to temporary file first, then rename to avoid corruption
            temp_file = self.orders_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(orders_data, f, indent=2)
            
            # Atomic rename
            temp_file.rename(self.orders_file)
            
            self.logger.debug(f"Saved {len(self.active_orders)} active orders to {self.orders_file}")
            
        except Exception as e:
            self.logger.error(f"Failed to save orders to {self.orders_file}: {e}")
            raise OrderPersistenceError(f"Failed to save orders: {e}")
    
    def load_orders(self) -> None:
        """Load active orders from file."""
        if not self.config.ENABLE_ORDER_PERSISTENCE:
            return
        
        if not self.orders_file.exists():
            self.logger.info("No existing orders file found, starting fresh")
            return
        
        try:
            with open(self.orders_file, 'r') as f:
                orders_data = json.load(f)
            
            # Load orders
            loaded_count = 0
            for order_dict in orders_data.get("orders", []):
                try:
                    order_record = OrderRecord.from_dict(order_dict)
                    
                    # Only load active orders
                    if order_record.status == "active":
                        self.active_orders[order_record.order_id] = order_record
                        loaded_count += 1
                        
                except Exception as e:
                    self.logger.warning(f"Failed to load order {order_dict.get('order_id', 'unknown')}: {e}")
                    continue
            
            self.logger.info(f"Loaded {loaded_count} active orders from {self.orders_file}")
            
        except Exception as e:
            self.logger.error(f"Failed to load orders from {self.orders_file}: {e}")
            # Don't raise exception here - we can continue without persisted orders
            # but log the error for debugging
    
    def clear_all_orders(self) -> None:
        """Clear all active orders (used for testing or manual cleanup)."""
        if not self.config.ENABLE_ORDER_PERSISTENCE:
            return
        
        cleared_count = len(self.active_orders)
        self.active_orders.clear()
        self.save_orders()
        
        self.logger.info(f"Cleared {cleared_count} orders from persistence")
    
    def cleanup_old_orders(self, max_age_hours: int = 24) -> int:
        """Remove orders older than specified hours (typically for stale orders)."""
        if not self.config.ENABLE_ORDER_PERSISTENCE:
            return 0
        
        cutoff_time = datetime.now(timezone.utc).timestamp() - (max_age_hours * 3600)
        orders_to_remove = []
        
        for order_id, order_record in self.active_orders.items():
            if order_record.created_at.timestamp() < cutoff_time:
                orders_to_remove.append(order_id)
        
        # Remove stale orders
        for order_id in orders_to_remove:
            self.remove_order(order_id)
        
        if orders_to_remove:
            self.logger.info(f"Removed {len(orders_to_remove)} stale orders (older than {max_age_hours}h)")
        
        return len(orders_to_remove)
    
    def get_statistics(self) -> Dict:
        """Get statistics about persisted orders."""
        if not self.active_orders:
            return {
                "total_active_orders": 0,
                "orders_by_pair": {},
                "oldest_order_age_hours": 0,
                "newest_order_age_hours": 0
            }
        
        # Group by pair
        orders_by_pair = {}
        for order in self.active_orders.values():
            orders_by_pair[order.pair] = orders_by_pair.get(order.pair, 0) + 1
        
        # Calculate age statistics
        now = datetime.now(timezone.utc)
        ages = [(now - order.created_at).total_seconds() / 3600 for order in self.active_orders.values()]
        
        return {
            "total_active_orders": len(self.active_orders),
            "orders_by_pair": orders_by_pair,
            "oldest_order_age_hours": max(ages) if ages else 0,
            "newest_order_age_hours": min(ages) if ages else 0
        }


# Global order persistence instance
order_persistence = None


def initialize_order_persistence(config: Config) -> OrderPersistence:
    """Initialize global order persistence."""
    global order_persistence
    order_persistence = OrderPersistence(config)
    return order_persistence


def get_order_persistence() -> OrderPersistence:
    """Get global order persistence instance."""
    if order_persistence is None:
        raise RuntimeError("Order persistence not initialized. Call initialize_order_persistence() first.")
    return order_persistence