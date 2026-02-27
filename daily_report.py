import os
import asyncio
from datetime import datetime, timedelta
import asyncpg
from fpdf import FPDF
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.mime.text import MIMEText
from email.utils import formatdate

async def generate_daily_report():
    yesterday = datetime.utcnow() - timedelta(days=1)
    yesterday_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)

    pool = await asyncpg.create_pool(dsn=os.getenv("DB_URL"))
    try:
        async with pool.acquire() as conn:
            closes = await conn.fetch("""
                SELECT id, trade_timestamp, underlying, strategy, unrealized_pnl, close_reason, closed_timestamp
                FROM positions
                WHERE status = 'closed'
                  AND closed_timestamp >= $1
                  AND closed_timestamp <= $2
                ORDER BY closed_timestamp DESC
            """, yesterday_start, yesterday_end)

            total_closes = len(closes)
            total_realized = sum(row['unrealized_pnl'] for row in closes)
            wins = sum(1 for row in closes if row['unrealized_pnl'] > 0)
            losses = total_closes - wins
            avg_gain = sum(row['unrealized_pnl'] for row in closes if row['unrealized_pnl'] > 0) / wins if wins > 0 else 0
            avg_loss = sum(row['unrealized_pnl'] for row in closes if row['unrealized_pnl'] < 0) / losses if losses > 0 else 0

            open_count = await conn.fetchval("SELECT COUNT(*) FROM positions WHERE status = 'open'")
            total_unrealized = await conn.fetchval("SELECT SUM(unrealized_pnl) FROM positions WHERE status = 'open'") or 0
    finally:
        await pool.close()

    # Create PDF with unique filename
    report_date = yesterday.strftime('%Y-%m-%d')
    pdf_path = f"/tmp/daily_pnl_report_{report_date}.pdf"

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, f"Daily OMS P&L Report - {report_date}", ln=1, align='C')
    pdf.ln(5)

    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Closed Trades Summary", ln=1)
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 8, f"Total Closes: {total_closes}", ln=1)
    pdf.cell(0, 8, f"Total Realized P&L: ${total_realized:.2f}", ln=1)
    pdf.cell(0, 8, f"Wins: {wins} | Losses: {losses}", ln=1)
    pdf.cell(0, 8, f"Avg Gain: ${avg_gain:.2f} | Avg Loss: ${avg_loss:.2f}", ln=1)
    pdf.ln(5)

    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Open Positions Snapshot", ln=1)
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 8, f"Open Positions: {open_count}", ln=1)
    pdf.cell(0, 8, f"Total Unrealized P&L: ${total_unrealized:.2f}", ln=1)
    pdf.ln(10)

    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Closed Trades Details", ln=1)
    pdf.set_font("Arial", size=10)
    pdf.cell(20, 8, "ID", border=1)
    pdf.cell(40, 8, "Close Time", border=1)
    pdf.cell(30, 8, "Underlying", border=1)
    pdf.cell(30, 8, "Strategy", border=1)
    pdf.cell(25, 8, "P&L", border=1)
    pdf.cell(45, 8, "Reason", border=1)
    pdf.ln()

    for row in closes:
        pdf.cell(20, 8, str(row['id']), border=1)
        pdf.cell(40, 8, row['closed_timestamp'].strftime("%Y-%m-%d %H:%M"), border=1)
        pdf.cell(30, 8, row['underlying'], border=1)
        pdf.cell(30, 8, row['strategy'], border=1)
        pdf.cell(25, 8, f"${row['unrealized_pnl']:.2f}", border=1)
        pdf.cell(45, 8, row['close_reason'], border=1)
        pdf.ln()

    pdf.output(pdf_path)

    # Send email
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    recipient = os.getenv("EMAIL_RECIPIENT")

    msg = MIMEMultipart()
    msg['From'] = sender
    msg['To'] = recipient
    msg['Date'] = formatdate(localtime=True)
    msg['Subject'] = f"Daily OMS P&L Report - {report_date}"
    msg.attach(MIMEText("Attached is the daily P&L report for closed trades.", "plain"))

    with open(pdf_path, "rb") as f:
        part = MIMEApplication(f.read(), Name=f"daily_pnl_report_{report_date}.pdf")
        part['Content-Disposition'] = f'attachment; filename="daily_pnl_report_{report_date}.pdf"'
        msg.attach(part)

    server = smtplib.SMTP('smtp.gmail.com', 587)
    try:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())
        print(f"Daily report sent for {report_date}")
    finally:
        server.quit()

if __name__ == "__main__":
    asyncio.run(generate_daily_report())
