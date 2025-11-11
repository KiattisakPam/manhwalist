from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
import sqlalchemy
import datetime
import os
import shutil
from typing import Optional, List

# [OK] Import notification_manager
from models import fcm_devices 
from database import get_db
from models import jobs, comics, employees, users, fcm_devices, job_supplemental_files
from schemas import User, JobWithComicInfo, JobSupplementalFile
import auth
import firebase_config
from routers.chat import notification_manager
import telegram_config # <<< [สำคัญ] เพิ่ม Import Telegram Config
import firebase_storage_client


router = APIRouter(
    prefix="/jobs",
    tags=["Jobs"],
    dependencies=[Depends(auth.get_current_user)]
)

@router.get("/all/", response_model=List[JobWithComicInfo])
async def get_all_jobs(db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_employer_user)):
    query = sqlalchemy.select(
        jobs.c.id, jobs.c.comic_id, jobs.c.employee_id, jobs.c.episode_number, jobs.c.task_type, jobs.c.rate, jobs.c.status, jobs.c.assigned_date, jobs.c.completed_date,
        employees.c.name.label("employee_name"),
        comics.c.title.label("comic_title"),
        comics.c.image_file.label("comic_image_file")
    ).select_from(
        jobs.join(employees, jobs.c.employee_id == employees.c.id)
            .join(comics, jobs.c.comic_id == comics.c.id)
    ).where(comics.c.employer_id == current_user.id).order_by(sqlalchemy.desc(jobs.c.assigned_date))
    result = await db.execute(query)
    return result.mappings().all()

