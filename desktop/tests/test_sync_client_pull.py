import pytest
import uuid
from app.database import init_local_db, get_local_session
from app.models.client import LocalClient
from app.sync.engine import SyncEngine

@pytest.fixture(autouse=True)
def setup_db():
    init_local_db()
    session = get_local_session()
    yield session
    session.close()

def test_apply_pulled_client_create(setup_db):
    session = setup_db
    engine = SyncEngine(device_id="test-device")
    assert session.query(LocalClient).filter_by(id="c1").first() is None
    item = {
        "entity_type": "client",
        "entity_id": "c1",
        "operation": "CREATE",
        "payload": {
            "first_name": "John",
            "last_name": "Doe",
            "phone": "123456789",
            "email": "john@example.com",
            "photo_url": None,
            "identity_card_image": None,
            "driving_license_image": None,
            "notes": "test client",
            "status": "ACTIVE"
        },
        "version": 2,
    }
    engine.apply_pulled_items([item])
    c = session.query(LocalClient).filter_by(id="c1").first()
    assert c is not None
    assert c.first_name == "John"
    assert c.last_name == "Doe"
    assert c.version == 2

def test_apply_pulled_client_update(setup_db):
    session = setup_db
    client = LocalClient(id="c2", first_name="Jane", last_name="Smith", version=1)
    session.add(client)
    session.commit()
    engine = SyncEngine(device_id="test-device")
    item = {
        "entity_type": "client",
        "entity_id": "c2",
        "operation": "UPDATE",
        "payload": {
            "first_name": "Janet",
            "last_name": "Smith",
            "phone": "987654321",
            "email": "janet@example.com",
            "notes": "updated",
        },
        "version": 3,
    }
    engine.apply_pulled_items([item])
    c = session.query(LocalClient).filter_by(id="c2").first()
    assert c.first_name == "Janet"
    assert c.phone == "987654321"
    assert c.version == 3

def test_apply_pulled_client_delete(setup_db):
    session = setup_db
    client = LocalClient(id="c3", first_name="Bob")
    session.add(client)
    session.commit()
    engine = SyncEngine(device_id="test-device")
    item = {
        "entity_type": "client",
        "entity_id": "c3",
        "operation": "DELETE",
        "payload": {},
        "version": 1,
    }
    engine.apply_pulled_items([item])
    assert session.query(LocalClient).filter_by(id="c3").first() is None
