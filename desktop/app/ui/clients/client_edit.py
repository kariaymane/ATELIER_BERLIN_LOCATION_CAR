"""
Client edition — a real UPDATE on the SAME client_id.

Business contract (identical to the backend, see
``backend/app/services/client_service.py::update_client``):

  - Editing a client NEVER creates a second client. The ``client_id`` the
    dialog opened with is the ``client_id`` it writes back to.
  - A field left untouched is not sent, so the server leaves it alone.
  - A field the user EMPTIED is sent as ``None`` — an explicit CLEAR. Only
    ``first_name`` / ``last_name`` are refused, they are NOT NULL columns.
  - Documents can be ADDED, REPLACED or REMOVED. A removal sends ``None``
    for that one column and never disturbs the other four.

Document rows carry NO file path text: the ``[Voir]`` button is the sole
control that opens a document, and nothing is allowed to cover it.

Persistence is online-first (PUT /api/v1/clients/{id} → PostgreSQL) with the
local SQLite row and the sync queue written in the same transaction, so the
Client window refreshes immediately from one committed state.
"""
import logging
from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QTextEdit, QPushButton, QFrame, QMessageBox, QFileDialog, QWidget,
    QScrollArea,
)

from app.i18n import t, is_rtl

logger = logging.getLogger(__name__)

# The five client document slots, in display order. Each entry is
# (column name, i18n caption key).
DOCUMENT_SLOTS = (
    ("identity_card_image", "docs_cin_recto"),
    ("identity_card_image_back", "docs_cin_verso"),
    ("driving_license_image", "docs_license_recto"),
    ("driving_license_image_back", "docs_license_verso"),
    ("contract_image", "docs_contract"),
)

# Plain text fields: (column name, i18n caption key, is_multiline)
TEXT_FIELDS = (
    ("first_name", "col_first_name", False),
    ("last_name", "col_last_name", False),
    ("cin_number", "col_cin", False),
    ("phone", "col_phone", False),
    ("address", "col_address", False),
    ("email", "col_email", False),
    ("license_number", "col_license", False),
    ("notes", "col_notes", True),
)