@router.post("/", status_code=201)
async def create_job(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth.get_current_employer_user),
    comic_id: int = Form(...),
    employee_id: int = Form(...),
    episode_number: int = Form(...),
    task_type: str = Form(...),
    rate: float = Form(...),
    telegram_link: Optional[str] = Form(None), 
    work_file: UploadFile = File(...),
    supplemental_file: Optional[UploadFile] = File(None),
    supplemental_file_comment: Optional[str] = Form(None)
):
    comic_res = await db.execute(sqlalchemy.select(comics).where(comics.c.id == comic_id))
    comic = comic_res.mappings().first()
    if not comic or comic.employer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Comic not found or not owned by user")

    employee_res = await db.execute(sqlalchemy.select(employees).where(employees.c.id == employee_id))
    employee = employee_res.mappings().first()
    if not employee or employee.employer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Employee not found or not owned by user")
        
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')

    work_file_bytes = await work_file.read()
    
    # 1. อัปโหลดไฟล์งานหลักไป Firebase
    work_file_name = f"work_{timestamp}_ep{episode_number}_{work_file.filename}"
    work_blob_name = f"job_files/{work_file_name}"
    
    final_work_blob_name_in_db = await firebase_storage_client.upload_file_to_firebase(
        work_file_bytes, 
        work_blob_name,
        content_type=work_file.content_type
    )

    final_supp_blob_name_in_db = None
    if supplemental_file:
        # 📌 [CRITICAL FIX 2] อ่าน supplemental_file เป็น bytes
        supp_file_bytes = await supplemental_file.read() 

        # 2. อัปโหลดไฟล์เสริมเริ่มต้นไป Firebase
        supplemental_file_name = f"supp_{timestamp}_ep{episode_number}_{supplemental_file.filename}"
        supplemental_blob_name = f"job_files/{supplemental_file_name}"
        
        # 📌 [FIX] ใช้ supp_file_bytes ที่อ่านแล้ว
        final_supp_blob_name_in_db = await firebase_storage_client.upload_file_to_firebase(
            supp_file_bytes, 
            supplemental_blob_name,
            content_type=supplemental_file.content_type
        )
        
    # 📌 [CRITICAL FIX]: ใช้ Blob Name ที่ถูกต้องในการบันทึก DB
    job_data = {
        "comic_id": comic_id, "employee_id": employee_id, "episode_number": episode_number,
        "task_type": task_type, "rate": rate, "assigned_date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "employer_work_file": final_work_blob_name_in_db,
        "telegram_link": telegram_link,
        "supplemental_file": final_supp_blob_name_in_db if supplemental_file else None,
        "supplemental_file_comment": supplemental_file_comment,
        "last_telegram_activity": "NEW_JOB", 
    }
    
    res = await db.execute(sqlalchemy.insert(jobs).values(**job_data))
    await db.commit()
    
    new_job_id = res.inserted_primary_key[0]
    
    # 📌 กำหนดกิจกรรมปัจจุบัน (สำหรับอัปเดตสถานะสุดท้าย)
    current_activity = 'NEW_JOB'
    
    try:
        # ... (โค้ดส่ง Notification - ปล่อยไว้เหมือนเดิม) ...
        # 1. ดึงข้อมูล User ID, ชื่อพนักงาน, และ Chat ID (จาก employees)
        emp_info_res = await db.execute(
            sqlalchemy.select(employees.c.user_id, employees.c.name, employees.c.telegram_chat_id)
            .where(employees.c.id == employee_id)
        )
        emp_info = emp_info_res.mappings().first()
        
        emp_user_id = emp_info.user_id if emp_info else None
        employee_name = emp_info.name if emp_info else "พนักงาน"
        telegram_chat_id = emp_info.telegram_chat_id if emp_info else None 

        # --- [เพิ่ม] DEBUG PRINT ตรงนี้ ---
        print(f"DEBUG_TELEGRAM: Attempting to notify job {new_job_id}")
        print(f"DEBUG_TELEGRAM: Employee ID: {employee_id}, Found Chat ID: {telegram_chat_id}")
        # ---------------------------------
        
        # 2. ดึง Token ของอุปกรณ์ (ถ้ามี User ID)
        tokens = []
        if emp_user_id:
            token_query = sqlalchemy.select(fcm_devices.c.device_token).where(
                fcm_devices.c.user_id == emp_user_id, 
                fcm_devices.c.is_active == True
            )
            tokens = (await db.execute(token_query)).scalars().all()
            
        # 3. เตรียมข้อมูล Notification
        comic_title = comic.title
        title = f"💼 งาน{task_type}ใหม่!"
        body = f"คุณได้รับงาน '{task_type}' ตอนที่ {episode_number} ของเรื่อง '{comic_title}'"
        
        if telegram_chat_id:
            # 📌 งานใหม่: ต้องแสดงหัวข้อเต็มเสมอ
            telegram_message = (
                f"*{title}* "
                # f"มอบหมายงานให้: *{employee_name}*\n" 
                f"เรื่อง: *{comic_title}* ตอนที่ {episode_number}"
                # f"ประเภท: *{task_type}*" # <<< ลบลิงก์ออกทั้งหมด
            )
            await telegram_config.send_telegram_notification(
                telegram_chat_id, 
                telegram_message,
                bot_type='NOTIFY' # <<< [สำคัญ] ใช้ Bot A (NOTIFY) สำหรับงานใหม่
            )
            
        # 📌 อัปเดตกิจกรรมล่าสุดในฐานข้อมูล (ถ้ามีการส่ง Telegram)
        if telegram_chat_id:
             await db.execute(sqlalchemy.update(jobs).where(jobs.c.id == new_job_id).values(
                last_telegram_activity=current_activity
            ))
             await db.commit()
             
        if emp_user_id:
            # 4.1. ส่ง Real-time Update (Bridge App)
            bridge_message = {
                "type": "NEW_JOB",
                "title": title,
                "body": body,
                "job_id": new_job_id,
            }
            await notification_manager.send_personal_notification(emp_user_id, bridge_message)
            
            # 4.2. ส่ง FCM (Push Notification สำรอง)
            if tokens:
                firebase_config.send_notification(
                    tokens=tokens,
                    title=title, 
                    body=body,
                    data={"type": "new_job", "job_id": str(new_job_id)}
                )
    except Exception as e:
        print(f"Failed to send new job notification: {e}")
    
    # 🛑 [FIX 1] แก้ไขเรื่อง 'Null' Error 🛑
    # สร้าง response data และแปลงค่า None ให้เป็น "" เพื่อป้องกัน Flutter error
    response_data = job_data.copy()
    response_data["id"] = new_job_id
    response_data["telegram_link"] = response_data.get("telegram_link") or "" 
    response_data["supplemental_file_comment"] = response_data.get("supplemental_file_comment") or ""
    
    response_data["supplemental_file"] = response_data.get("supplemental_file") 

    return response_data
    # (ลบ return {"id": new_job_id, **job_data} ของเก่าทิ้ง)

