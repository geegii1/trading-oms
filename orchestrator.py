import asyncio
import os
from datetime import datetime
from alpaca.trading.client import TradingClient
import db
from db import log_approved_trade, log_position, update_pnl_by_id, close_position_by_id, get_open_positions
from agents import StrategistAgent, QuantAgent, GuardianAgent
from price_fetcher import get_option_mid_price
from order_executor import submit_option_order
from market_hours import is_market_open, market_status

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
    """Update P&L for all open positions using real Alpaca options prices."""
    if db.db_pool is None:
        return

    open_positions = await get_open_positions()
    if not open_positions:
        return

    async with db.db_pool.acquire() as conn:
        for pos in open_positions:
            symbol = pos["underlying"]
            position_id = pos["id"]
            entry_price = float(pos["entry_price"])

            current_price = await asyncio.get_event_loop().run_in_executor(
                None, get_option_mid_price, symbol, pos["strategy"]
            )

            if current_price <= 0:
                continue

            pnl = round((current_price - entry_price) * 100, 2)
            await update_pnl_by_id(conn, position_id, current_price, pnl)

            if pnl >= 200:
                await close_position_by_id(conn, position_id, pnl, "Take-profit hit (+$200)")
                print(f"Closed {position_id} ({symbol}) P&L ${pnl:.2f} (Take-profit)")
            elif pnl <= -150:
                await close_position_by_id(conn, position_id, pnl, "Stop-loss hit (-$150)")
                print(f"Closed {position_id} ({symbol}) P&L ${pnl:.2f} (Stop-loss)")
            else:
                print(f"Position {position_id} ({symbol}): entry ${entry_price:.2f} → current ${current_price:.2f} → P&L ${pnl:.2f}")

async def orchestration_cycle():
    shadow_mode = os.getenv("SHADOW_MODE", "false").lower() == "true"
    status = market_status()
    print(f"[{datetime.utcnow().isoformat()}] Market {status['status']} ({status['current_time_et']})")

    if not status["is_open"]:
        print("Market closed — skipping trade cycle")
        # Still update P&L with latest available prices
        await refresh_pnl_from_broker()
        return

    print(f"Starting orchestration cycle (shadow_mode={shadow_mode})")

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

        if db.db_pool is not None:
            await log_approved_trade(idea, validation, risk_result)

        if risk_result["approved"]:
            approved.append(idea)
            print(f"APPROVED: {idea['strategy']} on {idea['underlying']} (conf: {idea['confidence']:.3f})")

            entry_price = await asyncio.get_event_loop().run_in_executor(
                None, get_option_mid_price, idea["underlying"], idea["strategy"]
            )

            if not shadow_mode:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, submit_option_order, idea["underlying"], idea["strategy"]
                )
                if result["success"]:
                    print(f"Order submitted: {result['contract']} order_id={result['order_id']}")
                else:
                    print(f"Order failed: {result['reason']}")

            if db.db_pool is not None:
                await log_position(idea, entry_price)
        else:
            print(f"Rejected by Guardian: {risk_result['reason']}")

    print(f"Cycle complete. Approved: {len(approved)} ideas")
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
