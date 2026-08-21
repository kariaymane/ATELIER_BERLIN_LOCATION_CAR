import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
async def main():
    e=create_async_engine('postgresql+asyncpg://car_rental_system:tZqxLZcrxVJF5HM@car-rental-db-prod.flycast:5432/car_rental_system', connect_args={"ssl": False})
    async with e.connect() as c:
        print(await c.scalar(text('SELECT 1')))
asyncio.run(main())
