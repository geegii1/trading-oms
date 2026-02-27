from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
from db import init_db, get_recent_approved_trades, get_open_positions, db_pool
from orchestrator import main_loop
import asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    print("Database initialized")
    asyncio.create_task(main_loop())
    print("Orchestration loop started")
    yield

app = FastAPI(title="AI OMS Dashboard", lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <!DOCTYPE html>
    <html>
    <head><title>AI OMS Dashboard</title></head>
    <body>
        <h1>AI Autonomous Options Trading OMS</h1>
        <p>Dashboard: <a href="/dashboard">/dashboard</a></p>
        <p>API docs: <a href="/docs">/docs</a></p>
        <p>Health: <a href="/health">/health</a></p>
    </body>
    </html>
    """

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    recent_trades = await get_recent_approved_trades(limit=10)
    open_positions = await get_open_positions()

    trades_html = "<tr><th>Time</th><th>Strategy</th><th>Underlying</th><th>Conf</th><th>Quant</th><th>Risk</th><th>Approved</th><th>Rationale</th></tr>"
    for trade in recent_trades:
        approved_color = "green" if trade['approved'] else "red"
        quant = f"{float(trade['quant_score']):.3f}" if trade['quant_score'] else 'N/A'
        risk = f"{float(trade['risk_score']):.3f}" if trade['risk_score'] else 'N/A'
        trades_html += f"""
        <tr>
            <td>{trade['timestamp']}</td>
            <td>{trade['strategy']}</td>
            <td>{trade['underlying']}</td>
            <td>{float(trade['confidence']):.3f}</td>
            <td>{quant}</td>
            <td>{risk}</td>
            <td style="color:{approved_color};">{'Yes' if trade['approved'] else 'No'}</td>
            <td>{trade['rationale']}</td>
        </tr>
        """

    positions_html = "<tr><th>ID</th><th>Time</th><th>Strategy</th><th>Underlying</th><th>Entry $</th><th>Current $</th><th>P&L</th></tr>"
    total_pnl = 0.0
    for pos in open_positions:
        pnl = float(pos['unrealized_pnl']) if pos['unrealized_pnl'] else 0.0
        total_pnl += pnl
        color = "green" if pnl >= 0 else "red"
        current = f"${float(pos['current_price']):.2f}" if pos['current_price'] else 'N/A'
        positions_html += f"""
        <tr>
            <td>{pos['id']}</td>
            <td>{pos['trade_timestamp']}</td>
            <td>{pos['strategy']}</td>
            <td>{pos['underlying']}</td>
            <td>${float(pos['entry_price']):.2f}</td>
            <td>{current}</td>
            <td style="color:{color};">${pnl:.2f}</td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>AI OMS Dashboard</title>
        <meta http-equiv="refresh" content="60">
        <style>
            body {{ font-family: Arial, sans-serif; padding: 20px; }}
            table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 13px; }}
            th {{ background-color: #f2f2f2; }}
            h1, h2 {{ text-align: center; }}
        </style>
    </head>
    <body>
        <h1>AI Autonomous Options Trading OMS</h1>
        <p style="text-align:center;">Shadow Mode • Cycle every 60s • Auto-refresh every 60s</p>
        <h2>Recent Approved Trades (last 10)</h2>
        <table>{trades_html}</table>
        <h2>Open Positions</h2>
        <table>{positions_html}</table>
        <h2>Total Unrealized P&L: <span style="color:{'green' if total_pnl >= 0 else 'red'};">${total_pnl:.2f}</span></h2>
    </body>
    </html>
    """
    return HTMLResponse(content=html, status_code=200)

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "db_pool": "initialized" if db_pool is not None else "not ready"
    }
