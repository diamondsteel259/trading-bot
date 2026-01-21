"""
Configuration management for VALR trading bot.
Handles loading and validation of environment variables.
"""

import os
from decimal import Decimal
from typing import Dict, List, Optional
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class ConfigError(Exception):
    """Raised when configuration validation fails."""
    pass


class Config:
    """Configuration class with validation for VALR trading bot."""
    
    # VALR API Configuration
    VALR_API_KEY: str
    VALR_API_SECRET: str
    VALR_BASE_URL: str = "https://api.valr.com"
    VALR_API_VERSION: str = "v1"
    
    # Trading Configuration
    TRADING_PAIRS: List[str]
    RSI_THRESHOLD: float
    TAKE_PROFIT_PERCENTAGE: float
    STOP_LOSS_PERCENTAGE: float
    ORDER_TIMEOUT_MINUTES: int
    BASE_TRADE_AMOUNT: Decimal
    
    # Risk Management
    MAX_POSITION_SIZE: Decimal
    MAX_DAILY_TRADES: int
    
    # Retry & Resilience
    MAX_RETRIES: int
    RETRY_BACKOFF_FACTOR: float
    REQUEST_TIMEOUT: int
    RATE_LIMIT_REQUESTS_PER_MINUTE: int
    
    # Logging Configuration
    LOG_LEVEL: str
    LOG_FILE_PATH: str
    LOG_MAX_SIZE_MB: int
    LOG_BACKUP_COUNT: int
    
    # Order Persistence
    ORDERS_FILE_PATH: str
    ENABLE_ORDER_PERSISTENCE: bool = True
    
    # Decimals Configuration (pair-specific precision)
    PAIR_DECIMALS: Dict[str, int] = {
        "BTCZAR": 8,
        "ETHZAR": 6,
        "ADAUSD": 6,
        "DOTUSD": 6,
        "LINKUSD": 6,
        "LTCUSD": 6,
        "XRPUSD": 6,
        "BCHUSD": 6,
        "BNBUSD": 6,
        "ADAUSDT": 6,
        "ETHUSDT": 6,
        "BTCUSDT": 8,
    }
    
    def __init__(self):
        """Initialize and validate configuration."""
        self._load_from_env()
        self._validate_config()
    
    def _load_from_env(self) -> None:
        """Load configuration values from environment variables."""
        # VALR API Configuration
        self.VALR_API_KEY = os.getenv("VALR_API_KEY", "")
        self.VALR_API_SECRET = os.getenv("VALR_API_SECRET", "")
        
        # Trading Configuration
        self.TRADING_PAIRS = os.getenv("TRADING_PAIRS", "BTCZAR,ETHZAR,ADAUSD,DOTUSD").split(",")
        self.TRADING_PAIRS = [pair.strip() for pair in self.TRADING_PAIRS if pair.strip()]
        
        self.RSI_THRESHOLD = float(os.getenv("RSI_THRESHOLD", "45.0"))
        self.TAKE_PROFIT_PERCENTAGE = float(os.getenv("TAKE_PROFIT_PERCENTAGE", "1.5"))
        self.STOP_LOSS_PERCENTAGE = float(os.getenv("STOP_LOSS_PERCENTAGE", "2.0"))
        self.ORDER_TIMEOUT_MINUTES = int(os.getenv("ORDER_TIMEOUT_MINUTES", "60"))
        self.BASE_TRADE_AMOUNT = Decimal(os.getenv("BASE_TRADE_AMOUNT", "100.0"))
        
        # Risk Management
        self.MAX_POSITION_SIZE = Decimal(os.getenv("MAX_POSITION_SIZE", "1000.0"))
        self.MAX_DAILY_TRADES = int(os.getenv("MAX_DAILY_TRADES", "20"))
        
        # Retry & Resilience
        self.MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
        self.RETRY_BACKOFF_FACTOR = float(os.getenv("RETRY_BACKOFF_FACTOR", "2.0"))
        self.REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
        self.RATE_LIMIT_REQUESTS_PER_MINUTE = int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "600"))
        
        # Logging Configuration
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
        self.LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", "logs/valr_bot.log")
        self.LOG_MAX_SIZE_MB = int(os.getenv("LOG_MAX_SIZE_MB", "10"))
        self.LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))
        
        # Order Persistence
        self.ORDERS_FILE_PATH = os.getenv("ORDERS_FILE_PATH", "data/orders.json")
        self.ENABLE_ORDER_PERSISTENCE = os.getenv("ENABLE_ORDER_PERSISTENCE", "true").lower() == "true"
    
    def _validate_config(self) -> None:
        """Validate configuration values."""
        errors = []
        
        # Required API credentials
        if not self.VALR_API_KEY:
            errors.append("VALR_API_KEY is required")
        if not self.VALR_API_SECRET:
            errors.append("VALR_API_SECRET is required")
        
        # Trading configuration validation
        if not self.TRADING_PAIRS:
            errors.append("At least one trading pair is required")
        
        if not 0 < self.RSI_THRESHOLD < 100:
            errors.append("RSI_THRESHOLD must be between 0 and 100")
        
        if self.TAKE_PROFIT_PERCENTAGE <= 0:
            errors.append("TAKE_PROFIT_PERCENTAGE must be positive")
        
        if self.STOP_LOSS_PERCENTAGE <= 0:
            errors.append("STOP_LOSS_PERCENTAGE must be positive")
        
        if self.ORDER_TIMEOUT_MINUTES <= 0:
            errors.append("ORDER_TIMEOUT_MINUTES must be positive")
        
        if self.BASE_TRADE_AMOUNT <= 0:
            errors.append("BASE_TRADE_AMOUNT must be positive")
        
        # Risk management validation
        if self.MAX_POSITION_SIZE <= 0:
            errors.append("MAX_POSITION_SIZE must be positive")
        
        if self.MAX_DAILY_TRADES <= 0:
            errors.append("MAX_DAILY_TRADES must be positive")
        
        # Retry configuration validation
        if self.MAX_RETRIES < 0:
            errors.append("MAX_RETRIES must be non-negative")
        
        if self.RETRY_BACKOFF_FACTOR <= 1:
            errors.append("RETRY_BACKOFF_FACTOR must be greater than 1")
        
        if self.REQUEST_TIMEOUT <= 0:
            errors.append("REQUEST_TIMEOUT must be positive")
        
        if self.RATE_LIMIT_REQUESTS_PER_MINUTE <= 0:
            errors.append("RATE_LIMIT_REQUESTS_PER_MINUTE must be positive")
        
        # Logging configuration validation
        valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.LOG_LEVEL not in valid_log_levels:
            errors.append(f"LOG_LEVEL must be one of: {valid_log_levels}")
        
        if errors:
            raise ConfigError(f"Configuration validation failed: {'; '.join(errors)}")
    
    def get_pair_decimals(self, pair: str) -> int:
        """Get decimal precision for a trading pair."""
        return self.PAIR_DECIMALS.get(pair, 6)  # Default to 6 decimals
    
    def create_directories(self) -> None:
        """Create necessary directories for logs and data."""
        # Create log directory
        log_dir = Path(self.LOG_FILE_PATH).parent
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # Create data directory
        data_dir = Path(self.ORDERS_FILE_PATH).parent
        data_dir.mkdir(parents=True, exist_ok=True)
    
    def __str__(self) -> str:
        """String representation of configuration (excluding sensitive data)."""
        return f"""
        Configuration:
        Trading Pairs: {', '.join(self.TRADING_PAIRS)}
        RSI Threshold: {self.RSI_THRESHOLD}
        Take Profit: {self.TAKE_PROFIT_PERCENTAGE}%
        Stop Loss: {self.STOP_LOSS_PERCENTAGE}%
        Base Trade Amount: {self.BASE_TRADE_AMOUNT}
        Max Position Size: {self.MAX_POSITION_SIZE}
        Max Daily Trades: {self.MAX_DAILY_TRADES}
        Order Timeout: {self.ORDER_TIMEOUT_MINUTES} minutes
        Max Retries: {self.MAX_RETRIES}
        Request Timeout: {self.REQUEST_TIMEOUT}s
        Log Level: {self.LOG_LEVEL}
        Order Persistence: {self.ENABLE_ORDER_PERSISTENCE}
        """


# Global configuration instance
config = Config()