@router.put("/{job_id}/complete")
async def employee_complete_job(job_id: int, db: AsyncSession = Depends(get_db), finished_file: UploadFile = File(...), current_user: User = Depends(auth.get_current_user)):
    job_res = await db.execute(sqlalchemy.select(jobs).where(jobs.c.id == job_id))
    job = job_res.mappings().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # 1. ตรวจสอบสิทธิ์: ต้องเป็นพนักงานที่ได้รับมอบหมายงานนี้เท่านั้น
    emp_res = await db.execute(sqlalchemy.select(employees.c.user_id, employees.c.name).where(employees.c.id == job.employee_id))
    employee_info = emp_res.mappings().first()
    if employee_info.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to complete this job")
    
    employee_name = employee_info.name
    current_activity = 'JOB_COMPLETE' 

    # 2. บันทึกไฟล์ที่เสร็จแล้วไป Firebase
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')
    new_file_name = f"fin_{timestamp}_ep{job['episode_number']}_{finished_file.filename}"
    new_blob_name = f"job_files/{new_file_name}"
    
    file_bytes = await finished_file.read()
    await firebase_storage_client.upload_file_to_firebase(
        file_bytes, 
        new_blob_name,
        content_type=finished_file.content_type
    )
    
    # 3. ลบไฟล์เก่าจาก Firebase Storage อย่างปลอดภัย
    if job.get('employee_finished_file'):
        old_blob_name = job['employee_finished_file']
        try:
            # 🛑 [CRITICAL FIX] ใช้ Firebase Client แทน os.remove
            await firebase_storage_client.delete_file_from_firebase(old_blob_name)
        except Exception as e:
            print(f"ERROR: Failed to remove old finished file {old_blob_name}. Continuing: {e}")
            pass

    # 4. อัปเดตสถานะงาน
    await db.execute(sqlalchemy.update(jobs).where(jobs.c.id == job_id).values(
        status="COMPLETED", 
        employee_finished_file=new_blob_name, # 🛑 บันทึก Blob Name
        completed_date=datetime.datetime.now(datetime.timezone.utc).isoformat(), 
        last_telegram_activity=current_activity
    ))
    await db.commit()

    try:
        # 5. ดึงข้อมูลที่จำเป็นสำหรับการแจ้งเตือน
        comic_query = sqlalchemy.select(comics.c.title, comics.c.employer_id).where(comics.c.id == job.comic_id)
        comic_info = (await db.execute(comic_query)).mappings().first()
        if not comic_info: raise Exception("Comic not found")
        
        comic_title = comic_info.title
        target_employer_id = comic_info.employer_id # User ID ของผู้จ้าง
        
        # <<< [สำคัญ] ดึง Chat ID ส่วนตัวของผู้จ้างจากตาราง users >>>
        employer_chat_res = await db.execute(
            sqlalchemy.select(users.c.telegram_report_chat_id)
            .where(users.c.id == target_employer_id)
        )
        employer_report_chat_id = employer_chat_res.scalar_one_or_none()
        
        # 6. เตรียม Notification
        title = f"🎉 งานเสร็จแล้ว!"
        body = f"{employee_info.name} ส่งงานเรื่อง *{comic_title}* (Ep {job.episode_number}) "

        # 7. ส่ง Telegram (ใช้ Report Bot ไปยัง Chat ID ส่วนตัวของผู้จ้าง)
        if employer_report_chat_id:
            telegram_message = f"*{title}* {body}"
            
            await telegram_config.send_telegram_notification(
                employer_report_chat_id, # ส่งไปหา Chat ID ส่วนตัวของผู้จ้าง
                telegram_message,
                bot_type='REPORT' # ใช้ Bot B
            )
            
        # 8. ส่ง Real-time Update (Bridge App) และ FCM
        tokens = []
        token_query = sqlalchemy.select(fcm_devices.c.device_token).where(
            fcm_devices.c.user_id == target_employer_id, 
            fcm_devices.c.is_active == True
        )
        tokens = (await db.execute(token_query)).scalars().all()

        if target_employer_id:
            bridge_message = {
                "type": "JOB_COMPLETE",
                "title": title,
                "body": body,
                "job_id": job_id,
            }
            await notification_manager.send_personal_notification(target_employer_id, bridge_message) # << แก้ไข: ต้องใช้ await

            if tokens:
                firebase_config.send_notification(
                    tokens=tokens,
                    title=title,
                    body=body,
                    data={"type": "job_complete", "job_id": str(job_id)}
                )
            
    except Exception as e:
        print(f"Failed to send completion notification: {e}")
    
    return {"message": "Job completed successfully"}


