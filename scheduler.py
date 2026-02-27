import asyncio
from orchestrator import orchestration_cycle
import os

async def autonomous_loop():
    while True:
        try:
            await orchestration_cycle()
        except Exception as e:
            print(f"Scheduler error: {e} — continuing")
        await asyncio.sleep(int(os.getenv("CYCLE_INTERVAL", 60)))

if __name__ == "__main__":
    asyncio.run(autonomous_loop())
