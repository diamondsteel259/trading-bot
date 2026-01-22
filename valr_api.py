"""
VALR API client with comprehensive error handling, retry logic, and rate limiting.
Implements signature-based authentication and connection pooling.
"""

import time
import hmac
import hashlib
import json
from decimal import Decimal
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import Config
from logging_setup import get_logger, get_valr_logger
from decimal_utils import DecimalUtils


class VALRAPIError(Exception):
    """Base exception for VALR API errors."""
    pass


class VALRAPIErrorCode(VALRAPIError):
    """VALR API error with specific error code."""
    
    def __init__(self, message: str, error_code: Optional[str] = None, status_code: Optional[int] = None):
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code


class VALRRateLimitError(VALRAPIError):
    """Raised when rate limit is exceeded."""
    pass


class VALRConnectionError(VALRAPIError):
    """Raised when connection fails."""
    pass


class VALRAPIResponse:
    """Wrapper for VALR API responses."""
    
    def __init__(self, data: Dict[str, Any], status_code: int, headers: Dict[str, str]):
        self.data = data
        self.status_code = status_code
        self.headers = headers
    
    def is_success(self) -> bool:
        """Check if response indicates success."""
        return 200 <= self.status_code < 300
    
    def is_rate_limited(self) -> bool:
        """Check if response indicates rate limiting."""
        return self.status_code == 429
    
    def get_error_message(self) -> str:
        """Extract error message from response."""
        if isinstance(self.data, dict):
            return self.data.get('message', self.data.get('error', 'Unknown error'))
        return str(self.data)


class VALRRateLimiter:
    """Rate limiter for VALR API calls."""
    
    def __init__(self, max_requests_per_minute: int):
        self.max_requests = max_requests_per_minute
        self.requests = []
        self.logger = get_logger("rate_limiter")
    
    def wait_if_needed(self) -> None:
        """Wait if approaching rate limit."""
        now = time.time()
        
        # Remove requests older than 1 minute
        self.requests = [req_time for req_time in self.requests if now - req_time < 60]
        
        # If at limit, wait until oldest request expires
        if len(self.requests) >= self.max_requests:
            oldest_request = min(self.requests)
            wait_time = 60 - (now - oldest_request) + 0.1  # Add small buffer
            if wait_time > 0:
                self.logger.debug(f"Rate limit reached, waiting {wait_time:.2f} seconds")
                time.sleep(wait_time)
                # Clean up old requests again
                self.requests = [req_time for req_time in self.requests if now - req_time < 60]
        
        # Record this request
        self.requests.append(now)


