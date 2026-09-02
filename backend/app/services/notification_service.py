"""
Notification service — monitors document expirations and maintenance alerts,
and provides retrieval / read status management.
"""
from typing import Optional
from uuid import UUID
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.vehicle import Vehicle
from app.models.maintenance import Maintenance
from app.schemas.notification import NotificationResponse
import logging

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def scan_and_generate_notifications(self) -> int:
        """
        Scan vehicles and maintenance records to create alerts for document
        expirations and maintenance events.
        """
        from shared.money_time import now_business
        today = now_business().date()
        warning_window = today + timedelta(days=15)
        created_count = 0

        # 1. Scan Vehicle Documents
        vehicles_result = await self._session.execute(select(Vehicle))
        vehicles = vehicles_result.scalars().all()

        for v in vehicles:
            v_name = f"{v.brand} {v.model}"
            v_reg = v.registration
            doc_checks = [
                ("Assurance", v.assurance_expiry, "assurance"),
                ("Vignette", v.vignette_expiry, "vignette"),
                ("Visite technique", v.visite_technique_expiry, "visite_technique"),
                ("Carte grise", v.carte_grise_expiry, "carte_grise"),
                (v.autres_label or "Document spécifique", v.autres_expiry, "autre"),
            ]

            for doc_label, expiry_dt, doc_key in doc_checks:
                if not expiry_dt:
                    continue

                if expiry_dt < today:
                    severity = "expired"
                    title = f"{doc_label} expirée - {v_name}"
                    message = f"Le document '{doc_label}' du véhicule {v_name} ({v_reg}) a expiré le {expiry_dt.isoformat()}. Action immédiate requise."
                elif expiry_dt <= warning_window:
                    severity = "warning"
                    title = f"Échéance {doc_label} proche - {v_name}"
                    message = f"Le document '{doc_label}' du véhicule {v_name} ({v_reg}) arrive à expiration le {expiry_dt.isoformat()}."
                else:
                    continue

                # Check if notification already exists for this vehicle, doc_key and expiry_dt
                notif_type = f"DOC_EXPIRY_{doc_key.upper()}"
                existing_result = await self._session.execute(
                    select(Notification).where(
                        Notification.vehicle_id == v.id,
                        Notification.type == notif_type,
                        Notification.due_date == expiry_dt,
                        Notification.severity == severity
                    )
                )
                if existing_result.scalars().first() is None:
                    notif = Notification(
                        vehicle_id=v.id,
                        type=notif_type,
                        severity=severity,
                        title=title,
                        message=message,
                        due_date=expiry_dt,
                        is_read=False
                    )
                    self._session.add(notif)
                    created_count += 1

        # 2. Scan Maintenance Events
        maint_result = await self._session.execute(
            select(Maintenance, Vehicle)
            .join(Vehicle, Maintenance.vehicle_id == Vehicle.id)
            .where(Maintenance.status == "ACTIVE")
        )
        maintenances = maint_result.all()

        for m, v in maintenances:
            v_name = f"{v.brand} {v.model}"
            m_type = m.type
            m_desc = m.description or "Entretien requis"
            m_step = m.step or "DIAGNOSTIC"
            m_start = m.start_datetime.date() if isinstance(m.start_datetime, datetime) else today

            title = f"Maintenance requise : {v_name}"
            message = f"Intervention ({m_type} - {m_step}) nécessaire pour {v_name} ({v.registration}). Description : {m_desc}"
            severity = "maintenance_required"

            notif_type = f"MAINTENANCE_{m_step}"
            existing_result = await self._session.execute(
                select(Notification).where(
                    Notification.vehicle_id == v.id,
                    Notification.type == notif_type,
                    Notification.due_date == m_start,
                )
            )
            if existing_result.scalars().first() is None:
                notif = Notification(
                    vehicle_id=v.id,
                    type=notif_type,
                    severity=severity,
                    title=title,
                    message=message,
                    due_date=m_start,
                    is_read=False
                )
                self._session.add(notif)
                created_count += 1

        if created_count > 0:
            await self._session.flush()
            logger.info("Generated %d new automated notifications", created_count)

        return created_count

    async def list_notifications(
        self,
        page: int = 1,
        page_size: int = 25,
        unread_only: bool = False,
    ) -> dict:
        """List notifications with joined vehicle metadata."""
        # First trigger scan to guarantee up-to-date notifications
        await self.scan_and_generate_notifications()

        stmt = select(Notification, Vehicle).outerjoin(Vehicle, Notification.vehicle_id == Vehicle.id)
        if unread_only:
            stmt = stmt.where(Notification.is_read == False)

        # Count total
        count_stmt = select(func.count(Notification.id))
        if unread_only:
            count_stmt = count_stmt.where(Notification.is_read == False)
        total_res = await self._session.execute(count_stmt)
        total = total_res.scalar() or 0

        # Count unread
        unread_res = await self._session.execute(
            select(func.count(Notification.id)).where(Notification.is_read == False)
        )
        unread_count = unread_res.scalar() or 0

        stmt = stmt.order_by(Notification.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(stmt)).all()

        items = []
        for notif, veh in rows:
            items.append(
                NotificationResponse(
                    id=str(notif.id),
                    vehicle_id=str(notif.vehicle_id) if notif.vehicle_id else None,
                    vehicle_name=f"{veh.brand} {veh.model}" if veh else None,
                    vehicle_registration=veh.registration if veh else None,
                    type=notif.type,
                    severity=notif.severity,
                    title=notif.title,
                    message=notif.message,
                    due_date=notif.due_date,
                    is_read=notif.is_read,
                    created_at=notif.created_at,
                )
            )

        return {
            "items": items,
            "total": total,
            "unread_count": unread_count,
            "page": page,
            "page_size": page_size,
        }

    async def create_notification(
        self,
        vehicle_id: Optional[UUID],
        type: str,
        severity: str,
        title: str,
        message: str,
        due_date: Optional[date] = None,
        user_id: Optional[UUID] = None,
        origin: str = "API",
    ) -> Notification:
        """
        Create a single persisted notification record in PostgreSQL and broadcast to Desktop and Mobile.
        Prevents duplicate unread notifications for the same vehicle and type.
        """
        # Deduplication check: if unread notification with same type & vehicle exists, update it
        if vehicle_id:
            stmt = select(Notification).where(
                Notification.vehicle_id == vehicle_id,
                Notification.type == type,
                Notification.is_read == False
            )
            existing = (await self._session.execute(stmt)).scalars().first()
            if existing:
                existing.message = message
                existing.title = title
                existing.severity = severity
                existing.due_date = due_date or existing.due_date
                existing.updated_at = datetime.now(timezone.utc)
                await self._session.flush()
                notif = existing
            else:
                notif = Notification(
                    vehicle_id=vehicle_id,
                    type=type,
                    severity=severity,
                    title=title,
                    message=message,
                    due_date=due_date,
                    is_read=False,
                    user_id=user_id,
                )
                self._session.add(notif)
                await self._session.flush()
        else:
            notif = Notification(
                vehicle_id=vehicle_id,
                type=type,
                severity=severity,
                title=title,
                message=message,
                due_date=due_date,
                is_read=False,
                user_id=user_id,
            )
            self._session.add(notif)
            await self._session.flush()

        # Fetch vehicle registration if available
        v_reg = None
        if vehicle_id:
            v_res = await self._session.execute(select(Vehicle).where(Vehicle.id == vehicle_id))
            v_obj = v_res.scalar_one_or_none()
            if v_obj:
                v_reg = v_obj.registration

        # Broadcast unified real-time event
        try:
            from app.services.event_broadcaster import broadcaster
            await broadcaster.broadcast_event(
                event_type="NOTIFICATION_CREATED",
                entity_type="notification",
                entity_id=str(notif.id),
                message=message,
                origin=origin,
                vehicle_id=str(vehicle_id) if vehicle_id else None,
                vehicle_registration=v_reg,
                data={
                    "notification_id": str(notif.id),
                    "type": notif.type,
                    "severity": notif.severity,
                    "title": notif.title,
                    "message": notif.message,
                    "due_date": notif.due_date.isoformat() if notif.due_date else None,
                    "is_read": notif.is_read,
                    "created_at": notif.created_at.isoformat() if notif.created_at else datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception as e:
            logger.warning("Broadcaster notification dispatch warning: %s", e)

        return notif

    async def get_unread_count(self) -> int:
        """Get unread count."""
        await self.scan_and_generate_notifications()
        res = await self._session.execute(
            select(func.count(Notification.id)).where(Notification.is_read == False)
        )
        return res.scalar() or 0

    async def mark_as_read(self, notification_id: UUID) -> bool:
        """Mark a single notification as read and broadcast event."""
        stmt = update(Notification).where(Notification.id == notification_id).values(is_read=True)
        res = await self._session.execute(stmt)
        if res.rowcount > 0:
            try:
                from app.services.event_broadcaster import broadcaster
                await broadcaster.broadcast_event(
                    event_type="NOTIFICATION_READ",
                    entity_type="notification",
                    entity_id=str(notification_id),
                    message="Notification marquée comme lue",
                    origin="API",
                    data={"notification_id": str(notification_id), "is_read": True}
                )
            except Exception as e:
                logger.warning("Broadcaster mark_read dispatch warning: %s", e)
            return True
        return False

    async def mark_all_read(self) -> int:
        """Mark all notifications as read and broadcast event."""
        stmt = update(Notification).where(Notification.is_read == False).values(is_read=True)
        res = await self._session.execute(stmt)
        if res.rowcount > 0:
            try:
                from app.services.event_broadcaster import broadcaster
                await broadcaster.broadcast_event(
                    event_type="NOTIFICATIONS_ALL_READ",
                    entity_type="notification",
                    entity_id="ALL",
                    message="Toutes les notifications marquées comme lues",
                    origin="API",
                    data={"all_read": True}
                )
            except Exception as e:
                logger.warning("Broadcaster mark_all_read dispatch warning: %s", e)
        return res.rowcount