@router.get("/my-jobs/")
async def get_my_jobs(db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    # ... (โค้ดเดิม) ...
    emp_res = await db.execute(sqlalchemy.select(employees.c.id).where(employees.c.user_id == current_user.id))
    employee_profile = emp_res.mappings().first()
    if not employee_profile:
        raise HTTPException(status_code=404, detail="Employee profile not found")
            
    jobs_query = (
        sqlalchemy.select(
            jobs.c.id, jobs.c.comic_id, jobs.c.employee_id, jobs.c.episode_number, jobs.c.task_type, jobs.c.rate, jobs.c.status, jobs.c.assigned_date, jobs.c.completed_date, 
            jobs.c.employer_work_file, jobs.c.employee_finished_file, jobs.c.telegram_link, jobs.c.payroll_id, jobs.c.is_revision,
            
            jobs.c.supplemental_file, 
            jobs.c.supplemental_file_comment,

            comics.c.title.label("comic_title"),
            comics.c.image_file.label("comic_image_file")
        )
        .select_from(
            jobs.join(comics, jobs.c.comic_id == comics.c.id)
        )
        .where(jobs.c.employee_id == employee_profile['id'])
        .order_by(sqlalchemy.desc(jobs.c.assigned_date))
    )
    jobs_res = await db.execute(jobs_query)
    
    return jobs_res.mappings().all()

@router.put("/{job_id}/request-revision", status_code=200)
async def request_revision(job_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_employer_user)):
    job_res = await db.execute(sqlalchemy.select(jobs).where(jobs.c.id == job_id))
    job = job_res.mappings().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    current_activity = 'REVISION_REQUEST' # <<<<< เพิ่ม: กำหนดกิจกรรมปัจจุบัน >>>>>

    # 1. ตรวจสอบความเป็นเจ้าของงาน
    comic_res = await db.execute(sqlalchemy.select(comics.c.employer_id).where(comics.c.id == job.comic_id))
    owner_id = comic_res.scalar_one_or_none()
    if owner_id != current_user.id:
         raise HTTPException(status_code=403, detail="Not authorized to modify this job")
         
    if job.status != "COMPLETED":
        raise HTTPException(status_code=400, detail="Only completed jobs can be sent for revision")

    # 🛑 [FIX] ลบไฟล์งานที่พนักงานส่งมาล่าสุดจาก Firebase Storage อย่างปลอดภัย
    if job.employee_finished_file:
        blob_name_to_delete = job.employee_finished_file
        try:
            await firebase_storage_client.delete_file_from_firebase(blob_name_to_delete)
        except Exception as e:
            # ไม่ต้อง raise error เพราะต้องการให้ Logic ดำเนินการต่อ
            print(f"WARNING: Failed to delete revision file {blob_name_to_delete}: {e}")
            pass
        
    # 📌 อัปเดตสถานะ ASSIGNED และ last_telegram_activity
    await db.execute(sqlalchemy.update(jobs).where(jobs.c.id == job_id).values(
        status="ASSIGNED", 
        employee_finished_file=None,
        completed_date=None,
        is_revision=True,
        last_telegram_activity=current_activity # <<<<< เพิ่ม/แก้ไข >>>>>
    ))
    await db.commit()
    
    # 3. ส่ง Notification ไปหาพนักงาน
    try:
        comic_res = await db.execute(sqlalchemy.select(comics.c.title).where(comics.c.id == job.comic_id))
        comic_title = comic_res.scalar_one()

        emp_user_res = await db.execute(sqlalchemy.select(employees.c.user_id, employees.c.telegram_chat_id).where(employees.c.id == job.employee_id))
        emp_info = emp_user_res.mappings().first()
        emp_user_id = emp_info.user_id if emp_info else None
        telegram_chat_id = emp_info.telegram_chat_id if emp_info else None # ดึง Chat ID มาใช้

        tokens = []
        if emp_user_id:
            token_query = sqlalchemy.select(fcm_devices.c.device_token).where(fcm_devices.c.user_id == emp_user_id, fcm_devices.c.is_active == True)
            tokens = (await db.execute(token_query)).scalars().all()
        
        title = f"⚠️ มีงานต้องแก้ไข!"
        body = f"แก้งานตอนที่ {job.episode_number} ของเรื่อง *{comic_title}* นะครับ"

        if emp_user_id:
            # --- [แก้ไข] ส่วน Telegram Notification ---
            if telegram_chat_id:
                # 📌 Logic เปรียบเทียบกิจกรรม
                if job.get('last_telegram_activity') == current_activity:
                    # กิจกรรมซ้ำ -> ตัดหัวข้อออก
                    telegram_message = (
                        f"⚠️ {body}"
                    )
                else:
                    # กิจกรรมใหม่ -> แสดงหัวข้อเต็ม
                    telegram_message = (
                        f"*{title}* "
                        f"{body}"
                    )
                
                await telegram_config.send_telegram_notification(
                    telegram_chat_id, 
                    telegram_message,
                    bot_type='NOTIFY' # <<< Bot A
                )
                
            # 3.1. ส่ง Real-time Update (Bridge App)
            bridge_message = {
                "type": "REVISION_REQUEST",
                "title": title,
                "body": body,
                "job_id": job_id,
            }
            await notification_manager.send_personal_notification(emp_user_id, bridge_message)

            # 3.2. ส่ง FCM (Push Notification สำรอง)
            if tokens:
                firebase_config.send_notification(
                    tokens=tokens,
                    title=title,
                    body=body,
                    data={"type": "revision_request", "job_id": str(job_id)}
                )
    except Exception as e:
        print(f"Failed to send revision notification: {e}")

    return {"message": "Job has been sent back for revision."}

