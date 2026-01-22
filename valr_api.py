"""VALR API client with comprehensive error handling, retry logic, and rate limiting.

Implements signature-based authentication and connection pooling.
"""

import time
import hmac
import hashlib
import json
from decimal import Decimal
from typing import Dict, List, Optional, Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import Config
from logging_setup import get_logger, get_valr_logger


class VALRAPIError(Exception):
    """Base exception for VALR API errors."""


class VALRAPIErrorCode(VALRAPIError):
    """VALR API error with specific error code."""

    def __init__(self, message: str, error_code: Optional[str] = None, status_code: Optional[int] = None):
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code


class VALRRateLimitError(VALRAPIError):
    """Raised when rate limit is exceeded."""


class VALRConnectionError(VALRAPIError):
    """Raised when connection fails."""


class VALRAPIResponse:
    """Wrapper for VALR API responses."""

    def __init__(self, data: Any, status_code: int, headers: Dict[str, str]):
        self.data = data
        self.status_code = status_code
        self.headers = headers

    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def is_rate_limited(self) -> bool:
        return self.status_code == 429

    def get_error_message(self) -> str:
        if isinstance(self.data, dict):
            return self.data.get("message", self.data.get("error", "Unknown error"))
        return str(self.data)


class VALRRateLimiter:
    """Rate limiter for VALR API calls."""

    def __init__(self, max_requests_per_minute: int):
        self.max_requests = max_requests_per_minute
        self.requests: List[float] = []
        self.logger = get_logger("rate_limiter")

    def wait_if_needed(self) -> None:
        now = time.time()
        self.requests = [req_time for req_time in self.requests if now - req_time < 60]

        if len(self.requests) >= self.max_requests:
            oldest_request = min(self.requests)
            wait_time = 60 - (now - oldest_request) + 0.1
            if wait_time > 0:
                self.logger.debug(f"Rate limit reached, waiting {wait_time:.2f} seconds")
                time.sleep(wait_time)
                self.requests = [req_time for req_time in self.requests if now - req_time < 60]

        self.requests.append(now)