class ClientEditDialog(QDialog):
    """Edit one existing client. Never creates a new one."""

    def __init__(self, client_row: dict, api_client=None, parent=None,
                 device_id: str = "", user_id: str = ""):
        super().__init__(parent)
        self._original = dict(client_row or {})
        self._client_id = str(self._original.get("id") or "")
        self._api = api_client
        # Identity stamped on a queued change. The ApiClient does not carry it.
        self._device_id = device_id
        self._user_id = user_id

        # Pending document intent per slot:
        #   None                  -> untouched
        #   ("SET", "/local/path")-> add or replace with this local file
        #   ("REMOVE", None)      -> clear this document column
        self._doc_intent = {key: None for key, _ in DOCUMENT_SLOTS}
        self._inputs = {}
        self._doc_state_labels = {}

        self.setWindowTitle(t("clients.edit_title"))
        self.setMinimumWidth(620)
        self.resize(680, 720)
        self._setup_ui()

    # ── UI ────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        title = QLabel(t("clients.edit_title"))
        title.setFont(QFont("Libre Caslon Text", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #1E4D38;")
        outer.addWidget(title)

        # Everything scrolls, so no field is ever pushed off a small screen.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(14)

        # ── identity + contact fields ─────────────────────────────
        form = QFormLayout()
        form.setSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for key, cap_key, multiline in TEXT_FIELDS:
            if multiline:
                widget = QTextEdit()
                widget.setPlainText(str(self._original.get(key) or ""))
                widget.setFixedHeight(70)
            else:
                widget = QLineEdit(str(self._original.get(key) or ""))
                widget.setMinimumHeight(30)
            self._inputs[key] = widget
            form.addRow(t(f"clients.{cap_key}"), widget)
        body_layout.addLayout(form)

        # ── document slots ────────────────────────────────────────
        docs_frame = QFrame()
        docs_frame.setObjectName("clientEditDocs")
        docs_frame.setStyleSheet(
            "#clientEditDocs { background: #F7FAF5; border-radius: 10px; }")
        docs_layout = QVBoxLayout(docs_frame)
        docs_layout.setContentsMargins(14, 12, 14, 12)
        docs_layout.setSpacing(8)

        docs_title = QLabel(t("clients.identity_section"))
        docs_title.setFont(QFont("Hanken Grotesk", 12, QFont.Weight.Bold))
        docs_title.setStyleSheet("color: #1E4D38;")
        docs_layout.addWidget(docs_title)

        for key, cap_key in DOCUMENT_SLOTS:
            docs_layout.addWidget(self._build_doc_row(key, cap_key))
        body_layout.addWidget(docs_frame)

        body_layout.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # ── actions ───────────────────────────────────────────────
        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton(t("common.cancel"))
        cancel.setMinimumHeight(34)
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        save = QPushButton(t("common.save"))
        save.setProperty("class", "primary")
        save.setMinimumHeight(34)
        save.clicked.connect(self._on_save)
        btns.addWidget(save)
        outer.addLayout(btns)

    def _build_doc_row(self, key: str, cap_key: str) -> QWidget:
        """One document row: NAME — state — [Voir] [Remplacer] [Retirer].

        The row never renders a file path. The name of the document type stays
        visible, the state is a short human label, and the buttons keep a fixed
        width so nothing can grow over them or push them off the row.
        """
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        name = QLabel(t(f"clients.{cap_key}"))
        name.setMinimumWidth(120)
        name.setStyleSheet("color: #2D3748; font-size: 12px; font-weight: 600;")
        h.addWidget(name)

        state = QLabel()
        state.setStyleSheet("color: #6B7264; font-size: 11px;")
        # The state label must never expand into the buttons.
        state.setWordWrap(False)
        self._doc_state_labels[key] = state
        h.addWidget(state, 1)

        view = QPushButton(f"👁 {t('clients.view_doc')}")
        view.setFixedWidth(90)
        view.setMinimumHeight(28)
        view.setCursor(Qt.CursorShape.PointingHandCursor)
        view.setStyleSheet(
            "background-color: #EBF3EA; color: #1E4D38; font-weight: bold; "
            "border: 1px solid #C4DFC0; border-radius: 4px; padding: 4px 8px;")
        view.clicked.connect(lambda _, k=key: self._view_document(k))
        h.addWidget(view)

        replace = QPushButton(t("clients.doc_replace"))
        replace.setFixedWidth(100)
        replace.setMinimumHeight(28)
        replace.setCursor(Qt.CursorShape.PointingHandCursor)
        replace.clicked.connect(lambda _, k=key: self._choose_document(k))
        h.addWidget(replace)

        remove = QPushButton(t("clients.doc_remove"))
        remove.setFixedWidth(90)
        remove.setMinimumHeight(28)
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.clicked.connect(lambda _, k=key: self._remove_document(k))
        h.addWidget(remove)

        self._refresh_doc_state(key)
        return row

    def _refresh_doc_state(self, key: str):
        intent = self._doc_intent.get(key)
        label = self._doc_state_labels[key]
        if intent and intent[0] == "SET":
            label.setText(f"✎ {t('clients.doc_pending')}")
            label.setStyleSheet("color: #975A16; font-size: 11px;")
        elif intent and intent[0] == "REMOVE":
            label.setText(f"✕ {t('clients.doc_will_remove')}")
            label.setStyleSheet("color: #B91C1C; font-size: 11px;")
        elif self._original.get(key):
            label.setText(f"✓ {t('clients.doc_present')}")
            label.setStyleSheet("color: #1E4D38; font-size: 11px;")
        else:
            label.setText(t("clients.doc_absent"))
            label.setStyleSheet("color: #9CA3AF; font-size: 11px;")

    # ── document actions ──────────────────────────────────────────

    def _view_document(self, key: str):
        intent = self._doc_intent.get(key)
        # A freshly chosen file is previewed from disk; otherwise the stored one.
        target = intent[1] if (intent and intent[0] == "SET") else None
        if intent and intent[0] == "REMOVE":
            target = None
        elif target is None:
            target = self._original.get(key)
        if not target:
            QMessageBox.information(self, "Information", t("clients.doc_missing"))
            return
        from app.utils.document_viewer import view_document
        view_document(target, api_client=self._api, parent=self)

    def _choose_document(self, key: str):
        path, _ = QFileDialog.getOpenFileName(
            self, t("clients.doc_choose"), "",
            "Documents (*.png *.jpg *.jpeg *.webp *.pdf)")
        if path:
            self._doc_intent[key] = ("SET", path)
            self._refresh_doc_state(key)

    def _remove_document(self, key: str):
        intent = self._doc_intent.get(key)
        if intent and intent[0] == "SET":
            # Cancel a not-yet-saved choice instead of scheduling a removal.
            self._doc_intent[key] = None
        elif not self._original.get(key):
            self._doc_intent[key] = None
        else:
            self._doc_intent[key] = ("REMOVE", None)
        self._refresh_doc_state(key)

    # ── save ──────────────────────────────────────────────────────

    def _current_text(self, key: str):
        widget = self._inputs[key]
        raw = (widget.toPlainText() if isinstance(widget, QTextEdit)
               else widget.text())
        raw = (raw or "").strip()
        return raw or None

    def _on_save(self):
        first = self._current_text("first_name")
        last = self._current_text("last_name")
        if not first or not last:
            QMessageBox.warning(self, t("common.error"), t("clients.err_name_req"))
            return

        # 1. Upload any newly chosen document, so the payload carries server URLs.
        doc_updates = {}
        for key, _ in DOCUMENT_SLOTS:
            intent = self._doc_intent.get(key)
            if intent is None:
                continue
            if intent[0] == "REMOVE":
                doc_updates[key] = None
                continue
            url = self._upload_document(intent[1])
            if url is None:
                QMessageBox.warning(
                    self, t("common.error"),
                    t("clients.save_failed", error=intent[1]))
                return
            doc_updates[key] = url

        # 2. Diff the text fields. Only what actually changed is sent, and an
        #    emptied optional field is sent as an explicit None (a CLEAR).
        payload = {}
        for key, _cap, _multi in TEXT_FIELDS:
            new = self._current_text(key)
            old = self._original.get(key) or None
            if new != old:
                payload[key] = new
        payload.update(doc_updates)

        if not payload:
            self.accept()
            return

        # 3. Persist. PostgreSQL via FastAPI is the business authority.
        #
        #    Three distinct outcomes, deliberately NOT collapsed:
        #      accepted   -> write the local mirror, nothing to queue.
        #      refused    -> the server rejected this content. Write NOTHING
        #                    locally and queue NOTHING: replaying a write the
        #                    server already refused would only fail again and
        #                    would leave the cache disagreeing with PostgreSQL.
        #                    The dialog stays open so the user can correct it.
        #      unreachable-> write the local mirror AND queue the change, so it
        #                    reaches PostgreSQL when connectivity returns.
        refused = None
        reachable = True
        if self._api is not None:
            result = self._api.update_client(self._client_id, payload)
            if result is None:
                reachable = False
            elif isinstance(result, dict) and "error" in result:
                refused = str(result["error"])
        else:
            reachable = False

        if refused is not None:
            QMessageBox.warning(self, t("common.error"),
                                t("clients.save_failed", error=refused))
            return

        try:
            self._apply_locally(payload, queue_sync=not reachable)
        except Exception as e:
            logger.error("Local client update failed: %s", e)
            QMessageBox.critical(self, t("common.error"),
                                 t("clients.save_failed", error=str(e)))
            return

        self.accept()

    def _upload_document(self, local_path: str):
        """Upload one document, returning the server URL.

        Offline, a durable pending-upload marker is stored instead, so the file
        is uploaded by the sync engine once the server is reachable again.
        """
        if self._api is not None:
            try:
                res = self._api.upload_client_image(local_path)
                if res and res.get("image_url"):
                    return res["image_url"]
            except Exception as e:
                logger.warning("Client document upload failed: %s", e)
        try:
            from app.sync.uploads import store_pending_file
            stored = store_pending_file(local_path)
            return f"pending_uploads/{stored.name}"
        except Exception as e:
            logger.error("Pending upload store failed: %s", e)
        return None

    def _apply_locally(self, payload: dict, queue_sync: bool):
        """Write the same change to the local cache inside one transaction.

        Uses ``DomainStore.mutate`` so the commit publishes exactly one new
        revisioned snapshot — every open widget re-renders from it immediately.
        """
        from app.state.domain_store import get_domain_store
        from app.models.client import LocalClient

        now_iso = datetime.now(timezone.utc).isoformat()
        client_id = self._client_id
        device_id = self._device_id
        user_id = self._user_id

        def _mutate(session):
            row = session.query(LocalClient).filter_by(id=client_id).one_or_none()
            if row is None:
                return
            for key, value in payload.items():
                setattr(row, key, value)
            row.updated_at = now_iso
            row.version = (row.version or 1) + 1

            # A document chosen while the server was unreachable is stored as a
            # `pending_uploads/...` marker. Register it so the pending-upload
            # processor uploads the real file and rewrites the marker — in the
            # client row AND in the queued payload — once the server is back.
            # Without this the marker would stay in PostgreSQL forever and the
            # document would never actually exist server-side.
            from app.sync.uploads import register_pending_upload
            for field, value in payload.items():
                register_pending_upload(
                    session,
                    marker=value or "",
                    entity_type="client",
                    entity_id=client_id,
                    upload_type="CLIENT_DOCUMENT",
                    remote_endpoint="/api/v1/clients/upload-image",
                    field_name=field,
                )

            if queue_sync:
                # The server did not take the write — queue it so the change
                # reaches PostgreSQL as soon as connectivity returns.
                from app.sync.queue import SyncQueue
                queue = SyncQueue(session, device_id, user_id)
                queue.enqueue("client", client_id, "UPDATE",
                              {"id": client_id, "version": row.version, **payload})

        # One commit, one published revision: `mutate` reloads the store and
        # fans out to every view, the clients list included. The details window
        # re-reads its own row when the dialog returns.
        get_domain_store().mutate(_mutate)