class VALRAPI:
    """VALR API client with comprehensive error handling and retry logic."""
    
    def __init__(self, config: Config):
        """Initialize VALR API client."""
        self.config = config
        self.logger = get_logger("valr_api")
        self.valr_logger = get_valr_logger()
        
        # Setup session with connection pooling and retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=config.MAX_RETRIES,
            backoff_factor=config.RETRY_BACKOFF_FACTOR,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"]
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=20
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Rate limiter
        self.rate_limiter = VALRRateLimiter(config.RATE_LIMIT_REQUESTS_PER_MINUTE)
        
        # Base URL
        self.base_url = f"{config.VALR_BASE_URL}/{config.VALR_API_VERSION}"
    
    def _generate_signature(self, timestamp: str, method: str, path: str, 
                          body: Optional[str] = None) -> str:
        """Generate signature for VALR API authentication."""
        message = timestamp + method.upper() + path + (body or "")
        secret_bytes = self.config.VALR_API_SECRET.encode('utf-8')
        message_bytes = message.encode('utf-8')
        
        signature = hmac.new(secret_bytes, message_bytes, hashlib.sha512).hexdigest()
        return signature
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None, 
                     params: Optional[Dict] = None) -> VALRAPIResponse:
        """Make authenticated request to VALR API with retry logic."""
        url = f"{self.base_url}{endpoint}"
        path = f"/{self.config.VALR_API_VERSION}{endpoint}"
        
        # Prepare request data
        body = json.dumps(data) if data else ""
        
        # Generate timestamp and signature
        timestamp = str(int(time.time() * 1000))
        signature = self._generate_signature(timestamp, method, path, body)
        
        # Prepare headers
        headers = {
            'X-VALR-API-KEY': self.config.VALR_API_KEY,
            'X-VALR-API-SIGNATURE': signature,
            'X-VALR-API-TIMESTAMP': timestamp,
            'Content-Type': 'application/json'
        }
        
        # Rate limiting
        self.rate_limiter.wait_if_needed()
        
        # Make request with retry logic
        start_time = time.time()
        last_exception = None
        
        for attempt in range(self.config.MAX_RETRIES + 1):
            try:
                self.logger.debug(f"Making {method} request to {endpoint} (attempt {attempt + 1})")
                
                response = self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    data=body,
                    params=params,
                    timeout=self.config.REQUEST_TIMEOUT
                )
                
                response_time = time.time() - start_time
                
                # Log API call
                self.valr_logger.log_api_call(
                    endpoint=endpoint,
                    method=method,
                    status_code=response.status_code,
                    response_time=response_time
                )
                
                # Parse response
                try:
                    response_data = response.json() if response.content else {}
                except json.JSONDecodeError as e:
                    self.logger.error(f"Failed to parse JSON response: {e}")
                    response_data = {"error": "Invalid JSON response"}
                
                api_response = VALRAPIResponse(
                    data=response_data,
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
                
                # Handle rate limiting
                if api_response.is_rate_limited():
                    if attempt < self.config.MAX_RETRIES:
                        wait_time = 2 ** attempt * self.config.RETRY_BACKOFF_FACTOR
                        self.logger.warning(f"Rate limited, waiting {wait_time}s before retry")
                        time.sleep(wait_time)
                        continue
                    else:
                        raise VALRRateLimitError(f"Rate limit exceeded after {self.config.MAX_RETRIES} retries")
                
                # Handle other HTTP errors
                if not api_response.is_success():
                    error_msg = api_response.get_error_message()
                    raise VALRAPIErrorCode(
                        f"API error: {error_msg}",
                        error_code=response_data.get('code'),
                        status_code=response.status_code
                    )
                
                return api_response
                
            except requests.exceptions.RequestException as e:
                last_exception = e
                self.logger.warning(f"Request failed (attempt {attempt + 1}): {e}")
                
                if attempt < self.config.MAX_RETRIES:
                    wait_time = 2 ** attempt * self.config.RETRY_BACKOFF_FACTOR
                    self.logger.debug(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                else:
                    raise VALRConnectionError(f"Failed to connect after {self.config.MAX_RETRIES} retries: {e}")
        
        # Should never reach here
        raise last_exception
    
    def get_server_time(self) -> int:
        """Get VALR server time."""
        response = self._make_request("GET", "/time")
        return response.data.get('serverTime', 0)
    
    def get_account_balances(self) -> Dict[str, Decimal]:
        """Get account balances."""
        response = self._make_request("GET", "/account/balances")
        balances = {}
        
        for balance_data in response.data.get('balances', []):
            currency = balance_data.get('currency')
            available = Decimal(balance_data.get('available', '0'))
            if available > 0:
                balances[currency] = available
        
        self.logger.debug(f"Account balances: {balances}")
        return balances
    
    def get_pair_summary(self, pair: str) -> Dict[str, Any]:
        """Get trading pair summary."""
        response = self._make_request("GET", f"/marketsummary/pair/{pair}")
        return response.data
    
    def get_order_book(self, pair: str, side: str = "both") -> Dict[str, Any]:
        """Get order book for a trading pair."""
        params = {"pair": pair, "side": side}
        response = self._make_request("GET", "/orderbook", params=params)
        return response.data
    
    def get_rsi_data(self, pair: str, interval: str = "1m", limit: int = 100) -> List[Dict]:
        """Get RSI data for a trading pair."""
        params = {
            "pair": pair,
            "interval": interval,
            "limit": limit
        }
        response = self._make_request("GET", "/marketdata/indicator/rsi", params=params)
        return response.data.get('data', [])
    
    def place_limit_order(self, pair: str, side: str, quantity: str, 
                         price: str, post_only: bool = True) -> Dict[str, Any]:
        """Place a limit order."""
        order_data = {
            "pair": pair,
            "side": side.upper(),
            "quantity": quantity,
            "price": price,
            "type": "POST_ONLY_LIMIT" if post_only else "LIMIT"
        }
        
        self.logger.info(f"Placing {side} order: {quantity} {pair} @ {price}")
        response = self._make_request("POST", "/orders", data=order_data)
        
        order_result = response.data
        self.valr_logger.log_order_event(
            event_type="PLACED",
            order_id=order_result.get('id', 'unknown'),
            pair=pair,
            side=side,
            quantity=Decimal(quantity),
            price=Decimal(price)
        )
        
        return order_result
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        response = self._make_request("DELETE", f"/orders/{order_id}")
        
        self.valr_logger.log_order_event(
            event_type="CANCELLED",
            order_id=order_id,
            pair="unknown",
            side="unknown"
        )
        
        return response.is_success()
    
    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get order status."""
        response = self._make_request("GET", f"/orders/{order_id}")
        return response.data
    
    def get_order_history(self, pair: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Get order history."""
        params = {"limit": limit}
        if pair:
            params["pair"] = pair
            
        response = self._make_request("GET", "/orders/history", params=params)
        return response.data.get('orders', [])
    
    def get_trade_history(self, pair: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Get trade history."""
        params = {"limit": limit}
        if pair:
            params["pair"] = pair
            
        response = self._make_request("GET", "/orders/tradehistory", params=params)
        return response.data.get('trades', [])
    
    def get_order_fills(self, order_id: str) -> List[Dict]:
        """Get fills for an order."""
        response = self._make_request("GET", f"/orders/{order_id}/fills")
        return response.data.get('fills', [])
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup resources."""
        if hasattr(self, 'session'):
            self.session.close()