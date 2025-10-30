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
    """ลงทะเบียนหรืออัปเดต Device Token สำหรับ FCM"""
    token = payload.device_token
    user_id = current_user.id
    
    # 1. ตรวจสอบว่า Token นี้มีอยู่แล้วหรือไม่
    query = sqlalchemy.select(fcm_devices).where(fcm_devices.c.device_token == token)
    existing = (await db.execute(query)).first()

    if existing:
        # 2. ถ้ามี: อัปเดตข้อมูล (อาจจะเปลี่ยนเจ้าของ หรือแค่เปิดใช้งาน)
        update_query = sqlalchemy.update(fcm_devices).where(fcm_devices.c.device_token == token).values(
            user_id=user_id, 
            is_active=True,
            updated_at=datetime.datetime.now().isoformat() # [เสริม] เพิ่มคอลัมน์ updated_at ใน models ถ้ามี
        )
        await db.execute(update_query)
        print(f"INFO: Updated existing FCM device token for User ID {user_id}")
    else:
        # 3. ถ้าไม่มี: เพิ่ม Token ใหม่
        insert_query = sqlalchemy.insert(fcm_devices).values(
            user_id=user_id, 
            device_token=token,
            is_active=True,
            created_at=datetime.datetime.now().isoformat() # [เสริม] เพิ่มคอลัมน์ created_at ใน models ถ้ามี
        )
        await db.execute(insert_query)
        print(f"INFO: Registered new FCM device token for User ID {user_id}")

    await db.commit()
    return {"message": "Device registered successfully"}

# [เพิ่มเติม] Endpoint สำหรับยกเลิกการลงทะเบียน
@router.post("/unregister-device")
async def unregister_device(
    payload: DeviceRegistration,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth.get_current_user)
):
    """ปิดใช้งาน (Soft Delete) Device Token"""
    token = payload.device_token
    
    # แทนที่จะลบทิ้ง ให้ set is_active = False เพื่อเก็บประวัติไว้
    update_query = sqlalchemy.update(fcm_devices).where(
        fcm_devices.c.device_token == token,
        fcm_devices.c.user_id == current_user.id # เพิ่มเงื่อนไข user_id เพื่อความปลอดภัย
    ).values(is_active=False) 
    
    await db.execute(update_query)
    await db.commit()
    
    return {"message": "Device unregistered (deactivated) successfully"}

