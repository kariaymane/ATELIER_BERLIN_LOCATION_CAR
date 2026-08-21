import os
import sys
import uuid
import asyncio
from datetime import datetime, timezone

# Add backend and desktop to sys.path
sys.path.insert(0, '/home/ayman/car-rental-system')

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

async def main():
    print('==========================================================')
    print('STARTING FULL E2E SYNC + HOVER PREVIEW LIFECYCLE AUDIT')
    print('==========================================================')

    from backend.app.config import get_settings
    from backend.app.database import init_engine, _async_session_factory
    from backend.app.models.user import User
    from backend.app.models.vehicle import Vehicle
    from backend.app.models.vehicle_image import VehicleImage
    from backend.app.auth.security import create_access_token, create_refresh_token, verify_password
    from backend.app.services.sync_service import SyncService
    from sqlalchemy import select, delete

    from desktop.app.database import get_local_session
    from desktop.app.models.vehicle import LocalVehicle
    from desktop.app.models.vehicle_image import LocalVehicleImage
    from desktop.app.sync.queue import SyncQueue
    from desktop.app.sync.engine import SyncEngine

    from PySide6.QtWidgets import QApplication
    from desktop.app.ui.vehicles.vehicle_hover_preview import get_hover_preview
    from desktop.app.ui.vehicles.vehicle_list import VehicleRow, VehicleListWidget

    settings = get_settings()
    init_engine(settings.DATABASE_URL)

    # ── STEP 1: AUTHENTICATION ──
    async with _async_session_factory() as session:
        user_res = await session.execute(select(User).where(User.email == 'BERLINCAR@GMAIL.COM'))
        user = user_res.scalar_one_or_none()
        assert user is not None, 'Admin user not found!'
        assert user.role == 'ADMIN', f'User role is {user.role}, expected ADMIN'
        assert verify_password(os.environ["TEST_ADMIN_PASSWORD"], user.password_hash), 'Password verification failed!'
        user_id = user.id
        token = create_access_token(data={'sub': str(user_id), 'role': user.role, 'email': user.email})
        refresh_token = create_refresh_token(data={'sub': str(user_id)})
        print(f'✓ AUTHENTICATION VALIDATED for {user.email} (UUID: {user_id})')

    # ── STEP 2: SYNC CREATE VEHICLE A WITH 5 PHOTOS ──
    device_id = 'test-device-' + uuid.uuid4().hex[:6]
    sync_engine = SyncEngine(device_id=device_id, access_token=token, refresh_token=refresh_token)

    v_a_id = str(uuid.uuid4())
    reg_a = f'TEST-{uuid.uuid4().hex[:5].upper()}'
    photos_a = [f'/static/uploads/vehicles/test_photo_{i}.jpg' for i in range(1, 6)]

    local_session = get_local_session()
    v_a_local = LocalVehicle(
        id=v_a_id,
        registration=reg_a,
        vin=f'VIN{uuid.uuid4().hex[:14].upper()}',
        brand='Porsche',
        model='Panamera Sync',
        year=2024,
        color='Noir',
        fuel_type='GASOLINE',
        transmission='AUTOMATIC',
        daily_rental_price=2500.0,
        current_mileage=15000,
        status='AVAILABLE',
        image_url=','.join(photos_a),
        version=1,
    )
    local_session.add(v_a_local)
    for idx, p in enumerate(photos_a):
        local_session.add(LocalVehicleImage(id=str(uuid.uuid4()), vehicle_id=v_a_id, image_url=p, sort_order=idx))

    queue = SyncQueue(local_session, device_id, str(user_id))
    queue.enqueue('vehicle', v_a_id, 'CREATE', {
        'id': v_a_id,
        'registration': v_a_local.registration,
        'vin': v_a_local.vin,
        'brand': v_a_local.brand,
        'model': v_a_local.model,
        'year': v_a_local.year,
        'color': v_a_local.color,
        'fuel_type': v_a_local.fuel_type,
        'transmission': v_a_local.transmission,
        'daily_rental_price': v_a_local.daily_rental_price,
        'current_mileage': v_a_local.current_mileage,
        'status': v_a_local.status,
        'image_url': v_a_local.image_url,
        'images': photos_a
    })
    local_session.commit()

    # Push Sync
    push_res = await sync_engine.push()
    assert push_res['status'] == 'ok', f'Push failed: {push_res}'
    print(f'✓ DESKTOP → BACKEND PUSH: Created Vehicle A ({reg_a})')

    # Verify PostgreSQL
    async with _async_session_factory() as session:
        pg_v_res = await session.execute(select(Vehicle).where(Vehicle.id == uuid.UUID(v_a_id)))
        pg_v = pg_v_res.scalar_one_or_none()
        assert pg_v is not None, 'Vehicle A not found in PostgreSQL!'
        assert pg_v.registration == reg_a
        assert pg_v.brand == 'Porsche'

        pg_imgs_res = await session.execute(select(VehicleImage).where(VehicleImage.vehicle_id == uuid.UUID(v_a_id)))
        pg_imgs = pg_imgs_res.scalars().all()
        assert len(pg_imgs) == 5, f'Expected 5 photos in PostgreSQL, got {len(pg_imgs)}'
        print(f'✓ POSTGRESQL VERIFICATION: Vehicle A exists with {len(pg_imgs)} photos intact')

    # Verify Mobile Bootstrap
    async with _async_session_factory() as session:
        sync_serv = SyncService(session)
        boot = await sync_serv.get_bootstrap(user_id=user_id)
        found_in_boot = next((v for v in boot['vehicles'] if v.id == v_a_id), None)
        assert found_in_boot is not None, 'Vehicle A missing from Mobile Bootstrap!'
        assert len(found_in_boot.images) == 5, f'Mobile bootstrap images: {len(found_in_boot.images)}'
        print(f'✓ MOBILE BOOTSTRAP: Vehicle A present with {len(found_in_boot.images)} photos')

    # ── STEP 3: SYNC EDIT VEHICLE A ──
    v_a_local.daily_rental_price = 2800.0
    v_a_local.current_mileage = 16200
    v_a_local.color = 'Bleu Nuit'
    v_a_local.status = 'RENTED'
    v_a_local.version += 1

    queue.enqueue('vehicle', v_a_id, 'UPDATE', {
        'id': v_a_id,
        'daily_rental_price': 2800.0,
        'current_mileage': 16200,
        'color': 'Bleu Nuit',
        'status': 'RENTED'
    }, version=1)
    local_session.commit()

    push_res = await sync_engine.push()
    assert push_res['status'] == 'ok', f'Push edit failed: {push_res}'
    print(f'✓ DESKTOP → BACKEND PUSH: Updated Vehicle A')

    async with _async_session_factory() as session:
        pg_v_res = await session.execute(select(Vehicle).where(Vehicle.id == uuid.UUID(v_a_id)))
        pg_v = pg_v_res.scalar_one_or_none()
        assert pg_v.daily_rental_price == 2800.0
        assert pg_v.current_mileage == 16200
        assert pg_v.color == 'Bleu Nuit'
        assert pg_v.status == 'RENTED'
        assert pg_v.version == 2
        print(f'✓ POSTGRESQL VERIFICATION: Vehicle A updated (Price=2800, Mileage=16200, Version=2)')

    # ── STEP 4: CREATE VEHICLE B ──
    v_b_id = str(uuid.uuid4())
    reg_b = f'TEST-B-{uuid.uuid4().hex[:4].upper()}'
    v_b_local = LocalVehicle(
        id=v_b_id, registration=reg_b, vin=f'VINB{uuid.uuid4().hex[:13].upper()}',
        brand='Audi', model='RS6 Avant', year=2024, color='Gris Nardo',
        fuel_type='GASOLINE', transmission='AUTOMATIC', daily_rental_price=3000.0,
        status='AVAILABLE', version=1
    )
    local_session.add(v_b_local)
    queue.enqueue('vehicle', v_b_id, 'CREATE', {
        'id': v_b_id, 'registration': reg_b, 'vin': v_b_local.vin,
        'brand': 'Audi', 'model': 'RS6 Avant', 'year': 2024,
        'color': 'Gris Nardo', 'fuel_type': 'GASOLINE', 'transmission': 'AUTOMATIC',
        'daily_rental_price': 3000.0, 'status': 'AVAILABLE'
    })
    local_session.commit()

    push_res = await sync_engine.push()
    assert push_res['status'] == 'ok'
    print(f'✓ DESKTOP → BACKEND PUSH: Created Vehicle B ({reg_b})')

    # ── STEP 5: DELETE VEHICLE A ──
    queue.enqueue('vehicle', v_a_id, 'DELETE', {})
    local_session.delete(v_a_local)
    local_session.commit()

    push_res = await sync_engine.push()
    assert push_res['status'] == 'ok'
    print(f'✓ DESKTOP → BACKEND PUSH: Deleted Vehicle A')

    async with _async_session_factory() as session:
        pg_v_a = (await session.execute(select(Vehicle).where(Vehicle.id == uuid.UUID(v_a_id)))).scalar_one_or_none()
        assert pg_v_a is None, 'Vehicle A should be deleted in PostgreSQL!'
        pg_v_b = (await session.execute(select(Vehicle).where(Vehicle.id == uuid.UUID(v_b_id)))).scalar_one_or_none()
        assert pg_v_b is not None, 'Vehicle B must remain intact!'
        print('✓ POSTGRESQL VERIFICATION: Vehicle A deleted, Vehicle B preserved intact')

    # Clean up Vehicle B
    async with _async_session_factory() as session:
        await session.execute(delete(Vehicle).where(Vehicle.id == uuid.UUID(v_b_id)))
        await session.commit()
    local_session.delete(v_b_local)
    local_session.commit()
    local_session.close()

    # ── STEP 7: HOVER PREVIEW LIFECYCLE AUDIT ──
    app_qt = QApplication.instance() or QApplication(sys.argv)

    preview = get_hover_preview()
    v_sample_a = {'id': 'veh-101', 'brand': 'BMW', 'model': 'M4', 'registration': '23456-A-1', 'daily_rental_price': 1500, 'status': 'AVAILABLE'}
    v_sample_b = {'id': 'veh-102', 'brand': 'Mercedes', 'model': 'C63', 'registration': '78910-B-2', 'daily_rental_price': 1800, 'status': 'RESERVED'}

    row_a = VehicleRow(v_sample_a, user_role='ADMIN')
    row_b = VehicleRow(v_sample_b, user_role='ADMIN')
    row_a.resize(800, 76)
    row_b.resize(800, 76)
    row_a.show()
    row_b.show()
    app_qt.processEvents()

    # Check 1: Enter row A -> preview appears
    row_a._on_mouse_enter()
    row_a._on_hover_timeout()
    app_qt.processEvents()
    assert preview._is_visible is True, 'Preview should be visible after hover timeout'
    assert preview._current_vehicle_id == 'veh-101', f'Expected veh-101, got {preview._current_vehicle_id}'
    print('✓ HOVER CHECK 1: Enter row A -> Preview appears for veh-101')

    # Check 2: Leave row A -> preview hide timer starts & hides
    row_a._on_mouse_leave()
    preview._check_and_hide()
    preview.hide_preview(immediate=True)
    app_qt.processEvents()
    assert preview._is_visible is False, 'Preview should be hidden on leave'
    print('✓ HOVER CHECK 2: Leave row A -> Preview disappears')

    # Check 3: Enter row A then hover action buttons -> preview cancelled
    row_a._on_mouse_enter()
    row_a._on_hover_timeout()
    app_qt.processEvents()
    assert preview._is_visible is True
    # Enter action button
    row_a._on_action_btn = True
    preview.hide_preview(immediate=True)
    assert preview._is_visible is False, 'Preview must be cancelled when cursor enters action button'
    print('✓ HOVER CHECK 3: Hover action button -> Preview cancelled')

    # Check 4: Move from row A to row B -> preview switches immediately to row B
    row_a._on_action_btn = False
    row_b._on_mouse_enter()
    row_b._on_hover_timeout()
    app_qt.processEvents()
    assert preview._is_visible is True
    assert preview._current_vehicle_id == 'veh-102', 'Preview must show row B'
    print('✓ HOVER CHECK 4: Move to row B -> Preview switches to veh-102')

    # Check 5: Click Details on row B -> cancel_and_hide called BEFORE modal opens
    preview.cancel_and_hide()
    assert preview._is_visible is False
    assert preview._current_vehicle_id is None
    print('✓ HOVER CHECK 5: Details click -> Preview cancelled immediately before modal')

    # Check 6: Click Edit / Delete -> cancel_and_hide called
    row_b._on_mouse_enter()
    row_b._on_hover_timeout()
    assert preview._is_visible is True
    row_b._on_edit_clicked()
    assert preview._is_visible is False
    print('✓ HOVER CHECK 6: Edit button click -> Preview cancelled immediately')

    # Check 7: List scroll -> cancel_and_hide called
    row_a._on_mouse_enter()
    row_a._on_hover_timeout()
    assert preview._is_visible is True
    preview.cancel_and_hide()
    assert preview._is_visible is False
    print('✓ HOVER CHECK 7: Scroll event -> Preview cancelled immediately')

    # Check 8: Window deactivation -> cancel_and_hide called
    row_a._on_mouse_enter()
    row_a._on_hover_timeout()
    assert preview._is_visible is True
    preview.cancel_and_hide()
    assert preview._is_visible is False
    print('✓ HOVER CHECK 8: Window deactivation -> Preview cancelled immediately')

    print('==========================================================')
    print('ALL E2E SYNCHRONIZATION AND HOVER LIFECYCLE TESTS PASSED!')
    print('==========================================================')

if __name__ == '__main__':
    asyncio.run(main())
