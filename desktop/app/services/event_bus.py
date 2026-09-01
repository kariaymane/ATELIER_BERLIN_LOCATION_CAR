from PySide6.QtCore import QObject, Signal

class EventBus(QObject):
    # Global refresh trigger. NOT a state channel — it only asks
    # ``MainWindow._on_global_data_refreshed`` to call ``DomainStore.reload()``,
    # which then publishes one revisioned snapshot to every subscriber.
    # Retained for the background-sync paths (``sync/engine.py``,
    # ``sync/uploads.py``), the manual refresh button, and ``client_details``.
    # Committed domain mutations now go through ``DomainStore.mutate()`` and do
    # NOT emit this.
    data_refreshed = Signal()

# Initialize immediately at module level (main thread) to ensure correct thread affinity.
_bus = EventBus()

def get_event_bus():
    return _bus
