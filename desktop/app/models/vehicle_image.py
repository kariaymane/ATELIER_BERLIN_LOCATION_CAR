from sqlalchemy import Column, String, Integer, ForeignKey
from app.database import LocalBase

class LocalVehicleImage(LocalBase):
    __tablename__ = "vehicle_images"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True)
    vehicle_id = Column(String, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False)
    image_url = Column(String, nullable=False)
    sort_order = Column(Integer, default=0)
