import os
import random
from datetime import datetime
import yfinance as yf
from polygon import RESTClient
from alpaca.trading.client import TradingClient

class StrategistAgent:
    def __init__(self):
        self.polygon_client = RESTClient(api_key=os.getenv("POLYGON_API_KEY"))

    def get_iv_rank(self, symbol: str) -> float:
        """Calculate real IV rank using Polygon options data"""
        try:
            chain = self.polygon_client.list_snapshot_options_chain(
                symbol,
                params={"limit": 250}
            )
            ivs = [c.implied_volatility for c in chain if c.implied_volatility]
            if not ivs:
                return 50.0
            current_iv = sum(ivs) / len(ivs)
            iv_rank = min(100, max(0, (current_iv - min(ivs)) / (max(ivs) - min(ivs)) * 100))
            return round(iv_rank, 2)
        except Exception as e:
            print(f"IV rank fetch failed: {e} — using fallback")
            return 50.0

    def get_market_state(self):
        try:
            vix = float(yf.Ticker("^VIX").history(period="1d")["Close"].iloc[-1])
            spy = yf.Ticker("SPY").history(period="5d")
            spot = float(spy["Close"].iloc[-1])

            iv_rank = self.get_iv_rank("SPY")
            skew = "flat" if vix < 20 else "steep_put" if spy["Close"].pct_change().mean() < 0 else "steep_call"
            momentum = "bullish" if spy["Close"].iloc[-1] > spy["Close"].iloc[-5] else "bearish"
            regime = "high_vol" if vix > 25 else "low_vol"

            return {
                "iv_rank": iv_rank,
                "skew": skew,
                "vix": vix,
                "momentum": momentum,
                "regime": regime,
                "spot_spy": spot
            }
        except Exception as e:
            print(f"Market data fetch failed: {e} — aborting cycle")
            return None

    def generate_ideas(self, market_state):
        if market_state is None:
            return []

        iv_rank = market_state["iv_rank"]
        skew = market_state["skew"]
        vix = market_state["vix"]
        momentum = market_state["momentum"]
        regime = market_state["regime"]

        underlyings = ["SPY", "AAPL", "TSLA", "NVDA", "QQQ"]
        ideas = []

        def score_strategy(strategy):
            score = 0.0
            if strategy == "straddle":
                if iv_rank > 65 and vix > 25:
                    score += 0.45
                if regime == "high_vol":
                    score += 0.25
            elif strategy == "iron_condor":
                if iv_rank < 35 and skew == "flat" and vix < 22:
                    score += 0.50
                if regime == "low_vol":
                    score += 0.30
            elif strategy == "calendar_spread":
                if skew in ["steep_call", "steep_put"] and momentum != "neutral":
                    score += 0.40
                if skew != "flat":
                    score += 0.25
            return score

        candidates = [
            {"strategy": "straddle", "underlying": random.choice(underlyings)},
            {"strategy": "iron_condor", "underlying": random.choice(underlyings)},
            {"strategy": "calendar_spread", "underlying": random.choice(underlyings)},
        ]

        for cand in candidates:
            score = score_strategy(cand["strategy"])
            if score > 0.3:
                confidence = round(0.55 + score * 0.4, 3)
                ideas.append({
                    "strategy": cand["strategy"],
                    "underlying": cand["underlying"],
                    "confidence": confidence,
                    "rationale": f"Score {score:.2f} — IV rank {iv_rank:.0f}, skew {skew}, VIX {vix:.1f}, {momentum} momentum"
                })

        for idea in ideas:
            idea["timestamp"] = datetime.utcnow().isoformat()

        return ideas  # Return only high-conviction ideas, no random fallbacks


class QuantAgent:
    def __init__(self):
        self.polygon_client = RESTClient(api_key=os.getenv("POLYGON_API_KEY"))

    def validate(self, idea):
        """Real validation using Polygon options chain data"""
        try:
            chain = list(self.polygon_client.list_snapshot_options_chain(
                idea["underlying"],
                params={"limit": 50}
            ))
            if not chain:
                return {"valid": False, "reason": "No options chain data available", "score": None}

            ivs = [c.implied_volatility for c in chain if c.implied_volatility]
            avg_iv = sum(ivs) / len(ivs) if ivs else 0
            volumes = [c.day.volume for c in chain if c.day and c.day.volume]
            avg_volume = sum(volumes) / len(volumes) if volumes else 0

            # Minimum liquidity check
            if avg_volume < 100:
                return {"valid": False, "reason": "Insufficient options liquidity", "score": None}

            # IV sanity check
            if avg_iv <= 0 or avg_iv > 5:
                return {"valid": False, "reason": "IV out of reasonable range", "score": None}

            score = round(min(0.98, 0.5 + avg_iv + (avg_volume / 10000)), 3)
            return {"valid": True, "score": score}

        except Exception as e:
            print(f"QuantAgent validation error: {e}")
            return {"valid": False, "reason": f"Validation error: {e}", "score": None}


class GuardianAgent:
    def __init__(self):
        self.trading_client = TradingClient(
            api_key=os.getenv("ALPACA_API_KEY"),
            secret_key=os.getenv("ALPACA_SECRET_KEY"),
            paper=True
        )

    def check_risk(self, validated_idea):
        try:
            account = self.trading_client.get_account()
            equity = float(account.equity)
            buying_power = float(account.buying_power)

            positions = self.trading_client.get_all_positions()
            total_positions = len(positions)
            total_unrealized_pnl = sum(float(p.unrealized_pl) for p in positions)

            # Drawdown limit (-5% of equity)
            drawdown_pct = (total_unrealized_pnl / equity) * 100 if equity > 0 else 0
            if drawdown_pct < -5:
                return {"approved": False, "reason": f"Drawdown limit exceeded ({drawdown_pct:.2f}%)"}

            # Position count limit
            if total_positions >= 10:
                return {"approved": False, "reason": "Max 10 open positions reached"}

            # Real concentration check
            underlying = validated_idea["underlying"]
            underlying_exposure = sum(
                abs(float(p.market_value)) for p in positions
                if p.symbol.startswith(underlying)
            )
            total_exposure = sum(abs(float(p.market_value)) for p in positions)
            if total_exposure > 0 and (underlying_exposure / equity) > 0.20:
                return {"approved": False, "reason": f"Concentration limit exceeded for {underlying} (max 20%)"}

            # Margin check
            idea_cost = 1000.0
            if buying_power < idea_cost * 2:
                return {"approved": False, "reason": "Insufficient buying power"}

            return {"approved": True, "risk_score": round(abs(drawdown_pct) / 5, 3)}

        except Exception as e:
            print(f"Risk check failed: {e} — rejecting for safety")
            return {"approved": False, "reason": f"Risk check error: {e}"}
