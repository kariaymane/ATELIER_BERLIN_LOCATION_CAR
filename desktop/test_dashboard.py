import sys
from PySide6.QtWidgets import QApplication
from app.ui.dashboard import DashboardWidget

app = QApplication(sys.argv)
dash = DashboardWidget()
print("DashboardWidget initialized successfully")
dash._on_period_changed()
print("_on_period_changed called successfully")
