import pytest
import uuid
from datetime import datetime, timezone
from app.database import get_local_session, init_local_db
from app.models.vehicle import LocalVehicle
from app.models.vehicle_image import LocalVehicleImage
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance, LocalMaintenancePart
from app.models.sync_queue import SyncQueueItem, LocalSyncQueue


@pytest.fixture(autouse=True)
def setup_db():
    init_local_db()
    session = get_local_session()
    yield session
    session.close()


def test_vehicle_model_crud(setup_db):
    session = setup_db
    v_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    vehicle = LocalVehicle(
        id=v_id,
        registration="12345-A-1",
        vin="WVWZZZ3CZWE123456",
        brand="Mercedes-Benz",
        model="Classe C",
        year=2024,
        color="Noir",
        fuel_type="DIESEL",
        transmission="AUTOMATIC",
        daily_rental_price=450.0,
        current_mileage=12000,
        status="AVAILABLE",
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(vehicle)
    session.commit()

    saved = session.query(LocalVehicle).filter_by(id=v_id).first()
    assert saved is not None
    assert saved.brand == "Mercedes-Benz"
    assert saved.daily_rental_price == 450.0
    assert saved.status == "AVAILABLE"

    session.delete(saved)
    session.commit()


def test_reservation_model_crud(setup_db):
    session = setup_db
    r_id = str(uuid.uuid4())
    v_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    res = LocalReservation(
        id=r_id,
        vehicle_id=v_id,
        customer_name="Aymane Kari",
        customer_phone="+212600000000",
        start_datetime=now,
        end_datetime=now,
        daily_price=450.0,
        num_days=3,
        total_price=1350.0,
        deposit=500.0,
        payment_status="PAID",
        status="ACTIVE",
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(res)
    session.commit()

    saved = session.query(LocalReservation).filter_by(id=r_id).first()
    assert saved is not None
    assert saved.customer_name == "Aymane Kari"
    assert saved.total_price == 1350.0

    session.delete(saved)
    session.commit()


def test_maintenance_model_with_parts(setup_db):
    session = setup_db
    m_id = str(uuid.uuid4())
    v_id = str(uuid.uuid4())
    p_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    maint = LocalMaintenance(
        id=m_id,
        vehicle_id=v_id,
        type="Entretien",
        title="Vidange + Filtres",
        start_datetime=now,
        oil_brand="Castrol Edge",
        oil_viscosity="5W-30",
        oil_quantity=4.5,
        oil_filter_changed=True,
        air_filter_changed=True,
        parts_cost=350.0,
        labor_cost=150.0,
        actual_cost=500.0,
        step="DIAGNOSTIC",
        status="ACTIVE",
        created_at=now,
        updated_at=now,
        version=1,
    )
    part = LocalMaintenancePart(
        id=p_id,
        maintenance_id=m_id,
        part_name="Filtre à huile OEM",
        quantity=1.0,
        unit_price=120.0,
        total_price=120.0,
        created_at=now,
        updated_at=now,
    )
    session.add(maint)
    session.add(part)
    session.commit()

    saved_m = session.query(LocalMaintenance).filter_by(id=m_id).first()
    assert saved_m is not None
    assert saved_m.oil_brand == "Castrol Edge"
    assert saved_m.oil_filter_changed is True

    saved_p = session.query(LocalMaintenancePart).filter_by(maintenance_id=m_id).first()
    assert saved_p is not None
    assert saved_p.part_name == "Filtre à huile OEM"

    session.delete(saved_p)
    session.delete(saved_m)
    session.commit()
