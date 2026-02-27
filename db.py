import asyncpg
import os
from datetime import datetime

db_pool = None

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(dsn=os.getenv("DB_URL"))
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS approved_trades (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMPTZ DEFAULT NOW(),
                strategy TEXT,
                underlying TEXT,
                confidence FLOAT,
                quant_score FLOAT,
                risk_score FLOAT,
                approved BOOLEAN,
                rationale TEXT
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id SERIAL PRIMARY KEY,
                trade_timestamp TIMESTAMPTZ DEFAULT NOW(),
                strategy TEXT,
                underlying TEXT,
                entry_price FLOAT,
                current_price FLOAT,
                unrealized_pnl FLOAT DEFAULT 0,
                status TEXT DEFAULT 'open',
                close_reason TEXT
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_positions_underlying_status ON positions(underlying, status);
        """)
        # Add current_price column if it doesn't exist (migration)
        await conn.execute("""
            ALTER TABLE positions ADD COLUMN IF NOT EXISTS current_price FLOAT;
        """)

async def log_approved_trade(idea, validation, risk_result):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO approved_trades (strategy, underlying, confidence, quant_score, risk_score, approved, rationale)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        idea["strategy"],
        idea["underlying"],
        idea["confidence"],
        validation.get("score"),
        risk_result.get("risk_score"),
        risk_result["approved"],
        idea.get("rationale", "")
        )

async def log_position(idea, entry_price):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO positions (strategy, underlying, entry_price, current_price, status)
            VALUES ($1, $2, $3, $3, 'open')
        """,
        idea["strategy"],
        idea["underlying"],
        entry_price
        )

async def update_pnl_by_id(conn, position_id: int, current_price: float, pnl: float):
    await conn.execute("""
        UPDATE positions SET current_price=$1, unrealized_pnl=$2 WHERE id=$3
    """, current_price, pnl, position_id)

async def close_position_by_id(conn, position_id: int, final_pnl: float, reason: str):
    await conn.execute("""
        UPDATE positions SET status='closed', unrealized_pnl=$1, close_reason=$2 WHERE id=$3
    """, final_pnl, reason, position_id)

async def get_open_positions():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM positions WHERE status='open' ORDER BY trade_timestamp DESC
        """)
        return [dict(r) for r in rows]

async def get_recent_approved_trades(limit=10):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM approved_trades ORDER BY timestamp DESC LIMIT $1
        """, limit)
        return [dict(r) for r in rows]
