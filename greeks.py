from math import log, sqrt, exp
from scipy.stats import norm
from scipy.optimize import brentq

def black_scholes_price(
    spot: float,
    strike: float,
    time_to_expiry: float,
    vol: float,
    rate: float,
    option_type: str = "call"
) -> float:
    if time_to_expiry <= 0:
        return max(spot - strike, 0) if option_type == "call" else max(strike - spot, 0)
    d1 = (log(spot / strike) + (rate + 0.5 * vol**2) * time_to_expiry) / (vol * sqrt(time_to_expiry))
    d2 = d1 - vol * sqrt(time_to_expiry)
    if option_type.lower() == "call":
        return spot * norm.cdf(d1) - strike * exp(-rate * time_to_expiry) * norm.cdf(d2)
    elif option_type.lower() == "put":
        return strike * exp(-rate * time_to_expiry) * norm.cdf(-d2) - spot * norm.cdf(-d1)
    else:
        raise ValueError("option_type must be 'call' or 'put'")

def black_scholes_greeks(
    spot: float,
    strike: float,
    time_to_expiry: float,
    vol: float,
    rate: float,
    option_type: str = "call"
) -> dict:
    if time_to_expiry <= 0 or vol <= 0:
        return {"error": "Time to expiry and volatility must be positive"}
    d1 = (log(spot / strike) + (rate + 0.5 * vol**2) * time_to_expiry) / (vol * sqrt(time_to_expiry))
    d2 = d1 - vol * sqrt(time_to_expiry)
    if option_type.lower() == "call":
        price = spot * norm.cdf(d1) - strike * exp(-rate * time_to_expiry) * norm.cdf(d2)
        delta = norm.cdf(d1)
        rho = strike * time_to_expiry * exp(-rate * time_to_expiry) * norm.cdf(d2)
    elif option_type.lower() == "put":
        price = strike * exp(-rate * time_to_expiry) * norm.cdf(-d2) - spot * norm.cdf(-d1)
        delta = norm.cdf(d1) - 1
        rho = -strike * time_to_expiry * exp(-rate * time_to_expiry) * norm.cdf(-d2)  # Fixed: negative for puts
    else:
        return {"error": "option_type must be 'call' or 'put'"}
    gamma = norm.pdf(d1) / (spot * vol * sqrt(time_to_expiry))
    theta = - (spot * norm.pdf(d1) * vol) / (2 * sqrt(time_to_expiry)) \
            - rate * strike * exp(-rate * time_to_expiry) * norm.cdf(d2 if option_type == "call" else -d2)
    vega = spot * norm.pdf(d1) * sqrt(time_to_expiry)
    return {
        "price": round(price, 4),
        "delta": round(delta, 4),
        "gamma": round(gamma, 4),
        "theta": round(theta, 4),
        "theta_per_day": round(theta / 365, 4),
        "vega": round(vega, 4),
        "rho": round(rho, 4),
        "d1": round(d1, 4),
        "d2": round(d2, 4)
    }

def implied_volatility(
    market_price: float,
    spot: float,
    strike: float,
    time_to_expiry: float,
    rate: float,
    option_type: str = "call",
    tol: float = 1e-6,
    max_iter: int = 100
) -> dict:
    def objective(vol):
        return black_scholes_price(spot, strike, time_to_expiry, vol, rate, option_type) - market_price
    try:
        iv = brentq(objective, a=0.001, b=5.0, xtol=tol, maxiter=max_iter)
        return {
            "implied_vol": round(iv, 4),
            "solved_price": round(black_scholes_price(spot, strike, time_to_expiry, iv, rate, option_type), 4),
            "iterations": "converged",
            "error_message": None
        }
    except ValueError as e:
        return {
            "implied_vol": None,
            "solved_price": None,
            "iterations": "failed",
            "error_message": str(e) or "No convergence - price out of reasonable IV range"
        }
