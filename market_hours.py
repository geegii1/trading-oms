from datetime import datetime, time
import pytz

def is_market_open() -> bool:
    """Returns True if US stock market is currently open."""
    et = pytz.timezone("America/New_York")
    now = datetime.now(et)

    # Weekend check
    if now.weekday() >= 5:  # 5=Saturday, 6=Sunday
        return False

    # Market hours: 9:30am - 4:00pm ET
    market_open = time(9, 30)
    market_close = time(16, 0)

    return market_open <= now.time() < market_close

def market_status() -> dict:
    """Returns market status with next open time info."""
    et = pytz.timezone("America/New_York")
    now = datetime.now(et)
    open_status = is_market_open()

    return {
        "is_open": open_status,
        "current_time_et": now.strftime("%Y-%m-%d %H:%M:%S ET"),
        "weekday": now.strftime("%A"),
        "status": "OPEN" if open_status else "CLOSED"
    }
