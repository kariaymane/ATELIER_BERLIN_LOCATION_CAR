import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
async def main():
    engine = create_async_engine("postgresql+asyncpg://car_rental_system:tZqxLZcrxVJF5HM@127.0.0.1:5432/car_rental_system")
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT email FROM users;"))
        print([r[0] for r in res.fetchall()])
asyncio.run(main())
