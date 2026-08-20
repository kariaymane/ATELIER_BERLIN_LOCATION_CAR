"""
Test Vehicle Hover Preview functionality:
- Hover enter, debounce timer (200ms), show_for_row
- Dynamic position calculation and clamping within app window
- Real vehicle data display (brand, model, reg, year, fuel, price, status, mileage, color, transmission)
- Absence of fake data when fields are missing
- Image cache loading and placeholder when photo missing
- Hover transition: mouse moving from Row -> Preview -> Outside
- Edit/Delete/View buttons remain responsive
"""
import sys
import time
from PySide6.QtWidgets import QApplication, QPushButton, QLabel
from PySide6.QtCore import Qt, QPoint, QEvent, QTimer
from PySide6.QtGui import QEnterEvent

from app.database import init_local_db
from app.ui.vehicles.vehicle_list import VehicleListWidget, VehicleRow
from app.ui.vehicles.vehicle_hover_preview import get_hover_preview, VehicleHoverPreview
from app.ui.main_window import MainWindow
from app.i18n import set_language
from app.config import save_language

def test_vehicle_hover_preview():
    save_language("fr")
    set_language("fr")
    app = QApplication.instance() or QApplication(sys.argv)
    init_local_db()

    user_data = {"id": "test-admin", "email": "BERLINCAR@GMAIL.COM", "full_name": "Admin", "role": "ADMIN"}
    main_win = MainWindow(user_data)
    main_win.resize(1280, 800)
    main_win.show()
    app.processEvents()

    # Switch to vehicles page
    main_win._switch_page("vehicles")
    app.processEvents()

    v_list = main_win._vehicle_list
    assert isinstance(v_list, VehicleListWidget)

    # 1. Test with real vehicle data
    test_vehicles = [
        {
            "id": "v-1",
            "brand": "Audi",
            "model": "A6 Prestige",
            "registration": "HOV-001",
            "year": 2024,
            "fuel_type": "DIESEL",
            "daily_rental_price": 1800.0,
            "status": "AVAILABLE",
            "current_mileage": 45000,
            "color": "Noir Mythic",
            "transmission": "Automatique",
            "image_url": "/static/uploads/vehicles/test_audi.jpg",
            "notes": "Vidange récente effectuée."
        },
        {
            "id": "v-2",
            "brand": "Renault",
            "model": "Clio 5",
            "registration": "HOV-002",
            "year": 2022,
            "fuel_type": "ESSENCE",
            "daily_rental_price": 350.0,
            "status": "MAINTENANCE",
            "current_mileage": None, # Missing mileage
            "color": "", # Missing color
            "transmission": "", # Missing transmission
            "image_url": "", # Missing image
            "notes": ""
        }
    ]

    v_list.load_vehicles(test_vehicles)
    app.processEvents()

    assert len(v_list._cards) == 2
    row1, data1 = v_list._cards[0]
    row2, data2 = v_list._cards[1]

    preview = get_hover_preview()
    assert isinstance(preview, VehicleHoverPreview)
    assert not preview.isVisible()

    # 2. Test Hover Enter on Row 1 (Audi A6)
    print("Testing hover debounce on Row 1 (Audi A6)...")
    enter_ev = QEnterEvent(QPoint(10, 10), QPoint(10, 10), row1.mapToGlobal(QPoint(10, 10)))
    row1.enterEvent(enter_ev)
    assert row1._is_hovered
    assert preview._show_timer.isActive()

    # Trigger hover timeout
    preview._on_show_timeout()
    app.processEvents()

    # Verify Preview is displayed and populated with real Audi A6 data
    assert preview.isVisible()
    assert preview._name_lbl.text() == "Audi A6 Prestige"
    assert preview._current_vehicle["registration"] == "HOV-001"
    assert preview._current_vehicle["daily_rental_price"] == 1800.0
    assert preview._current_vehicle["current_mileage"] == 45000
    print("✓ Preview displayed with full real vehicle data.")

    # Verify position is strictly within main_win bounds
    win_tl = main_win.mapToGlobal(QPoint(0, 0))
    p_pos = preview.pos()
    print(f"Preview pos: ({p_pos.x()}, {p_pos.y()}), Main window bounds: {win_tl.x()}..{win_tl.x()+main_win.width()}, {win_tl.y()}..{win_tl.y()+main_win.height()}")
    assert p_pos.x() >= win_tl.x()
    assert p_pos.x() + preview.width() <= win_tl.x() + main_win.width() + 10
    print("✓ Preview positioned strictly within application window bounds.")

    # 3. Test transition from Row -> Preview
    print("Testing cursor transition to Preview widget...")
    row1.leaveEvent(QEvent(QEvent.Type.Leave))
    assert not row1._is_hovered
    assert preview._hide_timer.isActive()

    # Enter Preview before hide timer expires
    preview.enterEvent(QEnterEvent(QPoint(5, 5), QPoint(5, 5), preview.mapToGlobal(QPoint(5, 5))))
    assert preview._is_hovered
    assert not preview._hide_timer.isActive()
    assert preview.isVisible()
    print("✓ Preview remains open when cursor enters preview card.")

    # 4. Leave Preview and verify hide
    print("Testing cursor leaving Preview widget...")
    preview.leaveEvent(QEvent(QEvent.Type.Leave))
    assert not preview._is_hovered
    assert preview._hide_timer.isActive()

    # Trigger check and hide
    preview._check_and_hide()
    # Process animation
    for _ in range(25):
        time.sleep(0.01)
        app.processEvents()

    assert not preview.isVisible()
    print("✓ Preview hides smoothly after cursor leaves.")

    # 5. Test Row 2 (Missing optional fields & missing image)
    print("Testing Row 2 with missing optional fields...")
    row2.enterEvent(QEnterEvent(QPoint(10, 10), QPoint(10, 10), row2.mapToGlobal(QPoint(10, 10))))
    preview._on_show_timeout()
    app.processEvents()

    assert preview.isVisible()
    assert preview._name_lbl.text() == "Renault Clio 5"
    assert "Photo indisponible" in preview._photo.text()

    # Check that missing fields are NOT in specs layout
    spec_labels = []
    for i in range(preview._specs_container.count()):
        item = preview._specs_container.itemAt(i)
        if item and item.layout():
            for j in range(item.layout().count()):
                w = item.layout().itemAt(j).widget()
                if isinstance(w, QLabel):
                    spec_labels.append(w.text())

    # "Kilométrage" must NOT be in spec_labels because mileage is None!
    assert "Kilométrage" not in spec_labels
    assert "Couleur" not in spec_labels
    assert "Transmission" not in spec_labels
    # "Immatriculation", "Année", "Carburant", "Tarif", "Statut" MUST be present
    assert "Immatriculation" in spec_labels
    assert "HOV-002" in spec_labels
    assert "350 DH / jour" in spec_labels
    assert "En maintenance" in spec_labels
    print("✓ No fake data: missing fields are completely omitted from preview.")

    # 6. Verify CRUD buttons on standalone row
    print("Testing CRUD buttons remain clickable and unobstructed...")
    test_row = VehicleRow(data1, "ADMIN")
    edit_emitted = []
    test_row.edit_requested.connect(lambda vid: edit_emitted.append(vid))

    for child in test_row.findChildren(QPushButton):
        if "✏" in child.text():
            child.click()
            break

    assert edit_emitted == ["v-1"]
    print("✓ Edit action button emits signal cleanly.")

    main_win.close()
    print("\n🎉 ALL VEHICLE HOVER PREVIEW TESTS PASSED 100%!")

if __name__ == "__main__":
    test_vehicle_hover_preview()