@router.post("/{job_id}/approve-archive", status_code=200)
async def approve_and_archive_job(job_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_employer_user)):
    job_res = await db.execute(sqlalchemy.select(jobs).where(jobs.c.id == job_id))
    job = job_res.mappings().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    comic_res = await db.execute(sqlalchemy.select(comics).where(comics.c.id == job.comic_id))
    comic = comic_res.mappings().first()
    if not comic:
        raise HTTPException(status_code=404, detail="Related Comic not found")
    
    owner_id_check_res = await db.execute(sqlalchemy.select(comics.c.employer_id).where(comics.c.id == job.comic_id))
    owner_id = owner_id_check_res.scalar_one_or_none()
    if owner_id != current_user.id:
         raise HTTPException(status_code=403, detail="Not authorized to modify this job")
     
    # 1. รวบรวมชื่อ Blob ทั้งหมดที่ต้องลบ
    files_to_delete = [
        job.employer_work_file, 
        job.employee_finished_file, 
        job.supplemental_file
    ]
    
    if job.episode_number > comic.last_updated_ep:
        # อัปเดต last_updated_ep
        await db.execute(
            sqlalchemy.update(comics)
            .where(comics.c.id == job.comic_id)
            .values(last_updated_ep=job.episode_number)
        )
    # 2. ลบไฟล์งานหลักจาก Firebase Storage
    for blob_name in files_to_delete:
        if blob_name:
            try:
                # 🛑 [FIX] ใช้ Firebase Client
                await firebase_storage_client.delete_file_from_firebase(blob_name)
            except Exception as e:
                print(f"WARNING: Failed to delete job file {blob_name} from Firebase: {e}")
                pass
                
    # 3. ลบ Supplemental Files ทั้งหมดที่เพิ่มมาภายหลัง
    supp_files_query = sqlalchemy.select(job_supplemental_files.c.file_name).where(job_supplemental_files.c.job_id == job_id)
    supp_files_result = await db.execute(supp_files_query)
    supplemental_files_to_delete_later = supp_files_result.scalars().all()
    
    for blob_name in supplemental_files_to_delete_later:
        if not blob_name.startswith('job_files/'):
             blob_name = f'job_files/{blob_name}'
             
        try:
            # 🛑 [FIX] ใช้ Firebase Client
            await firebase_storage_client.delete_file_from_firebase(blob_name)
        except Exception as e:
            print(f"WARNING: Failed to delete supplemental file {blob_name} from Firebase: {e}")
            pass
        
    # 4. ลบ Record จากตาราง job_supplemental_files
    delete_supp_query = sqlalchemy.delete(job_supplemental_files).where(job_supplemental_files.c.job_id == job_id)
    await db.execute(delete_supp_query)
    
    # 5. อัปเดต Job status และล้างชื่อไฟล์ใน Job table
    await db.execute(sqlalchemy.update(jobs).where(jobs.c.id == job_id).values(
        status="ARCHIVED",
        employer_work_file=None,
        employee_finished_file=None,
        supplemental_file=None, 
        supplemental_file_comment=None,
    ))
    await db.commit()
    return {"message": "Job approved and files have been archived."}


