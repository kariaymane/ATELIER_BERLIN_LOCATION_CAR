from PySide6.QtCore import QObject, Signal

class EventBus(QObject):
    # Signals can pass entity_type and entity_id, e.g. "client", "1234-5678..."
    entity_changed = Signal(str, str)
    # Global refresh signal
    data_refreshed = Signal()

_bus = None

def get_event_bus():
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
