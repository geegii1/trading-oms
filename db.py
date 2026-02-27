import asyncpg
import os
from datetime import datetime

db_pool = None

async def init_db():
    global db_pool
    db_url = os.getenv("DB_URL")
    db_pool = await asyncpg.create_pool(dsn=db_url)

    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id SERIAL PRIMARY KEY,
                trade_timestamp TIMESTAMP,
                underlying TEXT,
                strategy TEXT,
                entry_price NUMERIC,
                current_price NUMERIC,
                unrealized_pnl NUMERIC,
                status TEXT DEFAULT 'open',
                close_reason TEXT,
                closed_timestamp TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS approved_trades (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT NOW(),
                underlying TEXT,
                strategy TEXT,
                confidence NUMERIC,
                quant_score NUMERIC,
                risk_score NUMERIC,
                rationale TEXT,
                approved BOOLEAN
            )
        """)

        # Indexes for performance
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_positions_status 
            ON positions(status)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_positions_underlying_status 
            ON positions(underlying, status)
        """)

async def log_approved_trade(idea, validation, risk_result):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO approved_trades (underlying, strategy, confidence, quant_score, risk_score, rationale, approved)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, idea["underlying"], idea["strategy"], idea["confidence"],
             validation["score"] if validation["valid"] else None,
             risk_result["risk_score"] if risk_result["approved"] else None,
             idea["rationale"], risk_result["approved"])

async def log_position(idea, entry_price):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO positions (trade_timestamp, underlying, strategy, entry_price, current_price, unrealized_pnl)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, datetime.utcnow(), idea["underlying"], idea["strategy"], entry_price, entry_price, 0.0)

async def update_pnl_by_id(conn, position_id: int, current_pnl: float):
    await conn.execute("""
        UPDATE positions
        SET unrealized_pnl = $1,
            updated_at = NOW()
        WHERE id = $2
    """, current_pnl, position_id)

async def close_position_by_id(conn, position_id: int, realized_pnl: float, reason: str):
    await conn.execute("""
        UPDATE positions
        SET status = 'closed',
            unrealized_pnl = $1,
            close_reason = $2,
            closed_timestamp = NOW(),
            updated_at = NOW()
        WHERE id = $3
    """, realized_pnl, reason, position_id)

async def get_open_positions():
    async with db_pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM positions WHERE status = 'open'")

async def get_recent_approved_trades(limit=10):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            SELECT * FROM approved_trades
            ORDER BY timestamp DESC LIMIT $1
        """, limit)
