# VALR Mean Reversion Trading Bot

A production-ready, automated trading bot for the VALR cryptocurrency exchange that implements mean reversion trading strategies using RSI (Relative Strength Index) indicators.

## 🚀 Features

### Core Trading Functionality
- **RSI-Based Signal Detection**: Scans multiple trading pairs for oversold conditions (RSI < threshold)
- **Automated Order Placement**: Places post-only limit orders to minimize trading fees
- **Risk Management**: Implements take-profit (+1.5%), stop-loss (-2.0%), and timeout (60 min) mechanisms
- **Multi-Pair Support**: Monitors up to 12 cryptocurrency trading pairs simultaneously

### Production-Ready Infrastructure
- **Comprehensive Error Handling**: No bare except statements, proper exception hierarchy
- **Retry Logic & Resilience**: Exponential backoff, connection pooling, rate limiting
- **Configuration Management**: Environment variables with validation
- **Structured Logging**: Console and file logging with rotation
- **Order Persistence**: Crash recovery with automatic order tracking
- **Type Hints**: Full type annotations throughout the codebase

### Security & Monitoring
- **API Security**: Signature-based authentication, environment variable storage
- **Balance Verification**: Pre-trade balance checks and position sizing
- **Trade Limits**: Daily trade limits and position size restrictions
- **Monitoring**: Real-time statistics and performance tracking

## 📁 Project Structure

```
valr-trading-bot/
├── config.py                 # Configuration management with validation
├── valr_api.py              # VALR API client with retry logic
├── rsi_scanner.py           # RSI indicator analysis and signal detection
├── trading_engine.py        # Order execution and position management
├── order_persistence.py     # Crash recovery and order tracking
├── logging_setup.py         # Structured logging configuration
├── decimal_utils.py         # Precise monetary calculations
├── valr_bot.py             # Main orchestration and trading loop
├── requirements.txt         # Python dependencies
├── .env.template           # Environment configuration template
└── README.md               # This file
```

## 🛠️ Installation

### Prerequisites
- Python 3.8 or higher
- VALR exchange account with API credentials
- Sufficient account balance for trading

### Setup Instructions

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd valr-trading-bot
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**
   ```bash
   cp .env.template .env
   # Edit .env with your VALR API credentials and preferences
   ```

4. **Validate configuration**
   ```bash
   python -c "from config import Config; Config(); print('Configuration valid!')"
   ```

## ⚙️ Configuration

### Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `VALR_API_KEY` | VALR API key | `your_api_key_here` |
| `VALR_API_SECRET` | VALR API secret | `your_api_secret_here` |

### Optional Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TRADING_PAIRS` | `BTCZAR,ETHZAR,ADAUSD,DOTUSD` | Comma-separated list of pairs to trade |
| `RSI_THRESHOLD` | `45.0` | RSI value below which to consider oversold |
| `TAKE_PROFIT_PERCENTAGE` | `1.5` | Take profit percentage |
| `STOP_LOSS_PERCENTAGE` | `2.0` | Stop loss percentage |
| `BASE_TRADE_AMOUNT` | `100.0` | Base trade amount per position |
| `MAX_DAILY_TRADES` | `20` | Maximum trades per day |
| `LOG_LEVEL` | `INFO` | Logging level |

### Complete Configuration Example

```bash
# VALR API Credentials
VALR_API_KEY=your_actual_api_key
VALR_API_SECRET=your_actual_api_secret

# Trading Settings
TRADING_PAIRS=BTCZAR,ETHZAR,ADAUSD,DOTUSD,LINKUSD
RSI_THRESHOLD=40.0
TAKE_PROFIT_PERCENTAGE=2.0
STOP_LOSS_PERCENTAGE=1.5
BASE_TRADE_AMOUNT=200.0

# Risk Management
MAX_POSITION_SIZE=2000.0
MAX_DAILY_TRADES=30

# Logging
LOG_LEVEL=DEBUG
LOG_FILE_PATH=logs/valr_bot.log
```

## 🚀 Usage

### Basic Usage

1. **Run the bot**
   ```bash
   python valr_bot.py
   ```

2. **Monitor logs**
   ```bash
   tail -f logs/valr_bot.log
   ```

### Advanced Usage

```python
from valr_bot import VALRTradingBot
from config import Config

# Initialize with custom config
bot = VALRTradingBot()
bot.initialize()

# Run for specific duration or until stopped
try:
    bot.run()
except KeyboardInterrupt:
    print("Bot stopped by user")
```

### Programmatic Control

```python
from valr_api import VALRAPI
from rsi_scanner import RSIScanner
from trading_engine import VALRTradingEngine
from config import Config

# Initialize components
config = Config()
api = VALRAPI(config)
scanner = RSIScanner(api, config)
trading_engine = VALRTradingEngine(api, config)

# Perform manual RSI scan
results = scanner.scan_pairs()
oversold_pairs = [r for r in results if r['is_oversold']]

# Execute trade
if oversold_pairs:
    pair = oversold_pairs[0]['pair']
    rsi_value = oversold_pairs[0]['rsi_value']
    entry_order_id = trading_engine.execute_trade_setup(pair, rsi_value)
```

## 📊 Monitoring & Logging

### Log Files

- **Console Output**: Real-time status and trade events
- **File Logging**: `logs/valr_bot.log` with rotation (10MB files, 5 backups)
- **Log Levels**: DEBUG, INFO, WARNING, ERROR, CRITICAL

