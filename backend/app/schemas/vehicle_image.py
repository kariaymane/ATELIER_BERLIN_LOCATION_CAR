from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

class VehicleImageResponse(BaseModel):
    id: UUID
    vehicle_id: UUID
    image_url: str
    sort_order: int
    created_at: datetime

    model_config = {"from_attributes": True}
