"""Position persistence for VALR trading bot.

Handles saving and loading of active positions to/from JSON file.
Allows bot to resume monitoring positions after restart.
"""

import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Any, Optional
from logging_setup import get_logger


class PositionPersistence:
    """Handles persistence of trading positions."""

    def __init__(self, file_path: str = "data/positions.json"):
        self.file_path = file_path
        self.logger = get_logger("position_persistence")
        self._ensure_data_directory()

    def _ensure_data_directory(self):
        """Ensure the data directory exists."""
        directory = os.path.dirname(self.file_path)
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)

    def save_positions(self, positions: Dict[str, Dict[str, Any]]) -> None:
        """Save all active positions to JSON file."""
        try:
            # Convert positions to JSON-serializable format
            serializable_positions = {}
            for pos_id, position in positions.items():
                serializable_positions[pos_id] = {
                    "id": position["id"],
                    "pair": position["pair"],
                    "quantity": str(position["quantity"]),
                    "entry_price": str(position["entry_price"]),
                    "stop_loss_price": str(position["stop_loss_price"]),
                    "take_profit_price": str(position["take_profit_price"]),
                    "created_at": position["created_at"].isoformat(),
                    "entry_filled_at": position["entry_filled_at"].isoformat(),
                    "status": position["status"],
                    "entry_order_id": position["entry_order_id"],
                    "take_profit_order_id": position.get("take_profit_order_id"),
                    "stop_loss_order_id": position.get("stop_loss_order_id"),
                }

            with open(self.file_path, 'w') as f:
                json.dump(serializable_positions, f, indent=2)

            self.logger.debug(f"Saved {len(positions)} positions to {self.file_path}")

        except Exception as e:
            self.logger.error(f"Failed to save positions: {e}")

    def load_positions(self) -> Dict[str, Dict[str, Any]]:
        """Load all positions from JSON file."""
        try:
            if not os.path.exists(self.file_path):
                self.logger.info(f"No positions file found at {self.file_path}")
                return {}

            with open(self.file_path, 'r') as f:
                data = json.load(f)

            # Convert back to proper types
            positions = {}
            for pos_id, position in data.items():
                positions[pos_id] = {
                    "id": position["id"],
                    "pair": position["pair"],
                    "quantity": Decimal(position["quantity"]),
                    "entry_price": Decimal(position["entry_price"]),
                    "stop_loss_price": Decimal(position["stop_loss_price"]),
                    "take_profit_price": Decimal(position["take_profit_price"]),
                    "created_at": datetime.fromisoformat(position["created_at"]),
                    "entry_filled_at": datetime.fromisoformat(position["entry_filled_at"]),
                    "status": position["status"],
                    "entry_order_id": position["entry_order_id"],
                    "take_profit_order_id": position.get("take_profit_order_id"),
                    "stop_loss_order_id": position.get("stop_loss_order_id"),
                }

            self.logger.info(f"Loaded {len(positions)} active positions from {self.file_path}")
            return positions

        except Exception as e:
            self.logger.error(f"Failed to load positions: {e}")
            return {}

    def delete_position(self, position_id: str) -> None:
        """Delete a specific position from persistence."""
        try:
            positions = self.load_positions()
            if position_id in positions:
                del positions[position_id]
                self.save_positions(positions)
                self.logger.debug(f"Deleted position {position_id} from persistence")
        except Exception as e:
            self.logger.error(f"Failed to delete position {position_id}: {e}")


# Global singleton
_position_persistence_instance: Optional[PositionPersistence] = None


def get_position_persistence(file_path: str = "data/positions.json") -> PositionPersistence:
    """Get or create the global position persistence instance."""
    global _position_persistence_instance
    if _position_persistence_instance is None:
        _position_persistence_instance = PositionPersistence(file_path)
    return _position_persistence_instance