class VALRAPI:
    """VALR API client with comprehensive error handling and retry logic."""

    def __init__(self, config: Config):
        self.config = config
        self.logger = get_logger("valr_api")
        self.valr_logger = get_valr_logger()

        self.session = requests.Session()
        retry_strategy = Retry(
            total=config.MAX_RETRIES,
            backoff_factor=config.RETRY_BACKOFF_FACTOR,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.rate_limiter = VALRRateLimiter(config.RATE_LIMIT_REQUESTS_PER_MINUTE)

        self.base_url = f"{config.VALR_BASE_URL}/{config.VALR_API_VERSION}"

    def _generate_signature(self, timestamp: str, method: str, path: str, body: Optional[str] = None) -> str:
        message = timestamp + method.upper() + path + (body or "")
        secret_bytes = self.config.VALR_API_SECRET.encode("utf-8")
        message_bytes = message.encode("utf-8")
        return hmac.new(secret_bytes, message_bytes, hashlib.sha512).hexdigest()

    def _make_request(
        self, method: str, endpoint: str, data: Optional[Dict] = None, params: Optional[Dict] = None
    ) -> VALRAPIResponse:
        url = f"{self.base_url}{endpoint}"
        path = f"/{self.config.VALR_API_VERSION}{endpoint}"

        # For VALR API, DELETE requests send body as JSON, not as query params
        # For GET requests, use params; for POST/PUT/DELETE, use data
        if method.upper() == "GET":
            body = ""
        else:
            # For POST, PUT, DELETE: send data as JSON body
            body = json.dumps(data) if data else ""
            params = None  # VALR API doesn't use params for non-GET requests

        timestamp = str(int(time.time() * 1000))
        signature = self._generate_signature(timestamp, method, path, body)

        headers = {
            "X-VALR-API-KEY": self.config.VALR_API_KEY,
            "X-VALR-SIGNATURE": signature,
            "X-VALR-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }

        self.rate_limiter.wait_if_needed()

        start_time = time.time()
        last_exception: Optional[Exception] = None

        for attempt in range(self.config.MAX_RETRIES + 1):
            try:
                self.logger.debug(f"Making {method} request to {endpoint} (attempt {attempt + 1})")

                response = self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    data=body if body else None,
                    params=params,
                    timeout=self.config.REQUEST_TIMEOUT,
                )

                response_time = time.time() - start_time
                self.valr_logger.log_api_call(
                    endpoint=path,
                    method=method,
                    status_code=response.status_code,
                    response_time=response_time,
                )

                try:
                    # Handle DELETE requests that may return 204 No Content or 202 Accepted
                    if response.status_code in (204, 202) and not response.content:
                        response_data = {"success": True}
                    else:
                        response_data: Any = response.json() if response.content else {}
                except json.JSONDecodeError as e:
                    # DELETE requests may return 204/202 without body, which is fine
                    if response.status_code in (204, 202):
                        response_data = {"success": True}
                    else:
                        self.logger.error(f"Failed to parse JSON response: {e}")
                        response_data = {"error": "Invalid JSON response"}

                api_response = VALRAPIResponse(
                    data=response_data,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                )

                if api_response.is_rate_limited():
                    if attempt < self.config.MAX_RETRIES:
                        wait_time = 2**attempt * self.config.RETRY_BACKOFF_FACTOR
                        self.logger.warning(f"Rate limited, waiting {wait_time}s before retry")
                        time.sleep(wait_time)
                        continue
                    raise VALRRateLimitError(f"Rate limit exceeded after {self.config.MAX_RETRIES} retries")

                if not api_response.is_success():
                    error_msg = api_response.get_error_message()
                    error_code = response_data.get("code") if isinstance(response_data, dict) else None
                    raise VALRAPIErrorCode(
                        f"API error: {error_msg}",
                        error_code=error_code,
                        status_code=response.status_code,
                    )

                return api_response

            except requests.exceptions.RequestException as e:
                last_exception = e
                self.logger.warning(f"Request failed (attempt {attempt + 1}): {e}")

                if attempt < self.config.MAX_RETRIES:
                    wait_time = 2**attempt * self.config.RETRY_BACKOFF_FACTOR
                    self.logger.debug(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue

                raise VALRConnectionError(f"Failed to connect after {self.config.MAX_RETRIES} retries: {e}")

        raise VALRConnectionError(f"Failed to connect: {last_exception}")

    def _make_request_with_fallback(
        self, method: str, endpoints: List[str], data: Optional[Dict] = None, params: Optional[Dict] = None
    ) -> VALRAPIResponse:
        last_404: Optional[VALRAPIErrorCode] = None

        for endpoint in endpoints:
            try:
                return self._make_request(method, endpoint, data=data, params=params)
            except VALRAPIErrorCode as e:
                if e.status_code == 404:
                    last_404 = e
                    continue
                raise

        if last_404 is not None:
            raise last_404
        raise VALRAPIError("No endpoints provided")

    def get_server_time(self) -> int:
        """Health check using account balance API.

        For scalp trading, we verify connectivity and authentication
        by checking account balances, then return current timestamp.
        """

        try:
            self.get_account_balances()
            return int(time.time() * 1000)
        except Exception:
            # Still return time even if balance check fails
            return int(time.time() * 1000)

    def get_account_balances(self) -> Dict[str, Decimal]:
        response = self._make_request_with_fallback("GET", ["/account/balances"])  # v1 prefix handled by base_url

        raw = response.data
        if isinstance(raw, dict):
            items = raw.get("balances") or raw.get("data") or raw.get("items") or []
        elif isinstance(raw, list):
            items = raw
        else:
            items = []

        balances: Dict[str, Decimal] = {}
        for balance_data in items:
            if not isinstance(balance_data, dict):
                continue
            currency = balance_data.get("currency")
            available_str = balance_data.get("available") or balance_data.get("availableBalance") or "0"
            if not currency:
                continue
            try:
                available = Decimal(str(available_str))
            except Exception:
                available = Decimal("0")
            balances[currency] = available

        self.logger.debug(f"Account balances: {balances}")
        return balances

    def get_pair_summary(self, pair: str) -> Dict[str, Any]:
        """Get trading pair summary using VALR v1 API.

        For scalp trading, we need reliable market data endpoints.
        VALR v1 provides market summaries via public endpoints.
        """

        endpoints = [
            f"/public/{pair}/marketsummary",
            f"/marketsummary/pair/{pair}",
        ]
        response = self._make_request_with_fallback("GET", endpoints)
        return response.data if isinstance(response.data, dict) else {"data": response.data}

    def get_last_traded_price(self, pair: str) -> Decimal:
        summary = self.get_pair_summary(pair)
        for key in [
            "lastTradedPrice",
            "lastTradedPrice",
            "lastPrice",
            "price",
            "last",
        ]:
            if key in summary:
                try:
                    return Decimal(str(summary[key]))
                except Exception:
                    continue

        if "data" in summary and isinstance(summary["data"], dict):
            data = summary["data"]
            for key in ["lastTradedPrice", "lastPrice", "price", "last"]:
                if key in data:
                    return Decimal(str(data[key]))

        raise VALRAPIError(f"Could not extract last traded price for {pair} from response: {summary}")

    def get_order_book(self, pair: str) -> Dict[str, Any]:
        """Get order book for scalp trading entry point selection.
        
        For high-frequency scalp trading, we need real-time bid/ask prices
        to calculate optimal entry prices and quantity calculations.
        """

        # Use the public order book endpoint which should be available
        endpoint = f"/public/{pair}/orderbook"
        
        try:
            response = self._make_request("GET", endpoint)
            return response.data if isinstance(response.data, dict) else {"data": response.data}
        except VALRAPIErrorCode as e:
            if e.status_code != 404:
                raise
                
        # Fallback to generic orderbook with pair parameter
        endpoint = "/public/orderbook"
        response = self._make_request_with_fallback("GET", [endpoint], params={"pair": pair})
        return response.data if isinstance(response.data, dict) else {"data": response.data}

    def place_limit_order(self, pair: str, side: str, quantity: str, price: str, post_only: bool = True) -> Dict[str, Any]:
        """Place limit order optimized for scalp trading.

        For scalp trading with R30 trades:
        - Entry orders use postOnly=True for maker fees (0.18%)
        - Exit orders (TP/SL) use postOnly=False for immediate execution
        - All orders are LIMIT type for price control

        Endpoint: /v1/orders/limit (verified from official VALR documentation)
        """
        side_normalized = side.upper()

        # Use the correct endpoint for limit orders per VALR API docs
        endpoint = "/orders/limit"

        # Build payload according to VALR API specification
        payload = {
            "pair": pair,
            "side": side_normalized,
            "quantity": quantity,
            "price": price,
            "postOnly": post_only,
            "timeInForce": "GTC"  # Good Till Cancel
        }

        try:
            self.logger.info(f"Placing {side_normalized} order: {quantity} {pair} @ {price} (postOnly={post_only})")
            response = self._make_request("POST", endpoint, data=payload)
            order_result = response.data if isinstance(response.data, dict) else {"data": response.data}

            order_id = order_result.get("id") or order_result.get("orderId") or order_result.get("data", {}).get("id")
            self.valr_logger.log_order_event(
                event_type="PLACED",
                order_id=str(order_id or "unknown"),
                pair=pair,
                side=side_normalized,
                quantity=float(Decimal(quantity)),
                price=float(Decimal(price)),
            )
            return order_result
        except VALRAPIErrorCode as e:
            self.logger.error(f"Failed to place {side_normalized} order: {e}")
            raise

    def place_market_order(self, pair: str, side: str, quantity: str) -> Dict[str, Any]:
        """Place market order for scalp trading emergency exits.

        Market orders are used only for emergency position closing when
        stop loss or take profit orders fail to execute within timeouts.
        Note: Market orders have higher fees (0.35% vs 0.18% maker).

        Endpoint: /v1/orders/market (verified from official VALR documentation)
        """
        side_normalized = side.upper()
        endpoint = "/orders/market"

        payload = {
            "pair": pair,
            "side": side_normalized,
            "quoteAmount": quantity
        }

        try:
            self.logger.info(f"Placing {side_normalized} market order: {quantity} {pair}")
            response = self._make_request("POST", endpoint, data=payload)
            return response.data if isinstance(response.data, dict) else {"data": response.data}
        except VALRAPIErrorCode as e:
            self.logger.error(f"Failed to place {side_normalized} market order: {e}")
            raise

    def cancel_order(self, order_id: str, pair: Optional[str] = None) -> bool:
        """Cancel an order.

        Endpoint: /v1/orders/order (DELETE)
        Body: {"pair": "BTCZAR", "orderId": "xxx"}

        Args:
            order_id: The order ID to cancel
            pair: Trading pair (optional but recommended)

        Returns:
            True if cancellation succeeded
        """
        if pair is None:
            # Try to find the pair from order history if not provided
            self.logger.warning(f"cancel_order called without pair for order {order_id}")
            pair = "BTCZAR"  # Default fallback, but caller should provide this

        endpoint = "/orders/order"
        params = {
            "pair": pair,
            "orderId": order_id
        }

        try:
            response = self._make_request("DELETE", endpoint, data=params)
            self.valr_logger.log_order_event(event_type="CANCELLED", order_id=order_id, pair=pair, side="unknown")
            return response.is_success()
        except VALRAPIErrorCode as e:
            self.logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    def get_order_status(self, order_id: str, pair: Optional[str] = None) -> Dict[str, Any]:
        """Get order status.

        Endpoint: /v1/orders/{symbol}/orderid/{order_id} (GET)

        Args:
            order_id: The order ID to check
            pair: Trading pair (required for the endpoint)

        Returns:
            Order status information
        """
        if pair is None:
            raise ValueError("pair is required for get_order_status endpoint")

        endpoint = f"/orders/{pair}/orderid/{order_id}"
        response = self._make_request("GET", endpoint)
        return response.data if isinstance(response.data, dict) else {"data": response.data}

    def get_order_history(self, pair: Optional[str] = None, limit: int = 100) -> List[Dict]:
        params: Dict[str, Any] = {"limit": limit}
        if pair:
            params["pair"] = pair

        response = self._make_request_with_fallback("GET", ["/orders/history"], params=params)
        raw = response.data

        if isinstance(raw, dict):
            items = raw.get("orders") or raw.get("data") or raw.get("items") or []
        elif isinstance(raw, list):
            items = raw
        else:
            items = []

        return [item for item in items if isinstance(item, dict)]

    def get_trade_history(self, pair: Optional[str] = None, limit: int = 100) -> List[Dict]:
        params: Dict[str, Any] = {"limit": limit}
        if pair:
            params["pair"] = pair

        response = self._make_request_with_fallback("GET", ["/orders/tradehistory"], params=params)
        raw = response.data

        if isinstance(raw, dict):
            items = raw.get("trades") or raw.get("data") or raw.get("items") or []
        elif isinstance(raw, list):
            items = raw
        else:
            items = []

        return [item for item in items if isinstance(item, dict)]

    def get_order_fills(self, order_id: str) -> List[Dict]:
        response = self._make_request_with_fallback("GET", [f"/orders/{order_id}/fills"])
        raw = response.data

        if isinstance(raw, dict):
            items = raw.get("fills") or raw.get("data") or raw.get("items") or []
        elif isinstance(raw, list):
            items = raw
        else:
            items = []

        return [item for item in items if isinstance(item, dict)]

    def get_recent_trades(self, pair: str, limit: int = 100) -> List[Dict]:
        """Get recent trades for a trading pair.
        
        Used for aggregating 1-minute candles for RSI calculation.
        Returns up to 100 recent trades (VALR API default).
        
        Args:
            pair: Trading pair (e.g., "BTCZAR")
            limit: Maximum number of trades to fetch (default 100)
            
        Returns:
            List of trade dictionaries with keys: price, quantity, tradedAt, etc.
        """
        endpoint = f"/public/{pair}/trades"
        
        try:
            response = self._make_request("GET", endpoint)
            raw = response.data
            
            if isinstance(raw, list):
                return raw[:limit]
            elif isinstance(raw, dict):
                items = raw.get("trades") or raw.get("data") or raw.get("items") or []
                return items[:limit] if isinstance(items, list) else []
            
            return []
        except Exception as e:
            self.logger.warning(f"Failed to fetch recent trades for {pair}: {e}")
            return []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self, "session"):
            self.session.close()
