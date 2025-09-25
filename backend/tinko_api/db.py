import asyncpg
from .config import DATABASE_URL

pool = None  # type: ignore

async def init_db():
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(
            dsn=DATABASE_URL,
            min_size=1,
            max_size=5,
            statement_cache_size=1000,
        )

async def close_db():
    global pool
    if pool is not None:
        await pool.close()
        pool = None

async def get_db():
    """
    Yields a pooled connection per request.
    Make sure init_db() ran on startup.
    """
    if pool is None:
        raise RuntimeError("DB pool not initialized. Did the app run startup?")
    async with pool.acquire() as conn:
        yield conn
