from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
import sqlalchemy
import datetime
from datetime import timezone, timedelta
import pathlib
import os
import shutil
from typing import List
import asyncio
import telegram_config

from database import get_db
from models import comics, jobs, employees, users
from schemas import ComicCreate, ComicWithCompletion, ComicUpdate, EpisodeStatus, User
import auth
import httpx
import urllib.parse
from config import settings
import firebase_storage_client

BASE_DIR = pathlib.Path(__file__).parent.parent 
# COVERS_DIR = BASE_DIR / "covers"

router = APIRouter(
    prefix="/comics",
    tags=["Comics"],
    dependencies=[Depends(auth.get_current_user)]
)


# 📌 [FIX] 1. อัปโหลดภาพปก
@router.post("/upload-image/", tags=["Files"])
async def upload_image(file: UploadFile = File(...), current_user: User = Depends(auth.get_current_employer_user)):
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')
    
    # 📌 [FIX] สร้างชื่อ Blob (รวม covers/ เพื่อแยก Folder ใน Storage)
    new_file_name = f"cover_{timestamp}_{file.filename}"
    blob_name = f"covers/{new_file_name}" 
    
    # 📌 [FIX] อ่าน Content และอัปโหลดไป Firebase Storage
    file_bytes = await file.read()

    await firebase_storage_client.upload_file_to_firebase(
        file_bytes, 
        blob_name,
        content_type=file.content_type
    )
    
    return {"file_name": blob_name} # <<< [FIX] คืนค่าชื่อ Blob (covers/filename)



@router.get("/", response_model=List[ComicWithCompletion])
async def get_all_comics(db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_employer_user)):
    # --- แก้ไข Query ให้กรองข้อมูลเฉพาะของ employer ที่ login อยู่ ---
    comics_query = sqlalchemy.select(comics).where(comics.c.employer_id == current_user.id).order_by(comics.c.id.desc())
    comics_result = await db.execute(comics_query)
    comics_list = comics_result.mappings().all()

    response_list = []
    for comic in comics_list:
        completion_query = sqlalchemy.select(sqlalchemy.func.max(jobs.c.episode_number))\
            .where(jobs.c.comic_id == comic.id, jobs.c.status.in_(["COMPLETED", "ARCHIVED"]))
        latest_completed_ep = await db.scalar(completion_query)
        
        comic_data = dict(comic)
        comic_data['latest_employee_completed_ep'] = latest_completed_ep
        response_list.append(ComicWithCompletion.model_validate(comic_data))
        
    return response_list

@router.post("/", status_code=201)
async def create_comic(comic: ComicCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_employer_user)):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    # --- แก้ไข Query ให้เพิ่ม employer_id ตอนสร้าง ---
    query = sqlalchemy.insert(comics).values(
        **comic.model_dump(),
        employer_id=current_user.id, # <<< เพิ่ม employer_id
        last_updated_date=now,
        status_change_date=now
    )
    result = await db.execute(query)
    await db.commit()
    return {"id": result.inserted_primary_key[0], **comic.model_dump()}

@router.get("/{comic_id}/")
async def get_comic_by_id(comic_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_employer_user)):
    # --- แก้ไข Query ให้กรองข้อมูลเฉพาะของ employer ที่ login อยู่ ---
    query = sqlalchemy.select(comics).where(
        sqlalchemy.and_(
            comics.c.id == comic_id, 
            comics.c.employer_id == current_user.id
        )
    )
    comic = (await db.execute(query)).mappings().first()
    if not comic:
        raise HTTPException(status_code=404, detail="Comic not found or not accessible")
    return comic

@router.get("/{comic_id}/episodes/", response_model=List[EpisodeStatus])
async def get_comic_episode_statuses(comic_id: int, db: AsyncSession = Depends(get_db)):
    # --- (ส่วนตรวจสอบ comic เหมือนเดิม) ---
    comic_res = await db.execute(sqlalchemy.select(comics.c.id).where(comics.c.id == comic_id))
    comic = comic_res.mappings().first()
    if not comic:
        raise HTTPException(status_code=404, detail="Comic not found")

    # --- แก้ไข Query ตรงนี้ให้เสถียรขึ้น ---
    jobs_query = (
        sqlalchemy.select(
            jobs.c.episode_number,
            jobs.c.status,
            jobs.c.id.label("job_id"),
            employees.c.name.label("employee_name"),
            jobs.c.employee_finished_file,
            jobs.c.task_type
        )
        # ระบุตารางที่จะ Join ให้ชัดเจนขึ้น และใช้ LEFT OUTER JOIN (isouter=True)
        .select_from(jobs.join(employees, jobs.c.employee_id == employees.c.id, isouter=True))
        .where(jobs.c.comic_id == comic_id)
        .order_by(jobs.c.episode_number)
    )
    # ------------------------------------
    
    jobs_result = await db.execute(jobs_query)
    
    all_jobs_for_comic = [
        EpisodeStatus(
            episode_number=j.episode_number,
            status=j.status,
            job_id=j.job_id,
            employee_name=j.employee_name,
            task_type=j.task_type,
            finished_file_url=f"/job-files/{j.employee_finished_file}" if j.employee_finished_file else None,
        ) for j in jobs_result.mappings().all()
    ]
    return all_jobs_for_comic



