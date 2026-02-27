import os
import random
from datetime import datetime, date
import yfinance as yf
from alpaca.trading.client import TradingClient
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionChainRequest
from alpaca.trading.requests import GetOptionContractsRequest

class StrategistAgent:
    def __init__(self):
        self.trading_client = TradingClient(
            api_key=os.getenv("ALPACA_API_KEY"),
            secret_key=os.getenv("ALPACA_SECRET_KEY"),
            paper=True
        )
        self.data_client = OptionHistoricalDataClient(
            api_key=os.getenv("ALPACA_API_KEY"),
            secret_key=os.getenv("ALPACA_SECRET_KEY")
        )

    def get_iv_rank(self, symbol: str) -> float:
        """Calculate IV rank using Alpaca options chain"""
        try:
            req = GetOptionContractsRequest(
                underlying_symbols=[symbol],
                expiration_date_gte=date.today(),
                limit=200
            )
            contracts = self.trading_client.get_option_contracts(req)
            ivs = [float(c.close_price) for c in contracts.option_contracts if c.close_price]
            if not ivs:
                return 50.0
            current_iv = sum(ivs) / len(ivs)
            iv_rank = min(100, max(0, (current_iv - min(ivs)) / (max(ivs) - min(ivs) + 0.0001) * 100))
            return round(iv_rank, 2)
        except Exception as e:
            print(f"Alpaca IV rank failed: {e} — using yfinance fallback")
            return self.get_iv_rank_yfinance(symbol)

    def get_iv_rank_yfinance(self, symbol: str) -> float:
        """Fallback IV rank from yfinance"""
        try:
            ticker = yf.Ticker(symbol)
            options_dates = ticker.options
            if not options_dates:
                return 50.0
            chain = ticker.option_chain(options_dates[0])
            ivs = list(chain.calls['impliedVolatility'].dropna()) + \
                  list(chain.puts['impliedVolatility'].dropna())
            if not ivs:
                return 50.0
            current_iv = sum(ivs) / len(ivs)
            iv_rank = min(100, max(0, (current_iv - min(ivs)) / (max(ivs) - min(ivs) + 0.0001) * 100))
            return round(iv_rank, 2)
        except Exception as e:
            print(f"yfinance IV rank also failed: {e} — returning default 50")
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

        return ideas


class QuantAgent:
    def __init__(self):
        self.trading_client = TradingClient(
            api_key=os.getenv("ALPACA_API_KEY"),
            secret_key=os.getenv("ALPACA_SECRET_KEY"),
            paper=True
        )

    def validate(self, idea):
        """Validate using Alpaca options chain, fallback to yfinance"""
        try:
            return self._validate_alpaca(idea)
        except Exception as e:
            print(f"Alpaca validation failed: {e} — trying yfinance fallback")
            return self._validate_yfinance(idea)

    def _validate_alpaca(self, idea):
        req = GetOptionContractsRequest(
            underlying_symbols=[idea["underlying"]],
            expiration_date_gte=date.today(),
            limit=50
        )
        contracts = self.trading_client.get_option_contracts(req)
        chain = contracts.option_contracts

        if not chain:
            return {"valid": False, "reason": "No options chain data from Alpaca", "score": None}

        ivs = [float(c.close_price) for c in chain if c.close_price]
        avg_iv = sum(ivs) / len(ivs) if ivs else 0

        if avg_iv <= 0:
            return {"valid": False, "reason": "IV data unavailable", "score": None}

        score = round(min(0.98, 0.5 + avg_iv), 3)
        return {"valid": True, "score": score}

    def _validate_yfinance(self, idea):
        try:
            ticker = yf.Ticker(idea["underlying"])
            options_dates = ticker.options
            if not options_dates:
                return {"valid": False, "reason": "No options data from yfinance", "score": None}

            chain = ticker.option_chain(options_dates[0])
            calls = chain.calls
            if calls.empty:
                return {"valid": False, "reason": "Empty options chain", "score": None}

            avg_volume = calls['volume'].fillna(0).mean()
            avg_iv = calls['impliedVolatility'].fillna(0).mean()

            if avg_volume < 10:
                return {"valid": False, "reason": "Insufficient options liquidity", "score": None}

            score = round(min(0.98, 0.5 + avg_iv), 3)
            return {"valid": True, "score": score}
        except Exception as e:
            return {"valid": False, "reason": f"yfinance validation error: {e}", "score": None}


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
            if equity > 0 and (underlying_exposure / equity) > 0.20:
                return {"approved": False, "reason": f"Concentration limit exceeded for {underlying} (max 20%)"}

            # Margin check
            idea_cost = 1000.0
            if buying_power < idea_cost * 2:
                return {"approved": False, "reason": "Insufficient buying power"}

            return {"approved": True, "risk_score": round(abs(drawdown_pct) / 5, 3)}

        except Exception as e:
            print(f"Risk check failed: {e} — rejecting for safety")
            return {"approved": False, "reason": f"Risk check error: {e}"}
