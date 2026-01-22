import asyncio, functools, random
from typing import Callable

def retry_async(max_attempts: int = 2, base_delay: float = 0.2):
    def deco(fn: Callable):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            attempt = 0
            while True:
                try:
                    return await fn(*args, **kwargs)
                except Exception:
                    attempt += 1
                    if attempt > max_attempts:
                        raise
                    delay = base_delay * (2 ** (attempt-1)) + random.uniform(0, 0.05)
                    await asyncio.sleep(delay)
        return wrapper
    return deco
