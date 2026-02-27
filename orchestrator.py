import asyncio
import os
from datetime import datetime
from alpaca.trading.client import TradingClient
from db import db_pool, log_approved_trade, log_position, update_pnl_by_id, close_position_by_id, get_open_positions
from agents import StrategistAgent, QuantAgent, GuardianAgent

# Module-level singleton to avoid recreating clients every cycle
_trading_client = None

def get_trading_client():
    global _trading_client
    if _trading_client is None:
        _trading_client = TradingClient(
            api_key=os.getenv("ALPACA_API_KEY"),
            secret_key=os.getenv("ALPACA_SECRET_KEY"),
            paper=True
        )
    return _trading_client

async def refresh_pnl_from_broker():
    """Update P&L for all open positions using real Alpaca data."""
    if db_pool is None:
        print("DB pool not initialized yet — skipping P&L update")
        return

    client = get_trading_client()
    broker_positions = {p.symbol: p for p in client.get_all_positions()}

    open_positions = await get_open_positions()

    async with db_pool.acquire() as conn:
        for pos in open_positions:
            symbol = pos["underlying"]
            position_id = pos["id"]

            if symbol not in broker_positions:
                continue

            current_pnl = float(broker_positions[symbol].unrealized_pl)
            await update_pnl_by_id(conn, position_id, current_pnl)

            # Auto-close logic based on real P&L
            if current_pnl >= 20:
                await close_position_by_id(conn, position_id, current_pnl, "Take-profit hit (+$20)")
                print(f"Closed position {position_id} ({symbol}) with P&L {current_pnl:.2f} (Take-profit)")
            elif current_pnl <= -25:
                await close_position_by_id(conn, position_id, current_pnl, "Stop-loss hit (-$25)")
                print(f"Closed position {position_id} ({symbol}) with P&L {current_pnl:.2f} (Stop-loss)")

async def orchestration_cycle():
    shadow_mode = os.getenv("SHADOW_MODE", "true").lower() == "true"
    print(f"[{datetime.utcnow().isoformat()}] Starting orchestration cycle (shadow_mode={shadow_mode})")

    strategist = StrategistAgent()
    quant = QuantAgent()
    guardian = GuardianAgent()

    market_state = strategist.get_market_state()
    if market_state is None:
        print("No valid market data — skipping cycle")
        return

    print(f"Market state: VIX={market_state['vix']:.1f}, IV Rank={market_state['iv_rank']:.0f}, regime={market_state['regime']}")

    ideas = strategist.generate_ideas(market_state)
    if not ideas:
        print("No high-conviction ideas generated — cycle complete")
        return

    approved = []
    for idea in ideas:
        validation = quant.validate(idea)
        if not validation["valid"]:
            print(f"Rejected by Quant: {validation['reason']}")
            continue

        risk_result = guardian.check_risk(idea)
        await log_approved_trade(idea, validation, risk_result)

        if risk_result["approved"]:
            approved.append(idea)
            print(f"APPROVED: {idea['strategy']} on {idea['underlying']} (conf: {idea['confidence']:.3f})")

            # Get real entry price from Alpaca
            client = get_trading_client()
            broker_positions = {p.symbol: p for p in client.get_all_positions()}
            real_entry = float(broker_positions[idea["underlying"]].avg_entry_price) \
                if idea["underlying"] in broker_positions else 100.0

            if not shadow_mode:
                # TODO: Submit real Alpaca options order here
                print(f"LIVE MODE: Would submit order for {idea['underlying']}")

            await log_position(idea, real_entry)
        else:
            print(f"Rejected by Guardian: {risk_result['reason']}")

    print(f"Cycle complete. Approved: {len(approved)} ideas")

    # Update P&L from broker
    await refresh_pnl_from_broker()

async def main_loop():
    while True:
        try:
            await orchestration_cycle()
        except Exception as e:
            print(f"Cycle error: {e} — continuing")
        await asyncio.sleep(int(os.getenv("CYCLE_INTERVAL", 60)))

if __name__ == "__main__":
    asyncio.run(main_loop())
