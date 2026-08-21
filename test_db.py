import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
async def main():
    e=create_async_engine('postgresql+asyncpg://car_rental_system:tZqxLZcrxVJF5HM@car-rental-db-prod.flycast:5432/car_rental_system', connect_args={"ssl": False})
    async with e.connect() as c:
        try:
            res = await c.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='vehicles';"))
            print([r[0] for r in res.fetchall()])
        except Exception as ex:
            print(f"Error: {ex}")
asyncio.run(main())
