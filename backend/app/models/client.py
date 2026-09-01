from sqlalchemy import Column, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base
from app.models.base import TimestampMixin, VersionMixin, generate_uuid

class Client(Base, TimestampMixin, VersionMixin):
    __tablename__ = "clients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=True, index=True)
    phone = Column(String(20), nullable=True, index=True)
    cin_number = Column(String(50), nullable=True, index=True)
    # Identity documents are two-sided (recto/verso). The legacy single-image
    # columns are the RECTO/front; the *_back columns hold the VERSO/back and
    # stay NULL for historical clients until a back scan is uploaded.
    identity_card_image = Column(Text, nullable=True)
    identity_card_image_back = Column(Text, nullable=True)
    license_number = Column(String(50), nullable=True)
    driving_license_image = Column(Text, nullable=True)
    driving_license_image_back = Column(Text, nullable=True)
    photo_url = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="ACTIVE")

    def __repr__(self):
        return f"<Client(id={self.id}, first_name={self.first_name}, last_name={self.last_name})>"
