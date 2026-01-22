"""
Decimal utilities for precise monetary calculations in VALR trading bot.
Handles currency formatting, rounding, and precision management.
"""

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Union


class DecimalUtils:
    """Utility class for precise decimal operations."""
    
    @staticmethod
    def to_decimal(value: Union[str, float, int, Decimal]) -> Decimal:
        """Convert various types to Decimal."""
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    
    @staticmethod
    def format_price(price: Union[str, float, int, Decimal], decimals: int = 6) -> str:
        """Format price with specified decimal places."""
        decimal_price = DecimalUtils.to_decimal(price)
        return str(decimal_price.quantize(Decimal('1.' + '0' * decimals), rounding=ROUND_DOWN))
    
    @staticmethod
    def format_quantity(quantity: Union[str, float, int, Decimal], decimals: int = 8) -> str:
        """Format quantity with specified decimal places."""
        decimal_quantity = DecimalUtils.to_decimal(quantity)
        return str(decimal_quantity.quantize(Decimal('1.' + '0' * decimals), rounding=ROUND_DOWN))
    
    @staticmethod
    def round_down(value: Union[str, float, int, Decimal], decimals: int = 6) -> Decimal:
        """Round down to specified decimal places."""
        decimal_value = DecimalUtils.to_decimal(value)
        return decimal_value.quantize(Decimal('1.' + '0' * decimals), rounding=ROUND_DOWN)
    
    @staticmethod
    def round_up(value: Union[str, float, int, Decimal], decimals: int = 6) -> Decimal:
        """Round up to specified decimal places."""
        decimal_value = DecimalUtils.to_decimal(value)
        return decimal_value.quantize(Decimal('1.' + '0' * decimals), rounding=ROUND_HALF_UP)
    
    @staticmethod
    def multiply(a: Union[str, float, int, Decimal], b: Union[str, float, int, Decimal]) -> Decimal:
        """Multiply two values with high precision."""
        return DecimalUtils.to_decimal(a) * DecimalUtils.to_decimal(b)
    
    @staticmethod
    def divide(a: Union[str, float, int, Decimal], b: Union[str, float, int, Decimal]) -> Decimal:
        """Divide two values with high precision."""
        decimal_b = DecimalUtils.to_decimal(b)
        if decimal_b == 0:
            raise ValueError("Cannot divide by zero")
        return DecimalUtils.to_decimal(a) / decimal_b
    
    @staticmethod
    def subtract(a: Union[str, float, int, Decimal], b: Union[str, float, int, Decimal]) -> Decimal:
        """Subtract two values with high precision."""
        return DecimalUtils.to_decimal(a) - DecimalUtils.to_decimal(b)
    
    @staticmethod
    def add(a: Union[str, float, int, Decimal], b: Union[str, float, int, Decimal]) -> Decimal:
        """Add two values with high precision."""
        return DecimalUtils.to_decimal(a) + DecimalUtils.to_decimal(b)
    
    @staticmethod
    def percentage(value: Union[str, float, int, Decimal], percent: Union[str, float, int, Decimal]) -> Decimal:
        """Calculate percentage of a value."""
        decimal_value = DecimalUtils.to_decimal(value)
        decimal_percent = DecimalUtils.to_decimal(percent) / Decimal('100')
        return decimal_value * decimal_percent
    
    @staticmethod
    def calculate_take_profit_price(entry_price: Union[str, float, int, Decimal], 
                                  profit_percentage: Union[str, float, int, Decimal]) -> Decimal:
        """Calculate take profit price based on entry price and profit percentage."""
        decimal_entry = DecimalUtils.to_decimal(entry_price)
        decimal_profit = DecimalUtils.to_decimal(profit_percentage) / Decimal('100')
        return decimal_entry * (Decimal('1') + decimal_profit)
    
    @staticmethod
    def calculate_stop_loss_price(entry_price: Union[str, float, int, Decimal], 
                                loss_percentage: Union[str, float, int, Decimal]) -> Decimal:
        """Calculate stop loss price based on entry price and loss percentage."""
        decimal_entry = DecimalUtils.to_decimal(entry_price)
        decimal_loss = DecimalUtils.to_decimal(loss_percentage) / Decimal('100')
        return decimal_entry * (Decimal('1') - decimal_loss)
    
    @staticmethod
    def calculate_pnl(entry_price: Union[str, float, int, Decimal], 
                     exit_price: Union[str, float, int, Decimal], 
                     quantity: Union[str, float, int, Decimal]) -> Decimal:
        """Calculate profit and loss."""
        entry = DecimalUtils.to_decimal(entry_price)
        exit = DecimalUtils.to_decimal(exit_price)
        qty = DecimalUtils.to_decimal(quantity)
        
        if exit > entry:
            # Long position profit
            return (exit - entry) * qty
        else:
            # Long position loss
            return (exit - entry) * qty
    
    @staticmethod
    def calculate_pnl_percentage(entry_price: Union[str, float, int, Decimal], 
                               exit_price: Union[str, float, int, Decimal]) -> Decimal:
        """Calculate profit and loss percentage."""
        entry = DecimalUtils.to_decimal(entry_price)
        exit = DecimalUtils.to_decimal(exit_price)
        
        if entry == 0:
            return Decimal('0')
        
        pnl = (exit - entry) / entry
        return pnl * Decimal('100')
    
    @staticmethod
    def is_positive(value: Union[str, float, int, Decimal]) -> bool:
        """Check if value is positive."""
        return DecimalUtils.to_decimal(value) > 0
    
    @staticmethod
    def is_negative(value: Union[str, float, int, Decimal]) -> bool:
        """Check if value is negative."""
        return DecimalUtils.to_decimal(value) < 0
    
    @staticmethod
    def compare(a: Union[str, float, int, Decimal], b: Union[str, float, int, Decimal]) -> int:
        """Compare two values. Returns -1, 0, or 1."""
        decimal_a = DecimalUtils.to_decimal(a)
        decimal_b = DecimalUtils.to_decimal(b)
        
        if decimal_a < decimal_b:
            return -1
        elif decimal_a > decimal_b:
            return 1
        else:
            return 0


