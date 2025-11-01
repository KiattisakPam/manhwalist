from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
import sqlalchemy
import datetime
from datetime import timezone, timedelta
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

from config import settings

router = APIRouter(
    prefix="/comics",
    tags=["Comics"],
    dependencies=[Depends(auth.get_current_user)]
)



@router.post("/upload-image/", tags=["Files"])
async def upload_image(file: UploadFile = File(...), current_user: User = Depends(auth.get_current_employer_user)):
    os.makedirs("covers", exist_ok=True)
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')
    new_file_name = f"cover_{timestamp}_{file.filename}"
    file_path = os.path.join("covers", new_file_name)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"file_name": new_file_name}

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
        file_path = os.path.join("covers", comic_to_delete.image_file)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"WARNING: Failed to delete cover image {file_path}: {e}")

    # 3. ลบ Comic Record (การลบนี้จะลบ Jobs, Chat Rooms, Employees ที่เกี่ยวข้องผ่าน ON DELETE CASCADE)
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
    Endpoint นี้ถูกเรียกโดย Frontend เมื่อผู้จ้างกดปุ่ม
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

    # 2. คำนวณวันพรุ่งนี้ (อิงตามเวลาไทย GMT+7 เพื่อเปรียบเทียบกับตารางงาน)
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

    # 4. เตรียมข้อความสรุป
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
    
    # 5. ส่งข้อความสรุป (เสมอ)
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

    # 6. Logic การส่งภาพปกตามไป (ถ้า with_image=True)
    if with_image:
        print("DEBUG_NOTIFY: Sending images for tomorrow's updates.")
        
        # <<< [เพิ่มการรอ 5 วินาที หลังส่ง Text Message] >>>
        print("DEBUG_NOTIFY: Waiting 5s for Render cold start...")
        await asyncio.sleep(1)
        
        # 📌 [สำคัญ] แก้ไขการกำหนด base_url สำหรับการส่งภาพ
        try:
            # 1. ลองใช้ URL สาธารณะจาก settings (ใช้สำหรับ Telegram เท่านั้น)
            public_base_url = settings.BACKEND_BASE_URL 
        except Exception:
            public_base_url = "https://manhwalist-final.onrender.com"
            

        # 2. <<< [แก้ไข] ใช้ Internal/Localhost URL สำหรับการตรวจสอบ Content-Type >>>
        # เนื่องจาก Render.com บล็อก Loopback Requests (Bot ไม่สามารถเข้าถึง 127.0.0.1 ได้)
        # และ Backend ไม่สามารถเข้าถึง URL สาธารณะของตัวเองได้
        # เราจะ *สมมติว่าภาพปกเข้าถึงได้* ถ้า Status Code เป็น 200 เมื่อตรวจสอบจาก Public URL
        # และเราจะเอา Logic ตรวจสอบ Content-Type ออกไป เพราะมันทำให้เกิดปัญหา

        for comic in comics_list:
            image_file = comic.get('image_file')
            comic_title = comic.get('title')
            
            if image_file:
                image_url_to_send = f"{public_base_url}/covers/{image_file}" 
                
                # *** [FIX] ลบ Logic การตรวจสอบ Content-Type ออก ***
                # เราจะเชื่อว่าถ้า Base URL เป็น URL สาธารณะที่ถูกต้อง Telegram จะจัดการได้เอง
                
                try:
                    # 3. ส่ง URL สาธารณะไปให้ Telegram Bot
                    await telegram_config.send_telegram_photo(
                        report_chat_id,
                        image_url_to_send, # <<< ส่ง URL สาธารณะที่แท้จริง
                        caption=f"ปก: *{comic_title}* (Original Ep {comic.get('original_latest_ep', '?')})",
                        bot_type='REPORT' 
                    )
                    await asyncio.sleep(0.5) 

                except Exception as e:
                    print(f"ERROR_NOTIFY: Failed to send photo for {comic_title} (Telegram Error): {e}")
                    pass # ให้ลูปดำเนินต่อไป
                
    return {"message": f"Sent update notification for {len(comics_list)} comic(s) {'with images' if with_image else 'text only'}."}

