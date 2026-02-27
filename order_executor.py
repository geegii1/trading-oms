import os
from datetime import date, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest, MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, AssetClass

def submit_option_order(symbol: str, strategy: str) -> dict:
    """
    Submit a real paper options order to Alpaca.
    Returns order details or error.
    """
    try:
        client = TradingClient(
            api_key=os.getenv("ALPACA_API_KEY"),
            secret_key=os.getenv("ALPACA_SECRET_KEY"),
            paper=True
        )

        # Find best contract
        req = GetOptionContractsRequest(
            underlying_symbols=[symbol],
            expiration_date_gte=date.today() + timedelta(days=7),
            expiration_date_lte=date.today() + timedelta(days=45),
            limit=50
        )
        contracts = client.get_option_contracts(req)
        chain = contracts.option_contracts

        if not chain:
            return {"success": False, "reason": f"No contracts found for {symbol}"}

        # Pick ATM call for now (simplification — full multi-leg in future)
        valid = [c for c in chain if c.close_price and float(c.close_price) > 0]
        if not valid:
            return {"success": False, "reason": "No valid contracts with price"}

        # Sort by price and pick mid-chain (closest to ATM)
        valid.sort(key=lambda c: float(c.close_price))
        contract = valid[len(valid) // 2]

        # Submit market order for 1 contract
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
            "order_id": str(order.id),
            "contract": contract.symbol,
            "qty": 1,
            "side": "BUY"
        }

    except Exception as e:
        return {"success": False, "reason": str(e)}