# Convenience functions for common operations
def to_decimal(value: Union[str, float, int, Decimal]) -> Decimal:
    """Convert various types to Decimal."""
    return DecimalUtils.to_decimal(value)


def format_price(price: Union[str, float, int, Decimal], decimals: int = 6) -> str:
    """Format price with specified decimal places."""
    return DecimalUtils.format_price(price, decimals)


def format_quantity(quantity: Union[str, float, int, Decimal], decimals: int = 8) -> str:
    """Format quantity with specified decimal places."""
    return DecimalUtils.format_quantity(quantity, decimals)


def calculate_take_profit_price(entry_price: Union[str, float, int, Decimal], 
                              profit_percentage: Union[str, float, int, Decimal]) -> Decimal:
    """Calculate take profit price based on entry price and profit percentage."""
    return DecimalUtils.calculate_take_profit_price(entry_price, profit_percentage)


def calculate_stop_loss_price(entry_price: Union[str, float, int, Decimal], 
                            loss_percentage: Union[str, float, int, Decimal]) -> Decimal:
    """Calculate stop loss price based on entry price and loss percentage."""
    return DecimalUtils.calculate_stop_loss_price(entry_price, loss_percentage)


def calculate_pnl(entry_price: Union[str, float, int, Decimal], 
                 exit_price: Union[str, float, int, Decimal], 
                 quantity: Union[str, float, int, Decimal]) -> Decimal:
    """Calculate profit and loss."""
    return DecimalUtils.calculate_pnl(entry_price, exit_price, quantity)


def calculate_pnl_percentage(entry_price: Union[str, float, int, Decimal], 
                          exit_price: Union[str, float, int, Decimal]) -> Decimal:
    """Calculate profit and loss percentage."""
    return DecimalUtils.calculate_pnl_percentage(entry_price, exit_price)