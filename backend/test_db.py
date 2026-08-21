import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
async def main():
    engine = create_async_engine("postgresql+asyncpg://car_rental_system:tZqxLZcrxVJF5HM@127.0.0.1:5432/car_rental_system")
    async with engine.connect() as conn:
        res1 = await conn.execute(text("SELECT current_database();"))
        res2 = await conn.execute(text("SELECT current_user;"))
        res3 = await conn.execute(text("SELECT version_num FROM alembic_version;"))
        print("DB:", res1.scalar())
        print("USER:", res2.scalar())
        print("ALEMBIC:", res3.scalar())
asyncio.run(main())
