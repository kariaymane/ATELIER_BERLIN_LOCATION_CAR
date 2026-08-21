import asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from app.models.user import User
from app.auth.password import hash_password

async def main():
    engine = create_async_engine("postgresql+asyncpg://car_rental_system:tZqxLZcrxVJF5HM@127.0.0.1:5432/car_rental_system")
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        user = User(
            id="b9cf1c50-bf2b-44f3-9a87-acf775825d46",
            email="BERLINCAR@GMAIL.COM",
            username="berlincar",
            full_name="Berlin Car Admin",
            password_hash=hash_password("Berlin20002000"),
            role="ADMIN",
            is_active=True
        )
        session.add(user)
        await session.commit()
        print("User inserted!")

asyncio.run(main())
