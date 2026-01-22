"""
Structured logging setup for VALR trading bot.
Provides consistent logging to both console and file with rotation.
"""

import logging
import logging.handlers
from pathlib import Path
from typing import Optional
from config import Config


class VALRLogger:
    """Centralized logging configuration for VALR trading bot."""
    
    def __init__(self, config: Config):
        """Initialize logger with configuration."""
        self.config = config
        self.logger = None
        self._setup_logging()
    
    def _setup_logging(self) -> None:
        """Setup logging configuration with rotation."""
        # Create log directory
        self.config.create_directories()
        
        # Setup root logger
        self.logger = logging.getLogger("valr_bot")
        self.logger.setLevel(getattr(logging, self.config.LOG_LEVEL))
        
        # Clear existing handlers
        self.logger.handlers.clear()
        
        # Create formatter
        formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # File handler with rotation
        file_handler = logging.handlers.RotatingFileHandler(
            filename=self.config.LOG_FILE_PATH,
            maxBytes=self.config.LOG_MAX_SIZE_MB * 1024 * 1024,
            backupCount=self.config.LOG_BACKUP_COUNT,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, self.config.LOG_LEVEL))
        console_formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        
        # Add handlers to logger
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        # Prevent propagation to avoid duplicate logs
        self.logger.propagate = False
    
    def get_logger(self, name: Optional[str] = None) -> logging.Logger:
        """Get a logger instance."""
        if name:
            return logging.getLogger(f"valr_bot.{name}")
        return self.logger
    
    def log_trade_event(self, event_type: str, pair: str, details: dict) -> None:
        """Log trading events with structured data."""
        log_data = {
            "event_type": event_type,
            "pair": pair,
            **details
        }
        self.logger.info(f"TRADE_EVENT: {log_data}")
    
    def log_api_call(self, endpoint: str, method: str, status_code: Optional[int] = None, 
                    response_time: Optional[float] = None, error: Optional[str] = None) -> None:
        """Log API calls for monitoring."""
        log_data = {
            "endpoint": endpoint,
            "method": method,
            "status_code": status_code,
            "response_time_ms": round(response_time * 1000, 2) if response_time else None,
            "error": error
        }
        
        if error:
            self.logger.error(f"API_ERROR: {log_data}")
        elif status_code and 200 <= status_code < 300:
            self.logger.debug(f"API_SUCCESS: {log_data}")
        else:
            self.logger.warning(f"API_RESPONSE: {log_data}")
    
    def log_order_event(self, event_type: str, order_id: str, pair: str, 
                       side: str, quantity: Optional[float] = None, 
                       price: Optional[float] = None, status: Optional[str] = None) -> None:
        """Log order events with structured data."""
        log_data = {
            "event_type": event_type,
            "order_id": order_id,
            "pair": pair,
            "side": side,
            "quantity": quantity,
            "price": price,
            "status": status
        }
        self.logger.info(f"ORDER_EVENT: {log_data}")
    
    def log_rsi_scan(self, pair: str, rsi_value: float, threshold: float, action: str) -> None:
        """Log RSI scanning results."""
        log_data = {
            "pair": pair,
            "rsi_value": rsi_value,
            "threshold": threshold,
            "action": action
        }
        self.logger.debug(f"RSI_SCAN: {log_data}")
    
    def log_position_update(self, pair: str, position_type: str, quantity: float, 
                          entry_price: Optional[float] = None, 
                          current_price: Optional[float] = None,
                          pnl: Optional[float] = None) -> None:
        """Log position updates."""
        log_data = {
            "pair": pair,
            "position_type": position_type,
            "quantity": quantity,
            "entry_price": entry_price,
            "current_price": current_price,
            "pnl": pnl
        }
        self.logger.info(f"POSITION_UPDATE: {log_data}")


# Global logger instance
valr_logger = None


def setup_logging(config: Config) -> VALRLogger:
    """Setup global logging configuration."""
    global valr_logger
    valr_logger = VALRLogger(config)
    return valr_logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Get a logger instance."""
    if valr_logger is None:
        raise RuntimeError("Logging not initialized. Call setup_logging() first.")
    return valr_logger.get_logger(name)


def get_valr_logger() -> VALRLogger:
    """Get the VALRLogger instance with custom logging methods."""
    if valr_logger is None:
        raise RuntimeError("Logging not initialized. Call setup_logging() first.")
    return valr_logger