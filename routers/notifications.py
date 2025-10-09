from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
import sqlalchemy

from database import get_db
from models import fcm_devices
from schemas import User
import auth

router = APIRouter(
    prefix="/notifications",
    tags=["Notifications"],
    dependencies=[Depends(auth.get_current_user)]
)

class DeviceRegistration(BaseModel):
    device_token: str

@router.post("/register-device")
async def register_device(
    payload: DeviceRegistration,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth.get_current_user)
):
    query = sqlalchemy.select(fcm_devices).where(fcm_devices.c.device_token == payload.device_token)
    existing = (await db.execute(query)).first()
    
    if existing:
        update_query = sqlalchemy.update(fcm_devices).where(fcm_devices.c.device_token == payload.device_token).values(user_id=current_user.id, is_active=True)
        await db.execute(update_query)
    else:
        insert_query = sqlalchemy.insert(fcm_devices).values(user_id=current_user.id, device_token=payload.device_token)
        await db.execute(insert_query)
        
    await db.commit()
    return {"message": "Device registered successfully"}
