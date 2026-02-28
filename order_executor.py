import os
from datetime import date, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest, MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, AssetClass

def get_client():
    return TradingClient(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
        paper=True
    )

def get_chain(client, symbol: str, dte_min: int = 7, dte_max: int = 45, limit: int = 200):
    """Fetch options chain for a symbol."""
    req = GetOptionContractsRequest(
        underlying_symbols=[symbol],
        expiration_date_gte=date.today() + timedelta(days=dte_min),
        expiration_date_lte=date.today() + timedelta(days=dte_max),
        limit=limit
    )
    contracts = client.get_option_contracts(req)
    return contracts.option_contracts

def get_spot_price(client, symbol: str) -> float:
    """Get current spot price from Alpaca positions or fallback to yfinance."""
    try:
        import yfinance as yf
        price = float(yf.Ticker(symbol).history(period="1d")["Close"].iloc[-1])
        return price
    except:
        return 0.0

def find_strike(contracts, option_type: str, target_price: float, offset: float = 0):
    """Find contract closest to target_price + offset."""
    target = target_price + offset
    filtered = [c for c in contracts if 
                c.type == option_type and 
                c.strike_price and 
                c.close_price and 
                float(c.close_price) > 0]
    if not filtered:
        return None
    return min(filtered, key=lambda c: abs(float(c.strike_price) - target))

def submit_iron_condor(symbol: str) -> dict:
    """
    Iron condor = 4 legs:
    - Sell OTM put  (ATM - 5%)
    - Buy  OTM put  (ATM - 8%)  <- wing
    - Sell OTM call (ATM + 5%)
    - Buy  OTM call (ATM + 8%)  <- wing
    """
    try:
        client = get_client()
        chain = get_chain(client, symbol)
        if not chain:
            return {"success": False, "reason": f"No chain for {symbol}"}

        spot = get_spot_price(client, symbol)
        if spot <= 0:
            return {"success": False, "reason": "Could not get spot price"}

        # Find the 4 strikes
        short_put  = find_strike(chain, "put",  spot, offset=-spot*0.05)
        long_put   = find_strike(chain, "put",  spot, offset=-spot*0.08)
        short_call = find_strike(chain, "call", spot, offset=+spot*0.05)
        long_call  = find_strike(chain, "call", spot, offset=+spot*0.08)

        legs = [short_put, long_put, short_call, long_call]
        if any(l is None for l in legs):
            return {"success": False, "reason": "Could not find all 4 iron condor strikes"}

        orders = []
        sides = [OrderSide.SELL, OrderSide.BUY, OrderSide.SELL, OrderSide.BUY]
        labels = ["short_put", "long_put", "short_call", "long_call"]

        for leg, side, label in zip(legs, sides, labels):
            order = client.submit_order(
                MarketOrderRequest(
                    symbol=leg.symbol,
                    qty=1,
                    side=side,
                    time_in_force=TimeInForce.DAY,
                    asset_class=AssetClass.US_OPTION
                )
            )
            orders.append({
                "label": label,
                "contract": leg.symbol,
                "strike": float(leg.strike_price),
                "side": side.value,
                "order_id": str(order.id)
            })
            print(f"  Leg submitted: {label} {leg.symbol} {side.value} @ strike {leg.strike_price}")

        return {
            "success": True,
            "strategy": "iron_condor",
            "symbol": symbol,
            "spot": spot,
            "legs": orders
        }

    except Exception as e:
        return {"success": False, "reason": str(e)}

def submit_calendar_spread(symbol: str) -> dict:
    """
    Calendar spread = 2 legs same strike, different expiry:
    - Sell near-term ATM call (7-20 DTE)
    - Buy  far-term ATM call  (30-45 DTE)
    """
    try:
        client = get_client()

        spot = get_spot_price(client, symbol)
        if spot <= 0:
            return {"success": False, "reason": "Could not get spot price"}

        # Near-term leg (7-20 DTE)
        near_chain = get_chain(client, symbol, dte_min=7, dte_max=20)
        # Far-term leg (30-45 DTE)
        far_chain  = get_chain(client, symbol, dte_min=30, dte_max=45)

        if not near_chain or not far_chain:
            return {"success": False, "reason": "Insufficient chain data for calendar spread"}

        near_leg = find_strike(near_chain, "call", spot, offset=0)
        far_leg  = find_strike(far_chain,  "call", spot, offset=0)

        if not near_leg or not far_leg:
            return {"success": False, "reason": "Could not find ATM strikes for calendar"}

        orders = []
        for leg, side, label in [
            (near_leg, OrderSide.SELL, "short_near_call"),
            (far_leg,  OrderSide.BUY,  "long_far_call")
        ]:
            order = client.submit_order(
                MarketOrderRequest(
                    symbol=leg.symbol,
                    qty=1,
                    side=side,
                    time_in_force=TimeInForce.DAY,
                    asset_class=AssetClass.US_OPTION
                )
            )
            orders.append({
                "label": label,
                "contract": leg.symbol,
                "strike": float(leg.strike_price),
                "side": side.value,
                "order_id": str(order.id)
            })
            print(f"  Leg submitted: {label} {leg.symbol} {side.value} @ strike {leg.strike_price}")

        return {
            "success": True,
            "strategy": "calendar_spread",
            "symbol": symbol,
            "spot": spot,
            "legs": orders
        }

    except Exception as e:
        return {"success": False, "reason": str(e)}

def submit_option_order(symbol: str, strategy: str) -> dict:
    """
    Main entry point. Routes to correct multi-leg executor.
    Falls back to single-leg if multi-leg fails.
    """
    print(f"Submitting {strategy} on {symbol}...")

    if strategy == "iron_condor":
        result = submit_iron_condor(symbol)
    elif strategy == "calendar_spread":
        result = submit_calendar_spread(symbol)
    else:
        result = {"success": False, "reason": f"Unknown strategy: {strategy}"}

    if not result["success"]:
        print(f"Multi-leg failed: {result['reason']} — trying single-leg fallback")
        return submit_single_leg_fallback(symbol, strategy)

    return result

def submit_single_leg_fallback(symbol: str, strategy: str) -> dict:
    """Fallback: single ATM call buy if multi-leg fails."""
    try:
        client = get_client()
        chain = get_chain(client, symbol)
        if not chain:
            return {"success": False, "reason": f"No chain for {symbol} in fallback"}

        valid = [c for c in chain if c.close_price and float(c.close_price) > 0]
        if not valid:
            return {"success": False, "reason": "No valid contracts in fallback"}

        valid.sort(key=lambda c: float(c.close_price))
        contract = valid[len(valid) // 2]

        order = client.submit_order(
            MarketOrderRequest(
                symbol=contract.symbol,
                qty=1,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
                asset_class=AssetClass.US_OPTION
            )
        )

        return {
            "success": True,
            "strategy": "single_leg_fallback",
            "contract": contract.symbol,
            "order_id": str(order.id)
        }

    except Exception as e:
        return {"success": False, "reason": f"Fallback also failed: {e}"}
