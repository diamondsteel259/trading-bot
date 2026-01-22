"""Configuration management for VALR trading bot.

Handles loading and validation of environment variables.
"""

import os
from decimal import Decimal
from typing import Dict, List
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


class ConfigError(Exception):
    """Raised when configuration validation fails."""


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

    # Scalp-specific timing
    ENTRY_ORDER_TIMEOUT_SECONDS: int
    EXIT_ORDER_TIMEOUT_MINUTES: int
    POSITION_TIMEOUT_MINUTES: int

    SCAN_INTERVAL_SECONDS: int
    POSITION_MONITOR_INTERVAL_SECONDS: int
    RSI_PAIR_COOLDOWN_SECONDS: int

    # Amounts / fees
    BASE_TRADE_AMOUNT: Decimal
    MAKER_FEE_PERCENT: Decimal
    TAKER_FEE_PERCENT: Decimal

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

    # Pair-specific precision (matches VALR tick sizes for order placement)
    PAIR_PRICE_DECIMALS: Dict[str, int] = {
        "BTCZAR": 0,     # Tick size: 1 (whole numbers)
        "ETHZAR": 0,     # Tick size: 1 (whole numbers)
        "XRPZAR": 2,     # Tick size: 0.01
        "ADAZAR": 4,     # Tick size: 0.0001
        "SOLZAR": 0,     # Tick size: 1 (whole numbers)
        "DOTZAR": 2,     # Tick size: 0.01
        "LINKZAR": 2,    # Tick size: 0.01
        "LTCZAR": 1,     # Tick size: 0.1
        "BCHZAR": 0,     # Tick size: 1 (whole numbers)
        "AVAXZAR": 2,    # Tick size: 0.01
        "DOGEZAR": 4,    # Tick size: 0.0001
        "SHIBZAR": 8,    # Tick size: 0.00000001
        "BNBZAR": 0,     # Tick size: 1 (whole numbers)
        "TRXZAR": 4,     # Tick size: 0.0001
        "USDTZAR": 2,    # Tick size: 0.01
        "XLMZAR": 4,     # Tick size: 0.0001
        "XAUTZAR": 0,    # Tick size: 1 (whole numbers)
        "BTCUSDT": 2,
        "ETHUSDT": 2,
    }

    PAIR_QUANTITY_DECIMALS: Dict[str, int] = {
        "BTCZAR": 8,
        "ETHZAR": 6,
        "XRPZAR": 2,
        "ADAZAR": 2,
        "SOLZAR": 4,
        "DOTZAR": 4,
        "LINKZAR": 4,
        "LTCZAR": 4,
        "BCHZAR": 4,
        "AVAXZAR": 4,
        "DOGEZAR": 0,
        "SHIBZAR": 0,
        "BTCUSDT": 8,
        "ETHUSDT": 6,
    }

    # Tick sizes (minimum price increment) for each pair
    PAIR_TICK_SIZES = {
        "BTCZAR": "1",
        "ETHZAR": "1",
        "SOLZAR": "1",
        "BNBZAR": "1",
        "AVAXZAR": "0.1",
        "LTCZAR": "0.1",
        "XRPZAR": "0.01",
        "USDTZAR": "0.01",
        "ADAZAR": "0.001",
        "XLMZAR": "0.001",
        "DOGEZAR": "0.00001",
        "SHIBZAR": "0.0000001",
        "TRXZAR": "0.0001",
        "LINKZAR": "0.01",
        "XAUTZAR": "1",
        "BCHZAR": "1",
        "DEFAULT": "0.01"
    }

    def __init__(self):
        self._load_from_env()
        self._validate_config()

    def _load_from_env(self) -> None:
        # VALR API Configuration
        self.VALR_API_KEY = os.getenv("VALR_API_KEY", "")
        self.VALR_API_SECRET = os.getenv("VALR_API_SECRET", "")

        # Trading Configuration
        self.TRADING_PAIRS = os.getenv("TRADING_PAIRS", "BTCZAR,ETHZAR,XRPZAR,ADAZAR").split(",")
        self.TRADING_PAIRS = [pair.strip() for pair in self.TRADING_PAIRS if pair.strip()]

        self.RSI_THRESHOLD = float(os.getenv("RSI_THRESHOLD", "45.0"))
        self.TAKE_PROFIT_PERCENTAGE = float(os.getenv("TAKE_PROFIT_PERCENTAGE", "1.5"))
        self.STOP_LOSS_PERCENTAGE = float(os.getenv("STOP_LOSS_PERCENTAGE", "2.0"))

        # Scalp-specific timing
        self.ENTRY_ORDER_TIMEOUT_SECONDS = int(os.getenv("ENTRY_ORDER_TIMEOUT_SECONDS", "60"))
        self.EXIT_ORDER_TIMEOUT_MINUTES = int(os.getenv("EXIT_ORDER_TIMEOUT_MINUTES", "10"))
        self.POSITION_TIMEOUT_MINUTES = int(os.getenv("POSITION_TIMEOUT_MINUTES", "30"))

        self.SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "60"))
        self.POSITION_MONITOR_INTERVAL_SECONDS = int(os.getenv("POSITION_MONITOR_INTERVAL_SECONDS", "5"))
        self.RSI_PAIR_COOLDOWN_SECONDS = int(os.getenv("RSI_PAIR_COOLDOWN_SECONDS", "20"))

        # Amounts / fees
        self.BASE_TRADE_AMOUNT = Decimal(os.getenv("BASE_TRADE_AMOUNT", "30.0"))
        self.MAKER_FEE_PERCENT = Decimal(os.getenv("MAKER_FEE_PERCENT", "0.18"))
        self.TAKER_FEE_PERCENT = Decimal(os.getenv("TAKER_FEE_PERCENT", "0.35"))

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
        errors = []

        if not self.VALR_API_KEY:
            errors.append("VALR_API_KEY is required")
        if not self.VALR_API_SECRET:
            errors.append("VALR_API_SECRET is required")

        if not self.TRADING_PAIRS:
            errors.append("At least one trading pair is required")

        if not 0 < self.RSI_THRESHOLD < 100:
            errors.append("RSI_THRESHOLD must be between 0 and 100")

        if self.TAKE_PROFIT_PERCENTAGE <= 0:
            errors.append("TAKE_PROFIT_PERCENTAGE must be positive")

        if self.STOP_LOSS_PERCENTAGE <= 0:
            errors.append("STOP_LOSS_PERCENTAGE must be positive")

        if self.BASE_TRADE_AMOUNT <= 0:
            errors.append("BASE_TRADE_AMOUNT must be positive")

        if self.ENTRY_ORDER_TIMEOUT_SECONDS <= 0:
            errors.append("ENTRY_ORDER_TIMEOUT_SECONDS must be positive")

        if self.EXIT_ORDER_TIMEOUT_MINUTES <= 0:
            errors.append("EXIT_ORDER_TIMEOUT_MINUTES must be positive")

        if self.POSITION_TIMEOUT_MINUTES <= 0:
            errors.append("POSITION_TIMEOUT_MINUTES must be positive")

        if self.SCAN_INTERVAL_SECONDS <= 0:
            errors.append("SCAN_INTERVAL_SECONDS must be positive")

        if self.POSITION_MONITOR_INTERVAL_SECONDS <= 0:
            errors.append("POSITION_MONITOR_INTERVAL_SECONDS must be positive")

        if self.RSI_PAIR_COOLDOWN_SECONDS < 0:
            errors.append("RSI_PAIR_COOLDOWN_SECONDS must be non-negative")

        if self.MAX_POSITION_SIZE <= 0:
            errors.append("MAX_POSITION_SIZE must be positive")

        if self.MAX_DAILY_TRADES <= 0:
            errors.append("MAX_DAILY_TRADES must be positive")

        if self.MAX_RETRIES < 0:
            errors.append("MAX_RETRIES must be non-negative")

        if self.RETRY_BACKOFF_FACTOR <= 1:
            errors.append("RETRY_BACKOFF_FACTOR must be greater than 1")

        if self.REQUEST_TIMEOUT <= 0:
            errors.append("REQUEST_TIMEOUT must be positive")

        if self.RATE_LIMIT_REQUESTS_PER_MINUTE <= 0:
            errors.append("RATE_LIMIT_REQUESTS_PER_MINUTE must be positive")

        valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.LOG_LEVEL not in valid_log_levels:
            errors.append(f"LOG_LEVEL must be one of: {valid_log_levels}")

        if errors:
            raise ConfigError(f"Configuration validation failed: {'; '.join(errors)}")

    def get_pair_price_decimals(self, pair: str) -> int:
        return self.PAIR_PRICE_DECIMALS.get(pair, 2)

    def get_pair_quantity_decimals(self, pair: str) -> int:
        return self.PAIR_QUANTITY_DECIMALS.get(pair, 8)

    def get_pair_decimals(self, pair: str) -> int:
        return self.get_pair_price_decimals(pair)

    def get_pair_tick_size(self, pair: str) -> str:
        """Get tick size (minimum price increment) for a trading pair."""
        return self.PAIR_TICK_SIZES.get(pair, self.PAIR_TICK_SIZES["DEFAULT"])

    def create_directories(self) -> None:
        log_dir = Path(self.LOG_FILE_PATH).parent
        log_dir.mkdir(parents=True, exist_ok=True)

        data_dir = Path(self.ORDERS_FILE_PATH).parent
        data_dir.mkdir(parents=True, exist_ok=True)

    def __str__(self) -> str:
        return f"""
        Configuration:
        Trading Pairs: {', '.join(self.TRADING_PAIRS)}
        RSI Threshold: {self.RSI_THRESHOLD}
        Take Profit: {self.TAKE_PROFIT_PERCENTAGE}%
        Stop Loss: {self.STOP_LOSS_PERCENTAGE}%
        Base Trade Amount (quote): {self.BASE_TRADE_AMOUNT}
        Entry Timeout: {self.ENTRY_ORDER_TIMEOUT_SECONDS}s
        Exit Orders Timeout: {self.EXIT_ORDER_TIMEOUT_MINUTES}m
        Position Timeout: {self.POSITION_TIMEOUT_MINUTES}m
        Scan Interval: {self.SCAN_INTERVAL_SECONDS}s
        Monitor Interval: {self.POSITION_MONITOR_INTERVAL_SECONDS}s
        Max Position Size: {self.MAX_POSITION_SIZE}
        Max Daily Trades: {self.MAX_DAILY_TRADES}
        Max Retries: {self.MAX_RETRIES}
        Request Timeout: {self.REQUEST_TIMEOUT}s
        Log Level: {self.LOG_LEVEL}
        Order Persistence: {self.ENABLE_ORDER_PERSISTENCE}
        """


config = Config()