@router.put("/{comic_id}/")
async def update_comic(comic_id: int, comic_update: ComicUpdate, db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_employer_user)):
    # --- เพิ่ม Logic ตรวจสอบความเป็นเจ้าของก่อนแก้ไข ---
    comic_to_update_res = await db.execute(sqlalchemy.select(comics).where(comics.c.id == comic_id))
    comic_to_update = comic_to_update_res.mappings().first()

    if not comic_to_update:
        raise HTTPException(status_code=404, detail="Comic not found")
    if comic_to_update.employer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this comic")
    # ---------------------------------------------
        
    update_data = comic_update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No update data provided")
    
    update_data['last_updated_date'] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    query = sqlalchemy.update(comics).where(comics.c.id == comic_id).values(**update_data)
    await db.execute(query)
    await db.commit()
    return {"message": "Comic updated successfully"}

@router.delete("/{comic_id}/", status_code=200)
async def delete_comic(comic_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_employer_user)):
    # 1. ตรวจสอบความเป็นเจ้าของ
    comic_res = await db.execute(
        sqlalchemy.select(comics).where(
            sqlalchemy.and_(
                comics.c.id == comic_id, 
                comics.c.employer_id == current_user.id
            )
        )
    )
    comic_to_delete = comic_res.mappings().first()

    if not comic_to_delete:
        raise HTTPException(status_code=404, detail="Comic not found or not accessible")

    # 2. ลบไฟล์ภาพปกจริง (ถ้ามี)
    if comic_to_delete.image_file:
        blob_name = comic_to_delete.image_file # image_file คือ blob_name
        try:
            # 📌 [FIX] ลบจาก Firebase Storage
            await firebase_storage_client.delete_file_from_firebase(blob_name) 
        except Exception as e:
            print(f"WARNING: Failed to delete cover image from Firebase: {e}")

    # 3. ลบ Comic Record 
    delete_query = sqlalchemy.delete(comics).where(comics.c.id == comic_id)
    await db.execute(delete_query)
    await db.commit()

    return {"message": "Comic and all associated data deleted successfully"}


@router.post("/auto-update", status_code=200)
async def auto_update_comics(db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_employer_user)):
    """ตรวจสอบการ์ตูนทั้งหมดของ Employer ว่าถึงวันอัปเดตตามตารางหรือไม่ แล้วเพิ่ม original_latest_ep"""
    
    # 1. ดึงการ์ตูนทั้งหมดของ Employer ปัจจุบัน
    comics_query = sqlalchemy.select(comics).where(comics.c.employer_id == current_user.id)
    comics_result = await db.execute(comics_query)
    comics_list = comics_result.mappings().all()

    updates_made = 0
    today_date = datetime.date.today()
    today_iso = today_date.isoformat()
    today_day_of_week = today_date.strftime('%A').upper() # เช่น MONDAY
    today_day_of_month = str(today_date.day)

    for comic in comics_list:
        # 2. ตรวจสอบเงื่อนไขการอัปเดต (เมื่อสถานะเป็น ACTIVE เท่านั้น)
        if comic.status == 'ACTIVE' and comic.update_type:
            
            should_update = False
            last_update_date = datetime.datetime.fromisoformat(comic.last_updated_date).date()
            
            # ป้องกันการอัปเดตซ้ำในวันเดียวกัน
            if last_update_date == today_date:
                continue

            # ตรวจสอบ WEEKLY
            if comic.update_type == 'WEEKLY' and comic.update_value == today_day_of_week:
                should_update = True
            
            # ตรวจสอบ MONTHLY
            elif comic.update_type == 'MONTHLY' and comic.update_value and today_day_of_month in comic.update_value.split(','):
                should_update = True
                
            if should_update:
                new_latest_ep = comic.original_latest_ep + 1 # เพิ่ม 1 ตอน
                
                await db.execute(
                    sqlalchemy.update(comics).where(comics.c.id == comic.id).values(
                        original_latest_ep=new_latest_ep,
                        last_updated_date=today_iso
                    )
                )
                updates_made += 1

    if updates_made > 0:
        await db.commit()
    
    return {"message": f"Auto update complete. {updates_made} comic(s) were updated."}


