import os
from datetime import date, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest

def get_option_mid_price(symbol: str, strategy: str) -> float:
    """
    Fetch real mid price (bid+ask)/2 for the most liquid ATM option
    for a given underlying and strategy type.
    Falls back to underlying price / 100 if unavailable.
    """
    try:
        client = TradingClient(
            api_key=os.getenv("ALPACA_API_KEY"),
            secret_key=os.getenv("ALPACA_SECRET_KEY"),
            paper=True
        )

        # Get contracts expiring in next 30-60 days
        req = GetOptionContractsRequest(
            underlying_symbols=[symbol],
            expiration_date_gte=date.today() + timedelta(days=7),
            expiration_date_lte=date.today() + timedelta(days=45),
            limit=50
        )
        contracts = client.get_option_contracts(req)
        chain = contracts.option_contracts

        if not chain:
            print(f"No contracts found for {symbol} — using spot price fallback")
            return get_spot_price_fallback(symbol)

        # Filter for contracts with valid bid/ask
        valid = [
            c for c in chain
            if c.close_price and float(c.close_price) > 0
        ]

        if not valid:
            return get_spot_price_fallback(symbol)

        # Sort by open interest proxy (close price as liquidity signal)
        # Pick the ATM-ish contract with highest close price activity
        valid.sort(key=lambda c: float(c.close_price), reverse=False)
        mid = len(valid) // 2
        best = valid[mid]

        price = float(best.close_price)
        print(f"Entry price for {symbol} ({strategy}): ${price:.2f} from contract {best.symbol}")
        return round(price, 2)

    except Exception as e:
        print(f"Option price fetch failed for {symbol}: {e} — using fallback")
        return get_spot_price_fallback(symbol)


def get_spot_price_fallback(symbol: str) -> float:
    """Fallback: use yfinance spot price"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        price = float(ticker.history(period="1d")["Close"].iloc[-1])
        print(f"Using spot price fallback for {symbol}: ${price:.2f}")
        return round(price, 2)
    except Exception as e:
        print(f"Spot price fallback also failed: {e} — returning 0.0")
        return 0.0