@router.get("/{job_id}/supplemental-files/count", response_model=dict)
async def get_job_supplemental_files_count(job_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    # ... (โค้ดเดิม) ...
    job_res = await db.execute(
        sqlalchemy.select(
            jobs.c.comic_id, 
            jobs.c.employee_id,
            jobs.c.supplemental_file,
            jobs.c.supplemental_file_comment # <<< ควรดึงมาด้วยเพื่อความสมบูรณ์
        ).where(jobs.c.id == job_id)
    )
    job = job_res.mappings().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    # 🛑 [FIX 3] แก้ไขเรื่อง 403 (ไฟล์เสริม) 🛑
    # เพิ่มโค้ดตรวจสอบสิทธิ์ตรงนี้ครับ
    is_employer_owner = False
    is_assigned_employee = False
    
    if current_user.role == 'employer':
        comic_res = await db.execute(sqlalchemy.select(comics.c.employer_id).where(comics.c.id == job.comic_id))
        owner_id = comic_res.scalar_one_or_none()
        if owner_id == current_user.id:
            is_employer_owner = True
            
    if current_user.role == 'employee':
        emp_res = await db.execute(sqlalchemy.select(employees.c.id).where(employees.c.user_id == current_user.id))
        employee_profile = emp_res.mappings().first()
        if employee_profile and employee_profile.id == job.employee_id:
            is_assigned_employee = True

    if not is_employer_owner and not is_assigned_employee:
         raise HTTPException(status_code=403, detail="Not authorized to view files for this job")
    # 🛑 สิ้นสุดโค้ดที่เพิ่ม 🛑
    
    
    # 2. นับจำนวนไฟล์เสริมที่เพิ่มภายหลัง (จากตาราง job_supplemental_files)
    count_later_query = sqlalchemy.select(sqlalchemy.func.count()).select_from(job_supplemental_files).where(job_supplemental_files.c.job_id == job_id)
    count_later = await db.scalar(count_later_query)
    
    # 3. ตรวจสอบไฟล์เสริมที่แนบมาตอนสร้างงาน (ตอนนี้สามารถเข้าถึงได้แล้ว)
    has_initial_file = job.supplemental_file is not None and job.supplemental_file != ""

    return {
        "count_later": count_later,
        "has_initial_file": has_initial_file,
        "total_files": count_later + (1 if has_initial_file else 0)
    }
    
    

@router.get("/{job_id}/supplemental-files/", response_model=List[JobSupplementalFile])
async def get_job_supplemental_files(job_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    # 1. ตรวจสอบว่า Job มีอยู่จริง
    job_res = await db.execute(sqlalchemy.select(jobs.c.comic_id, jobs.c.employee_id).where(jobs.c.id == job_id))
    job = job_res.mappings().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # 2. ตรวจสอบสิทธิ์ (ผู้จ้างเจ้าของงาน หรือพนักงานที่ได้รับมอบหมาย)
    is_employer_owner = False
    is_assigned_employee = False
    
    if current_user.role == 'employer':
        comic_res = await db.execute(sqlalchemy.select(comics.c.employer_id).where(comics.c.id == job.comic_id))
        owner_id = comic_res.scalar_one_or_none()
        if owner_id == current_user.id:
            is_employer_owner = True
            
    if current_user.role == 'employee':
        emp_res = await db.execute(sqlalchemy.select(employees.c.id).where(employees.c.user_id == current_user.id))
        employee_profile = emp_res.mappings().first()
        if employee_profile and employee_profile.id == job.employee_id:
            is_assigned_employee = True

    if not is_employer_owner and not is_assigned_employee:
         raise HTTPException(status_code=403, detail="Not authorized to view files for this job")
         
    # 3. ดึงรายการไฟล์
    query = sqlalchemy.select(job_supplemental_files).where(job_supplemental_files.c.job_id == job_id).order_by(sqlalchemy.desc(job_supplemental_files.c.uploaded_at))
    result = await db.execute(query)
    return result.mappings().all()

@router.get("/{job_id}/", response_model=JobWithComicInfo)
async def get_job_by_id(job_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
        
        
    # 1. สร้าง Query ดึง Job พร้อม Comic/Employee Info
    query = sqlalchemy.select(
        jobs.c.id, jobs.c.comic_id, jobs.c.employee_id, jobs.c.episode_number, jobs.c.task_type, jobs.c.rate, jobs.c.status, jobs.c.assigned_date, jobs.c.completed_date, jobs.c.employer_work_file, jobs.c.employee_finished_file, jobs.c.telegram_link, jobs.c.payroll_id, jobs.c.is_revision,
        jobs.c.supplemental_file, jobs.c.supplemental_file_comment, # <<< เพิ่มไฟล์เสริม
        employees.c.name.label("employee_name"),
        comics.c.title.label("comic_title"),
        comics.c.image_file.label("comic_image_file"),
        comics.c.employer_id.label("comic_employer_id") # <<< ดึง employer_id มาตรวจสอบ
    ).select_from(
        jobs.join(employees, jobs.c.employee_id == employees.c.id)\
            .join(comics, jobs.c.comic_id == comics.c.id)
    ).where(jobs.c.id == job_id)
    
    result = (await db.execute(query)).mappings().first()
    
    
    if not result:
        raise HTTPException(status_code=404, detail="Job not found")
    
    
    # 2. ตรวจสอบสิทธิ์หลังดึงข้อมูล (เพื่อแก้ไขปัญหา SQLAlchemy)
    is_employer_owner = result.comic_employer_id == current_user.id
    is_assigned_employee = False
    
    if current_user.role == 'employee':
        emp_res = await db.execute(sqlalchemy.select(employees.c.user_id).where(employees.c.id == result.employee_id))
        assigned_user_id = emp_res.scalar_one_or_none()
        if assigned_user_id == current_user.id:
            is_assigned_employee = True
            
    # 3. หากไม่ใช่เจ้าของและไม่ใช่พนักงานที่ได้รับมอบหมาย ให้ตอบ 403
    if not is_employer_owner and not is_assigned_employee:
        raise HTTPException(status_code=403, detail="Not authorized to access this job.")
        
    # 4. ส่งข้อมูลกลับ
    result_dict = dict(result)
    del result_dict['comic_employer_id']
    
    return JobWithComicInfo.model_validate(result_dict)


@router.post("/{job_id}/add-file", status_code=200)
async def add_supplemental_file_to_job(
    job_id: int,
    comment: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth.get_current_employer_user)
):
    # 1. ตรวจสอบว่า Job มีอยู่จริงและเป็นของ Employer คนนี้
    # 📌 ปรับ Query: ดึง last_telegram_activity มาด้วย (เนื่องจากเป็น SELECT JOIN)
    job_res = await db.execute(
        sqlalchemy.select(
            jobs.c.id, jobs.c.employee_id, jobs.c.comic_id, jobs.c.episode_number, 
            jobs.c.last_telegram_activity, # <<<<< [สำคัญ] เพิ่มคอลัมน์นี้ >>>>>
            comics.c.employer_id, comics.c.title
        )
        .select_from(jobs.join(comics, jobs.c.comic_id == comics.c.id))
        .where(jobs.c.id == job_id)
    )
    job = job_res.mappings().first()
    if not job or job.employer_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found or not accessible")

    current_activity = 'FILE_ADDED' # <<<<< เพิ่ม: กำหนดกิจกรรมปัจจุบัน >>>>>

    # os.makedirs("job_files", exist_ok=True) # <<< ไม่จำเป็นเมื่อใช้ Firebase
    
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')
    new_file_name = f"supp_{timestamp}_job{job_id}_{file.filename}"
    new_blob_name = f"job_files/{new_file_name}"
    
    file_bytes = await file.read()
    await firebase_storage_client.upload_file_to_firebase(
        file_bytes, 
        new_blob_name,
        content_type=file.content_type
    )

    insert_query = sqlalchemy.insert(job_supplemental_files).values(
        job_id=job_id,
        file_name=new_blob_name, # 🛑 บันทึก Blob Name เต็ม
        comment=comment,
        uploaded_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    await db.execute(insert_query)
    
    # 📌 อัปเดตกิจกรรมล่าสุด
    await db.execute(sqlalchemy.update(jobs).where(jobs.c.id == job_id).values(last_telegram_activity=current_activity)) # <<<<< เพิ่ม >>>>>
    await db.commit() 
    
    # 4. (Optional) ส่ง Notification ไปหาพนักงาน
    try:
        emp_user_res = await db.execute(sqlalchemy.select(employees.c.user_id, employees.c.telegram_chat_id).where(employees.c.id == job.employee_id))
        emp_info = emp_user_res.mappings().first()
        emp_user_id = emp_info.user_id if emp_info else None
        telegram_chat_id = emp_info.telegram_chat_id if emp_info else None # ดึง Chat ID มาใช้
        
        tokens = []
        if emp_user_id:
            token_query = sqlalchemy.select(fcm_devices.c.device_token).where(fcm_devices.c.user_id == emp_user_id, fcm_devices.c.is_active == True)
            tokens = (await db.execute(token_query)).scalars().all()

        title = f"📁 คำแปลมาแล้ว!"
        body = f"ในงานตอนที่ {job.episode_number} ของเรื่อง '{job.title}'" # ใช้ job.title ที่ดึงมา
        
        if emp_user_id:
            # --- [แก้ไข] ส่วน Telegram Notification ---
            if telegram_chat_id:
                 # 📌 Logic เปรียบเทียบกิจกรรม
                if job.get('last_telegram_activity') == current_activity:
                    # กิจกรรมซ้ำ -> ตัดหัวข้อออก
                    # telegram_message = (
                    #     f"📁 {body}"
                    # )
                    telegram_message = (
                        f"*{title}* "
                        f"{body}"
                    )
                else:
                    # กิจกรรมใหม่ -> แสดงหัวข้อเต็ม
                    telegram_message = (
                        f"*{title}* "
                        f"{body}"
                    )
                
                await telegram_config.send_telegram_notification(
                    telegram_chat_id, 
                    telegram_message,
                    bot_type='NOTIFY' # <<< Bot A
                )
                
            # 4.1. ส่ง Real-time Update (Bridge App)
            bridge_message = {
                "type": "FILE_ADDED",
                "title": title,
                "body": body,
                "job_id": job_id,
            }
            await notification_manager.send_personal_notification(emp_user_id, bridge_message)

            # 4.2. ส่ง FCM (Push Notification สำรอง)
            if tokens:
                firebase_config.send_notification(
                    tokens=tokens,
                    title=title,
                    body=body,
                    data={"type": "file_added", "job_id": str(job_id)}
                )
    except Exception as e:
        print(f"Failed to send notification about new file: {e}")

    return {"message": "File added successfully", "file_name": new_file_name}

