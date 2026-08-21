import sys
from PySide6.QtWidgets import QApplication
from app.ui.login_window import LoginWindow

app = QApplication(sys.argv)
win = LoginWindow()
win.show()
print("UI loaded successfully")
sys.exit(0)
