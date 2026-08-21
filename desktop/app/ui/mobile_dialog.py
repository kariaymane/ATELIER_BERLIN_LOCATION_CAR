from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QFormLayout
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QFont
import requests

class _ApiWorker(QThread):
    finished = Signal(bool)
    def __init__(self, url):
        super().__init__()
        self.url = url
    def run(self):
        try:
            res = requests.get(self.url, timeout=2)
            self.finished.emit(res.status_code == 200)
        except Exception:
            self.finished.emit(False)

class MobileAppDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Contrôle de l'application Mobile")
        self.setFixedSize(500, 440)

        from app.config import API_BASE_URL
        self.api_url = API_BASE_URL
        self._setup_ui()
        self._refresh_status()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Header
        header = QLabel("📱 Intégration Mobile App")
        header.setFont(QFont("Libre Caslon Text", 16, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        info = QLabel("L'application mobile est une interface connectée directement à cette même base de données centrale PostgreSQL.")
        info.setFont(QFont("Hanken Grotesk", 10))
        info.setWordWrap(True)
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info)

        # Status Frame (6px radius)
        status_frame = QFrame()
        status_frame.setObjectName("status_frame")
        status_layout = QFormLayout(status_frame)
        status_layout.setContentsMargins(16, 16, 16, 16)
        status_layout.setVerticalSpacing(12)

        self.lbl_api_status = QLabel("Vérification...")
        self.lbl_api_url = QLabel("Vérification...")
        self.lbl_vehicles = QLabel("-")
        self.lbl_reservations = QLabel("-")
        self.lbl_maintenance = QLabel("-")
        self.lbl_last_sync = QLabel("-")

        for lbl in [self.lbl_api_url, self.lbl_vehicles, self.lbl_reservations, self.lbl_maintenance, self.lbl_last_sync]:
            lbl.setFont(QFont("Hanken Grotesk", 10))

        status_layout.addRow("État de connexion :", self.lbl_api_url)
        status_layout.addRow("Statut de l'API Mobile :", self.lbl_api_status)
        status_layout.addRow("Véhicules synchronisés :", self.lbl_vehicles)
        status_layout.addRow("Réservations synchronisées :", self.lbl_reservations)
        status_layout.addRow("Maintenances synchronisées :", self.lbl_maintenance)
        status_layout.addRow("Dernière vérification :", self.lbl_last_sync)

        layout.addWidget(status_frame)
        layout.addStretch()

        # Action buttons
        btn_refresh = QPushButton("🔄 Rafraîchir le statut")
        btn_refresh.clicked.connect(self._refresh_status)
        layout.addWidget(btn_refresh)

        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

    def _refresh_status(self):
        self.lbl_api_status.setText("Vérification...")

        from datetime import datetime
        self.lbl_last_sync.setText(datetime.now().strftime("%H:%M:%S"))

        QTimer.singleShot(100, self._check_api)

    def _check_api(self):
        self._worker = _ApiWorker(f"{self.api_url.replace('/api/v1', '/health')}")
        self._worker.finished.connect(self._on_check_api_finished)
        self._worker.start()

    def _on_check_api_finished(self, is_online: bool):
        if is_online:
            self.lbl_api_status.setText("🟢 CONNECTED")
            self.lbl_api_url.setText("Connecté (Production)")
            self.lbl_vehicles.setText("Synchronisé")
            self.lbl_reservations.setText("Synchronisé")
            self.lbl_maintenance.setText("Synchronisé")
        else:
            self.lbl_api_status.setText("🔴 DISCONNECTED")
            self.lbl_api_url.setText("Non connecté")
            self.lbl_vehicles.setText("Hors ligne")
            self.lbl_reservations.setText("Hors ligne")
            self.lbl_maintenance.setText("Hors ligne")
