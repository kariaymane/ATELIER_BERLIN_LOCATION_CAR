import asyncio
import app.database as database
from app.config import get_settings
from app.models.user import User
from sqlalchemy.future import select
from app.auth.password import hash_password

async def update_user():
    settings = get_settings()
    database.init_engine(settings.DATABASE_URL)

    async with database._async_session_factory() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()
        print('--- EXISTING USERS ---')
        for u in users:
            print(f'UUID: {u.id} | Email: {u.email} | Role: {u.role}')

        target_user = next((u for u in users if u.email in ['locationcar@gmail.com', 'admin@example.com', 'BERLINCAR@GMAIL.COM']), None)
        if target_user:
            print(f'\n--- UPDATING USER {target_user.id} ---')
            target_user.email = 'BERLINCAR@GMAIL.COM'
            target_user.password_hash = hash_password('Berlin20002000')
            await session.commit()
            print('Update successful.')
        else:
            print('WARNING: Target user not found.')

asyncio.run(update_user())
