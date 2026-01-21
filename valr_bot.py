"""
Main orchestration module for VALR mean reversion trading bot.
Coordinates all components and implements the main trading loop.
"""

import signal
import sys
import time
from datetime import datetime, timedelta
from typing import Optional
import os
import threading
from pathlib import Path

from config import Config, ConfigError
from logging_setup import setup_logging, get_logger
from valr_api import VALRAPI, VALRAPIError, VALRConnectionError
from rsi_scanner import RSIScanner
from trading_engine import VALRTradingEngine
from order_persistence import initialize_order_persistence


class VALRTradingBot:
    """Main VALR trading bot orchestrator."""
    
    def __init__(self, config_file: Optional[str] = None):
        """Initialize the trading bot."""
        self.config = None
        self.api = None
        self.scanner = None
        self.trading_engine = None
        self.logger = None
        self.running = False
        self.scan_interval_seconds = 300  # 5 minutes between full scans
        self.monitor_interval_seconds = 60  # 1 minute between position monitoring
        
        # Signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.running = False
    
    def initialize(self) -> None:
        """Initialize all components of the trading bot."""
        try:
            # Load and validate configuration
            self.config = Config()
            self.config.create_directories()
            
            # Setup logging
            self.logger = setup_logging(self.config).get_logger()
            self.logger.info("Starting VALR Trading Bot initialization...")
            
            # Initialize order persistence
            self.order_persistence = initialize_order_persistence(self.config)
            
            # Initialize VALR API client
            self.api = VALRAPI(self.config)
            
            # Test API connection
            self.logger.info("Testing VALR API connection...")
            server_time = self.api.get_server_time()
            self.logger.info(f"VALR server time: {server_time}")
            
            # Initialize RSI scanner
            self.scanner = RSIScanner(self.api, self.config)
            
            # Initialize trading engine
            self.trading_engine = VALRTradingEngine(self.api, self.config)
            
            self.logger.info("VALR Trading Bot initialization complete")
            self.logger.info(f"Trading pairs: {', '.join(self.config.TRADING_PAIRS)}")
            self.logger.info(f"RSI threshold: {self.config.RSI_THRESHOLD}")
            self.logger.info(f"Take profit: {self.config.TAKE_PROFIT_PERCENTAGE}%")
            self.logger.info(f"Stop loss: {self.config.STOP_LOSS_PERCENTAGE}%")
            
        except ConfigError as e:
            self.logger.error(f"Configuration error: {e}")
            raise
        except VALRConnectionError as e:
            self.logger.error(f"Failed to connect to VALR API: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Failed to initialize trading bot: {e}")
            raise
    
    def run(self) -> None:
        """Run the main trading bot loop."""
        if not self.config:
            raise RuntimeError("Bot not initialized. Call initialize() first.")
        
        self.running = True
        self.logger.info("Starting VALR Trading Bot main loop...")
        
        last_scan_time = datetime.now() - timedelta(seconds=self.scan_interval_seconds)
        last_monitor_time = datetime.now() - timedelta(seconds=self.monitor_interval_seconds)
        
        try:
            while self.running:
                current_time = datetime.now()
                
                # Position monitoring (more frequent)
                if (current_time - last_monitor_time).total_seconds() >= self.monitor_interval_seconds:
                    self._monitor_positions()
                    last_monitor_time = current_time
                
                # RSI scanning (less frequent to respect API limits)
                if (current_time - last_scan_time).total_seconds() >= self.scan_interval_seconds:
                    self._perform_rsi_scan()
                    last_scan_time = current_time
                
                # Cleanup old orders periodically
                if current_time.hour == 0 and current_time.minute < 5:  # Run once daily at midnight
                    self._cleanup_old_orders()
                
                # Brief sleep to prevent tight loops
                time.sleep(5)
                
        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received")
        except Exception as e:
            self.logger.error(f"Error in main loop: {e}")
            raise
        finally:
            self._shutdown()
    
    def _perform_rsi_scan(self) -> None:
        """Perform RSI scanning and execute trades on oversold conditions."""
        try:
            self.logger.info("Starting RSI scan...")
            
            # Perform RSI scan
            scan_results = self.scanner.scan_pairs()
            
            # Process oversold signals
            for result in scan_results:
                if result.get("is_oversold") and result.get("rsi_value") is not None:
                    pair = result["pair"]
                    rsi_value = result["rsi_value"]
                    
                    self.logger.info(
                        f"Oversold signal for {pair}: RSI={rsi_value:.2f} "
                        f"(threshold: {self.config.RSI_THRESHOLD})"
                    )
                    
                    # Execute trade setup
                    entry_order_id = self.trading_engine.execute_trade_setup(pair, rsi_value)
                    
                    if entry_order_id:
                        self.logger.info(
                            f"Trade setup initiated for {pair}: Order ID {entry_order_id}"
                        )
                    else:
                        self.logger.warning(f"Failed to initiate trade for {pair}")
                
                time.sleep(0.5)  # Small delay between pairs
            
            # Log scan statistics
            oversold_count = sum(1 for r in scan_results if r.get("is_oversold", False))
            self.logger.info(f"RSI scan complete: {oversold_count} oversold signals found")
            
        except Exception as e:
            self.logger.error(f"Error during RSI scan: {e}")
    
    def _monitor_positions(self) -> None:
        """Monitor open positions and check for exit conditions."""
        try:
            self.trading_engine.monitor_positions()
            
            # Log trading statistics periodically
            stats = self.trading_engine.get_trading_statistics()
            if stats["open_positions"] > 0 or stats["trades_today"] > 0:
                self.logger.info(
                    f"Trading stats: {stats['trades_today']}/{stats['max_daily_trades']} trades, "
                    f"{stats['open_positions']} open positions"
                )
            
        except Exception as e:
            self.logger.error(f"Error monitoring positions: {e}")
    
    def _cleanup_old_orders(self) -> None:
        """Cleanup old order records."""
        try:
            self.order_persistence.cleanup_old_orders(max_age_hours=24)
            
            # Log persistence statistics
            stats = self.order_persistence.get_statistics()
            self.logger.info(f"Order persistence stats: {stats}")
            
        except Exception as e:
            self.logger.error(f"Error cleaning up old orders: {e}")
    
    def _shutdown(self) -> None:
        """Perform graceful shutdown."""
        self.logger.info("Shutting down VALR Trading Bot...")
        
        try:
            # Save any pending orders
            self.order_persistence.save_orders()
            
            # Close API session
            if self.api:
                self.api.__exit__(None, None, None)
            
            self.logger.info("VALR Trading Bot shutdown complete")
            
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")
    
    def get_status(self) -> dict:
        """Get current bot status."""
        if not self.config:
            return {"status": "not_initialized"}
        
        try:
            stats = self.trading_engine.get_trading_statistics() if self.trading_engine else {}
            persistence_stats = self.order_persistence.get_statistics() if self.order_persistence else {}
            
            return {
                "status": "running" if self.running else "stopped",
                "config": {
                    "trading_pairs": self.config.TRADING_PAIRS,
                    "rsi_threshold": self.config.RSI_THRESHOLD,
                    "take_profit_percentage": self.config.TAKE_PROFIT_PERCENTAGE,
                    "stop_loss_percentage": self.config.STOP_LOSS_PERCENTAGE,
                    "base_trade_amount": str(self.config.BASE_TRADE_AMOUNT),
                    "max_daily_trades": self.config.MAX_DAILY_TRADES
                },
                "statistics": stats,
                "order_persistence": persistence_stats,
                "last_scan": self.scanner.get_scan_statistics() if self.scanner else {}
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }


def main():
    """Main entry point."""
    # Get config file path from environment or use default
    config_file = os.getenv("VALR_CONFIG_FILE")
    
    try:
        # Create and run bot
        bot = VALRTradingBot(config_file)
        bot.initialize()
        bot.run()
        
    except KeyboardInterrupt:
        print("\nBot stopped by user")
        sys.exit(0)
    except ConfigError as e:
        print(f"Configuration error: {e}")
        sys.exit(1)
    except VALRConnectionError as e:
        print(f"Connection error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()