async def get_comics_to_update_tomorrow(db: AsyncSession, employer_id: int) -> List[dict]:
    """ดึงรายการการ์ตูนของ employer ที่มีกำหนดอัปเดตในวันพรุ่งนี้ (ตาม UTC)"""
    
    # 1. คำนวณวันพรุ่งนี้ (ใน Timezone ที่ Server ใช้)
    # NOTE: หาก server ใช้ UTC ให้ใช้ datetime.datetime.now(datetime.timezone.utc) + timedelta(days=1)
    # แต่เนื่องจากตารางบันทึกวันเป็น String เราจะใช้ วันพรุ่งนี้ที่เป็น UTC
    
    tomorrow_date = datetime.datetime.now(datetime.timezone.utc).date() + datetime.timedelta(days=1)
    
    tomorrow_day_of_week = tomorrow_date.strftime('%A').upper() # เช่น TUESDAY
    tomorrow_day_of_month = str(tomorrow_date.day)
    
    # 2. สร้าง Query: ดึงเฉพาะ ACTIVE และตรงตาม Update Value
    query = sqlalchemy.select(comics).where(
        sqlalchemy.and_(
            comics.c.employer_id == employer_id,
            comics.c.status == 'ACTIVE',
            comics.c.update_type.isnot(None),
            # ตรวจสอบ WEEKLY หรือ MONTHLY
            sqlalchemy.or_(
                # WEEKLY: type=WEEKLY AND value=TUESDAY
                sqlalchemy.and_(
                    comics.c.update_type == 'WEEKLY',
                    comics.c.update_value == tomorrow_day_of_week
                ),
                # MONTHLY: type=MONTHLY AND value contains '3' (วันที่ 3)
                sqlalchemy.and_(
                    comics.c.update_type == 'MONTHLY',
                    comics.c.update_value.contains(tomorrow_day_of_month)
                )
            )
        )
    )
    
    result = await db.execute(query)
    return result.mappings().all()

