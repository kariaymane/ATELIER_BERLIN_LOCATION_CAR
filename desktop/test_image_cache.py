import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest

app = QApplication(sys.argv)
manager = QNetworkAccessManager()
url = "http://localhost:8000/static/uploads/vehicles/test.jpg"
def finished(reply):
    print("Error:", reply.error())
    data = reply.readAll()
    print("Size:", len(data))
    app.quit()
manager.finished.connect(finished)
manager.get(QNetworkRequest(QUrl(url)))
app.exec()
