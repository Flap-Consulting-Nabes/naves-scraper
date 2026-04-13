import asyncio
import random


async def random_delay(min_s: float = 2.5, max_s: float = 6.5) -> None:
    """Wait a random time between min_s and max_s seconds to simulate human behaviour."""
    delay = random.uniform(min_s, max_s)
    await asyncio.sleep(delay)
