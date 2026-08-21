import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from app.models.vehicle import Vehicle
from app.models.reservation import Reservation
from app.models.maintenance import Maintenance
from app.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def run_tests():
    async with async_session() as db:
        from app.models.user import User

        u_id = uuid.uuid4()
        user = User(
            id=u_id,
            username=f"qa_{str(u_id)[:8]}",
            email=f"qa_{str(u_id)[:8]}@test.local",
            password_hash="hashed",
            full_name="QA Test",
            role="ADMIN"
        )
        db.add(user)

        # Create a test vehicle
        v_id = uuid.uuid4()
        v = Vehicle(
            id=v_id,
            registration=f"QA-{str(v_id)[:6]}",
            vin=str(v_id).replace("-", "")[:17],
            brand="Test",
            model="QA",
            year=2026,
            color="Red",
            fuel_type="GASOLINE",
            transmission="MANUAL",
            current_mileage=10,
            daily_rental_price=200,
            status="AVAILABLE",
            created_by=u_id
        )
        db.add(v)
        await db.commit()
        print("✅ Vehicle created.")

        now = datetime.now(timezone.utc)

        # Test 1: Create a reservation
        r1_id = uuid.uuid4()
        r1 = Reservation(
            id=r1_id,
            vehicle_id=v_id,
            customer_name="John Doe",
            start_datetime=now + timedelta(days=1),
            end_datetime=now + timedelta(days=5),
            daily_price=200,
            num_days=4,
            total_price=800,
            status="RESERVED",
            created_by=u_id
        )
        db.add(r1)
        await db.commit()
        print("✅ Reservation 1 created.")

        # Test 2: Double reservation (Overlap)
        try:
            r2 = Reservation(
                id=uuid.uuid4(),
                vehicle_id=v_id,
                customer_name="Jane Doe",
                start_datetime=now + timedelta(days=2),
                end_datetime=now + timedelta(days=6),
                daily_price=200,
                num_days=4,
                total_price=800,
                status="RESERVED",
                created_by=u_id
            )
            db.add(r2)
            await db.commit()
            print("❌ FAIL: Double reservation succeeded!")
        except Exception as e:
            await db.rollback()
            print("✅ Double reservation correctly prevented:", str(e).split('\n')[0])

        # Test 3: Maintenance overlap with reservation
        try:
            m1 = Maintenance(
                id=uuid.uuid4(),
                vehicle_id=v_id,
                type="Entretien",
                start_datetime=now + timedelta(days=4),
                expected_end_datetime=now + timedelta(days=7),
                step="EN ATTENTE",
                status="ACTIVE",
                created_by=u_id
            )
            db.add(m1)
            await db.commit()
            print("❌ FAIL: Maintenance overlap succeeded!")
        except Exception as e:
            await db.rollback()
            print("✅ Maintenance overlap correctly prevented:", str(e).split('\n')[0])

        # Clean up
        await db.execute(text(f"DELETE FROM reservations WHERE vehicle_id = '{v_id}'"))
        await db.execute(text(f"DELETE FROM maintenances WHERE vehicle_id = '{v_id}'"))
        await db.execute(text(f"DELETE FROM vehicles WHERE id = '{v_id}'"))
        await db.execute(text(f"DELETE FROM users WHERE id = '{u_id}'"))
        await db.commit()
        print("✅ Cleanup complete.")

if __name__ == "__main__":
    asyncio.run(run_tests())