### Log Events

The bot logs various events with structured data:

- **Trade Events**: Entry orders, take profit, stop loss triggers
- **RSI Scans**: Oversold signals and threshold analysis
- **Order Events**: Placements, fills, cancellations
- **API Calls**: Request/response timing and error handling
- **Position Updates**: PnL calculations and status changes

### Example Log Output

```
2024-01-15 14:30:15 | INFO     | valr_bot | Starting VALR Trading Bot initialization...
2024-01-15 14:30:15 | INFO     | valr_api | API_SUCCESS: {'endpoint': '/v1/account/balances', 'method': 'GET', 'status_code': 200}
2024-01-15 14:30:16 | INFO     | rsi_scanner | RSI_SCAN: {'pair': 'BTCZAR', 'rsi_value': 38.5, 'threshold': 45.0, 'action': 'BUY_SIGNAL'}
2024-01-15 14:30:16 | INFO     | trading_engine | ORDER_EVENT: {'event_type': 'ENTRY_PLACED', 'order_id': '12345', 'pair': 'BTCZAR', 'side': 'buy', 'quantity': 0.001, 'price': 950000}
```

## 🛡️ Risk Management

### Built-in Safeguards

1. **Balance Verification**: Pre-trade balance checks
2. **Position Limits**: Maximum position size restrictions
3. **Daily Limits**: Configurable daily trade limits
4. **Order Timeouts**: Automatic timeout for stale orders
5. **Rate Limiting**: Respects VALR API rate limits
6. **Error Recovery**: Automatic retry with exponential backoff

### Configuration Recommendations

```bash
# Conservative settings for beginners
BASE_TRADE_AMOUNT=50.0
MAX_DAILY_TRADES=10
MAX_POSITION_SIZE=500.0
RSI_THRESHOLD=35.0  # More conservative signals

# Aggressive settings for experienced traders
BASE_TRADE_AMOUNT=200.0
MAX_DAILY_TRADES=50
MAX_POSITION_SIZE=2000.0
RSI_THRESHOLD=45.0  # Standard signals
```

## 🔧 Development

### Running Tests

```bash
# Install development dependencies
pip install pytest pytest-asyncio

# Run tests
pytest tests/
```

### Code Quality

```bash
# Format code
black *.py

# Check types
mypy *.py

# Lint code
flake8 *.py
```

### Adding New Features

1. **New Indicators**: Extend `rsi_scanner.py` for additional technical indicators
2. **Order Types**: Modify `trading_engine.py` to support more order types
3. **Exchange Support**: Create new API client based on `valr_api.py`
4. **Risk Management**: Enhance position management in `trading_engine.py`

## 🐛 Troubleshooting

### Common Issues

1. **Configuration Errors**
   ```
   Configuration validation failed: VALR_API_KEY is required
   ```
   **Solution**: Ensure `.env` file is created with valid API credentials

2. **API Connection Issues**
   ```
   Failed to connect after 3 retries: Connection timeout
   ```
   **Solution**: Check internet connection and VALR API status

3. **Insufficient Balance**
   ```
   Insufficient ZAR balance. Required: 1000.0, Available: Check account balance
   ```
   **Solution**: Ensure sufficient balance in VALR account

4. **Rate Limiting**
   ```
   Rate limit reached, waiting 58.23 seconds
   ```
   **Solution**: Normal behavior - bot will automatically retry

### Debug Mode

Enable detailed logging for troubleshooting:

```bash
LOG_LEVEL=DEBUG python valr_bot.py
```

### Health Checks

```python
# Check bot status
status = bot.get_status()
print(f"Bot status: {status['status']}")
print(f"Active positions: {status['statistics']['open_positions']}")
print(f"Trades today: {status['statistics']['trades_today']}")
```

## 📈 Performance

### Expected Performance

- **Scan Frequency**: Every 5 minutes per pair
- **Order Response**: Within 1-2 seconds for limit orders
- **Memory Usage**: < 100MB typical usage
- **CPU Usage**: < 5% during normal operation
- **Network**: ~600 API requests per minute maximum

### Optimization Tips

1. **Reduce Pairs**: Monitor fewer pairs for lower resource usage
2. **Increase Scan Interval**: Reduce API calls by increasing scan frequency
3. **Batch Operations**: Use single API calls when possible
4. **Local Storage**: Enable order persistence for crash recovery

## ⚠️ Disclaimer

**IMPORTANT**: This trading bot is for educational and experimental purposes. Cryptocurrency trading involves significant risk and you can lose all of your invested capital. Please:

- Never trade more than you can afford to lose
- Start with small amounts to test the bot
- Understand the strategies being employed
- Monitor the bot regularly
- Consider the tax implications of frequent trading

The developers are not responsible for any financial losses incurred through the use of this software.

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📞 Support

For issues, questions, or contributions:

1. Check the [Issues](https://github.com/your-repo/issues) page
2. Review the troubleshooting section above
3. Create a detailed issue report with logs and configuration

## 🔄 Version History

- **v1.0.0**: Initial release with full RSI mean reversion trading
- **v1.1.0**: Added order persistence and crash recovery
- **v1.2.0**: Enhanced error handling and retry logic
- **v2.0.0**: Complete refactor with production-ready infrastructure

---

**Happy Trading! 📈**