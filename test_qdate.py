import sys
from PySide6.QtWidgets import QApplication, QDateTimeEdit
from PySide6.QtCore import QDateTime, QTime, QDate
app = QApplication(sys.argv)
now = QDateTime.currentDateTime()
now.setTime(QTime(9, 0, 0))
dt_edit = QDateTimeEdit(now)
# Simulate user picking a new date
dt_edit.setDate(QDate(2026, 8, 20))
print("Time after date change:", dt_edit.time().toString())
