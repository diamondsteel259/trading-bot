"""Position recovery from VALR API.

Reconstructs positions by analyzing open orders on VALR exchange.
Used when bot restarts without position persistence data.
"""

from typing import Dict, List, Any, Optional, Tuple
from decimal import Decimal
from datetime import datetime, timezone
from logging_setup import get_logger
from valr_api import VALRAPI


def recover_positions_from_valr(api: VALRAPI) -> List[Dict[str, Any]]:
    """Recover open positions by analyzing orders on VALR.

    Strategy:
    1. Get all open orders from VALR
    2. Group by pair
    3. For each pair, look for TP/SL order pairs (same quantity)
    4. These represent active positions
    5. Reconstruct position data
    """
    logger = get_logger("position_recovery")

    try:
        # Get all open orders from VALR
        open_orders = api.get_open_orders()
        logger.info(f"Fetched {len(open_orders)} open orders from VALR for position recovery")

        if not open_orders:
            return []

        # Group orders by pair
        orders_by_pair: Dict[str, List[Dict]] = {}
        for order in open_orders:
            pair = order.get("currencyPair") or order.get("pair") or ""
            if not pair:
                continue

            if pair not in orders_by_pair:
                orders_by_pair[pair] = []
            orders_by_pair[pair].append(order)

        # Recover positions from order groups
        recovered_positions = []

        for pair, orders in orders_by_pair.items():
            # Look for TP/SL pairs (both SELL orders with same quantity)
            sell_orders = [o for o in orders if (o.get("side") or "").upper() == "SELL"]

            if len(sell_orders) < 2:
                continue  # Need at least 2 sell orders (TP and SL)

            # Try to match TP/SL pairs by quantity
            for i, order1 in enumerate(sell_orders):
                for order2 in sell_orders[i+1:]:
                    qty1 = _extract_quantity(order1)
                    qty2 = _extract_quantity(order2)

                    if qty1 and qty2 and abs(qty1 - qty2) < Decimal("0.00001"):  # Same quantity
                        # Found a TP/SL pair!
                        price1 = _extract_price(order1)
                        price2 = _extract_price(order2)

                        if not price1 or not price2:
                            continue

                        # Higher price is TP, lower is SL
                        if price1 > price2:
                            tp_order, sl_order = order1, order2
                            tp_price, sl_price = price1, price2
                        else:
                            tp_order, sl_order = order2, order1
                            tp_price, sl_price = price2, price1

                        # Calculate entry price from TP/SL
                        # TP is entry * 1.01, SL is entry * 0.98
                        # Solve for entry: entry ≈ TP / 1.01
                        entry_price = tp_price / Decimal("1.01")

                        # Create position object
                        position = {
                            "id": f"{pair}_recovered_{int(datetime.now(timezone.utc).timestamp())}",
                            "pair": pair,
                            "quantity": qty1,
                            "entry_price": entry_price,
                            "stop_loss_price": sl_price,
                            "take_profit_price": tp_price,
                            "created_at": datetime.now(timezone.utc),
                            "entry_filled_at": datetime.now(timezone.utc),
                            "status": "open",
                            "entry_order_id": "recovered",
                            "take_profit_order_id": _extract_order_id(tp_order),
                            "stop_loss_order_id": _extract_order_id(sl_order),
                        }

                        recovered_positions.append(position)
                        logger.info(
                            f"Recovered position: {pair} qty={qty1} entry≈{entry_price:.2f} "
                            f"TP={tp_price} SL={sl_price}"
                        )

                        # Remove these orders from list to avoid duplicate detection
                        sell_orders.remove(order1)
                        sell_orders.remove(order2)
                        break

        if recovered_positions:
            logger.info(f"Successfully recovered {len(recovered_positions)} positions from VALR")
        else:
            logger.info("No positions recovered from VALR open orders")

        return recovered_positions

    except Exception as e:
        logger.error(f"Failed to recover positions from VALR: {e}")
        return []


def _extract_quantity(order: Dict) -> Optional[Decimal]:
    """Extract quantity from order."""
    for key in ["originalQuantity", "quantity", "remainingQuantity", "baseAmount"]:
        if key in order and order[key] is not None:
            try:
                return Decimal(str(order[key]))
            except:
                continue
    return None


def _extract_price(order: Dict) -> Optional[Decimal]:
    """Extract price from order."""
    for key in ["price", "limitPrice", "orderPrice"]:
        if key in order and order[key] is not None:
            try:
                return Decimal(str(order[key]))
            except:
                continue
    return None


def _extract_order_id(order: Dict) -> str:
    """Extract order ID from order."""
    return str(order.get("orderId") or order.get("id") or "")
