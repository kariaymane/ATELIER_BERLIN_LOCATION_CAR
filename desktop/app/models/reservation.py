"""
SQLite local model for Reservation.
"""
from sqlalchemy import Column, String, Integer, Float, Text
from app.database import LocalBase


class LocalReservation(LocalBase):
    __tablename__ = "reservations"

    id = Column(String(36), primary_key=True)
    vehicle_id = Column(String(36), nullable=False)
    customer_id = Column(String(36), nullable=True)  # canonical Client link
    customer_name = Column(String(255), nullable=True)
    customer_phone = Column(String(20), nullable=True)
    customer_email = Column(String(255), nullable=True)
    identity_card_image = Column(Text, nullable=True)
    driving_license_image = Column(Text, nullable=True)
    start_datetime = Column(String(50), nullable=False)
    end_datetime = Column(String(50), nullable=False)
    daily_price = Column(Float, nullable=False)
    num_days = Column(Integer, nullable=False)
    total_price = Column(Float, nullable=False)
    deposit = Column(Float, nullable=False, default=0.0)
    payment_status = Column(String(20), nullable=False, default="PENDING")
    status = Column(String(20), nullable=False, default="RESERVED")
    # Machine-readable cause when status == 'CANCELLED' (e.g. 'MAINTENANCE').
    # The human translation lives in the i18n layer, never here.
    cancellation_reason = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(String(30), nullable=False)
    updated_at = Column(String(30), nullable=False)
    version = Column(Integer, nullable=False, default=1)
