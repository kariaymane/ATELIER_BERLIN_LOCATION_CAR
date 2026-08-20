import uuid
import datetime
from app.database import get_local_session
from app.models.vehicle import LocalVehicle
from app.models.maintenance import LocalMaintenance

def run_test():
    session = get_local_session()
    audi_id = str(uuid.uuid4())
    now = datetime.datetime.now().isoformat()

    v = LocalVehicle(
        id=audi_id, registration="AUDI-TEST", brand="Audi", model="A4",
        status="AVAILABLE", created_at=now, updated_at=now
    )
    session.add(v)
    session.commit()

    m1_id = str(uuid.uuid4())
    m1 = LocalMaintenance(
        id=m1_id, vehicle_id=audi_id, type="Oil change", status="ACTIVE",
        step="DIAGNOSTIC", created_at=now, updated_at=now, start_datetime=now
    )
    session.add(m1)
    session.commit()

    m1 = session.query(LocalMaintenance).filter_by(id=m1_id).first()
    m1.status = "COMPLETED"
    m1.step = "TERMINE"
    session.commit()

    m2_id = str(uuid.uuid4())
    m2 = LocalMaintenance(
        id=m2_id, vehicle_id=audi_id, type="Brake repair", status="ACTIVE",
        step="DIAGNOSTIC", created_at=now, updated_at=now, start_datetime=now
    )
    session.add(m2)
    session.commit()

    count = session.query(LocalMaintenance).filter_by(vehicle_id=audi_id).count()
    print("M Count for Audi:", count)
    for m in session.query(LocalMaintenance).filter_by(vehicle_id=audi_id).all():
        print(m.id, m.type, m.status)

run_test()