@router.post("/notify-tomorrow-updates", status_code=200)
async def notify_tomorrow_updates(
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(auth.get_current_employer_user),
    with_image: bool = Query(False)
):
    """
    ตรวจสอบการ์ตูนที่จะอัปเดตวันพรุ่งนี้ และส่ง Telegram Notification (Report Bot)
    ใช้ File System Read และ Document Upload เพื่อส่งไฟล์ภาพเป็นชื่อเรื่อง
    """
    employer_id = current_user.id
    
    # 1. ดึง Report Chat ID และตรวจสอบ
    employer_chat_res = await db.execute(
        sqlalchemy.select(users.c.telegram_report_chat_id)
        .where(users.c.id == employer_id)
    )
    report_chat_id = employer_chat_res.scalar_one_or_none()
    
    print(f"DEBUG_NOTIFY: Fetched Report Chat ID: {report_chat_id}")
    
    if not report_chat_id:
        print(f"WARNING: Report Chat ID not found for employer {employer_id}")
        return {"message": "Employer Report Chat ID not set. Skipping notification."}

    # 2. คำนวณวันพรุ่งนี้
    THAI_TZ = timezone(timedelta(hours=7)) 
    now_thai = datetime.datetime.now(THAI_TZ)
    tomorrow_date = now_thai.date() + datetime.timedelta(days=1)
    
    tomorrow_day_of_week = tomorrow_date.strftime('%A').upper() 
    tomorrow_day_of_month = str(tomorrow_date.day)
    
    # 3. ดึงรายการการ์ตูนที่จะอัปเดตวันพรุ่งนี้
    comics_query = sqlalchemy.select(comics).where(
        sqlalchemy.and_(
            comics.c.employer_id == employer_id,
            comics.c.status == 'ACTIVE',
            sqlalchemy.or_(
                sqlalchemy.and_(
                    comics.c.update_type == 'WEEKLY',
                    comics.c.update_value == tomorrow_day_of_week
                ),
                sqlalchemy.and_(
                    comics.c.update_type == 'MONTHLY',
                    comics.c.update_value.contains(tomorrow_day_of_month)
                )
            )
        )
    )
    comics_list = (await db.execute(comics_query)).mappings().all()

    print(f"DEBUG_NOTIFY: Found {len(comics_list)} comics for tomorrow's update.")
    
    if not comics_list:
        return {"message": "No comics scheduled for update tomorrow."}

    # 4. เตรียมข้อความสรุป (Final Message)
    message_parts = [
        f"🌟 *แจ้งเตือนอัปเดตวันพรุ่งนี้ ({tomorrow_date.strftime('%d/%m')})* 🌟",
        f"รายการการ์ตูน ({len(comics_list)} เรื่อง) ที่มีกำหนดอัปเดต:",
        ""
    ]
    
    for i, comic in enumerate(comics_list):
        detail = f"กำหนด: {comic['update_type']} ({comic['update_value']})"
        message_parts.append(f"{i+1}. *{comic['title']}*")
        message_parts.append(f"  _ล่าสุด (ทำแล้ว):_ Ep {comic['last_updated_ep']}")
        message_parts.append(f"  _ต้นฉบับถึง:_ Ep {comic['original_latest_ep']}")
        message_parts.append(f"  _{detail}_\n")

    final_message = "\n".join(message_parts)
    
    # 5. Logic การส่ง
    if with_image:
        print("DEBUG_NOTIFY: Sending images (using File System Read and Document Upload).")
        
        await asyncio.sleep(1) 
        
        # 📌 [FIX] ใช้ settings.BACKEND_BASE_URL (ไม่ใช้แล้วเพราะเปลี่ยนเป็น File Read)
        # base_url = settings.BACKEND_BASE_URL.replace("http://", "https://") 
        
        # 5.2. ส่งภาพปกทีละภาพ (Binary Document Upload)
        for i, comic in enumerate(comics_list): 
            image_file_name_with_path = comic.get('image_file') # image_file คือ blob_name (covers/filename)
            
            if image_file_name_with_path:
                
                # 📌 [FIX] ดึงชื่อไฟล์และนามสกุลที่ถูกต้อง
                original_file_name = os.path.basename(image_file_name_with_path)
                original_extension = os.path.splitext(original_file_name)[1]
                
                # ใช้ชื่อเรื่อง + นามสกุลไฟล์เดิม
                telegram_file_name = f"{comic['title']}{original_extension}" 
                
                # 📌 [FIX] สร้าง Caption
                caption_details = (
                    f"*{comic['title']}*\n"
                    f"ล่าสุด: Ep {comic['last_updated_ep']}\n"
                    f"ต้นฉบับ: Ep {comic['original_latest_ep']}\n"
                    f"กำหนด: {comic['update_type']} ({comic['update_value']})"
                )
                
                try:
                    # 1. อ่าน Binary Data จาก Firebase Storage (File System Read)
                    image_bytes = await firebase_storage_client.download_file_from_firebase(image_file_name_with_path)
                    
                    if image_bytes is None:
                        raise FileNotFoundError(f"Cover file not found in Firebase Storage: {image_file_name_with_path}")
                        
                    # 2. อัปโหลด Binary Data ไปยัง Telegram เป็น Document
                    await telegram_config.send_telegram_document_in_memory(
                        report_chat_id, 
                        image_bytes,
                        filename=telegram_file_name, 
                        caption=caption_details, 
                        bot_type='REPORT'
                    )
                    print(f"INFO: Successfully sent document {i+1} for {comic['title']}.")
                except Exception as e:
                    print(f"ERROR: Failed to send document {i+1} (Firebase Read Error): {e}")
        
        return {"message": "Sent update notification... (via file read upload)."}
    
    # 6. ถ้า with_image=False ให้ส่งแค่ข้อความสรุป
    else:
        print(f"DEBUG_NOTIFY: Attempting to send text message (Bot B) to Chat ID: {report_chat_id}")
        try:
            await telegram_config.send_telegram_notification(
                report_chat_id, 
                final_message,
                bot_type='REPORT' 
            )
            print("DEBUG_NOTIFY: Text notification sent successfully.")
        except Exception as e:
            print(f"ERROR_NOTIFY: Failed to send text notification: {e}")
            
        return {"message": f"Sent update notification for {len(comics_list)} comic(s) (text only)."}
    
    

    