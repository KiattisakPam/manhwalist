from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
import sqlalchemy
import datetime
import os
import shutil
from typing import Optional, List

from models import fcm_devices 
from database import get_db
from models import jobs, comics, employees, users, fcm_devices, job_supplemental_files
from schemas import User, JobWithComicInfo, JobSupplementalFile
import auth
import firebase_config

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
        jobs.join(employees, jobs.c.employee_id == employees.c.id)\
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
        
    os.makedirs("job_files", exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')

    file_name = f"emp_{timestamp}_ep{episode_number}_{work_file.filename}"
    file_path = os.path.join("job_files", file_name)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(work_file.file, buffer)

    supplemental_file_name = None
    if supplemental_file:
        supplemental_file_name = f"supp_{timestamp}_ep{episode_number}_{supplemental_file.filename}"
        supp_file_path = os.path.join("job_files", supplemental_file_name)
        with open(supp_file_path, "wb") as buffer:
            shutil.copyfileobj(supplemental_file.file, buffer)

    job_data = {
        "comic_id": comic_id, "employee_id": employee_id, "episode_number": episode_number,
        "task_type": task_type, "rate": rate, "assigned_date": datetime.datetime.now().isoformat(),
        "employer_work_file": file_name, "telegram_link": telegram_link,
        "supplemental_file": supplemental_file_name,
        "supplemental_file_comment": supplemental_file_comment,
    }
    res = await db.execute(sqlalchemy.insert(jobs).values(**job_data))
    await db.commit()
    return {"id": res.inserted_primary_key[0], **job_data}

@router.put("/{job_id}/complete")
async def employee_complete_job(job_id: int, db: AsyncSession = Depends(get_db), finished_file: UploadFile = File(...), current_user: User = Depends(auth.get_current_user)):
    job_res = await db.execute(sqlalchemy.select(jobs).where(jobs.c.id == job_id))
    job = job_res.mappings().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # 1. <<< ตรวจสอบสิทธิ์: ต้องเป็นพนักงานที่ได้รับมอบหมายงานนี้เท่านั้น >>>
    emp_res = await db.execute(sqlalchemy.select(employees.c.user_id).where(employees.c.id == job.employee_id))
    employee_user_id = emp_res.scalar_one_or_none()
    if employee_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to complete this job")
    # -------------------------------------------------------------

    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    new_file_name = f"fin_{timestamp}_ep{job['episode_number']}_{finished_file.filename}"
    new_file_path = os.path.join("job_files", new_file_name)
    with open(new_file_path, "wb") as buffer:
        shutil.copyfileobj(finished_file.file, buffer)

    # 2. <<< แก้ไข Logic การลบไฟล์: ลบไฟล์งานที่พนักงานส่งมาครั้งก่อนหน้าเท่านั้น >>>
    if job.get('employee_finished_file') and os.path.exists(os.path.join("job_files", job['employee_finished_file'])):
        os.remove(os.path.join(os.path.join("job_files", job['employee_finished_file'])))
    # --------------------------------------------------------------------------

    await db.execute(sqlalchemy.update(jobs).where(jobs.c.id == job_id).values(
        status="COMPLETED", employee_finished_file=new_file_name,
        completed_date=datetime.datetime.now().isoformat()
    ))
    await db.commit()

    try:
        # 3. <<< ปรับปรุง Notification Scope >>>
        comic_query = sqlalchemy.select(comics.c.title, comics.c.employer_id).where(comics.c.id == job.comic_id)
        comic_info = (await db.execute(comic_query)).mappings().first()
        if not comic_info: raise Exception("Comic not found")
        
        comic_title = comic_info.title
        target_employer_id = comic_info.employer_id

        emp_res = await db.execute(sqlalchemy.select(employees.c.name).where(employees.c.id == job.employee_id))
        employee_name = emp_res.scalar_one()

        token_query = sqlalchemy.select(fcm_devices.c.device_token).where(
            fcm_devices.c.user_id == target_employer_id, 
            fcm_devices.c.is_active == True
        )
        tokens = (await db.execute(token_query)).scalars().all()

        if tokens:
            firebase_config.send_notification(
                tokens=tokens,
                title=f"🎉 งานเสร็จแล้ว!",
                body=f"{employee_name} ได้ส่งงานตอนที่ {job.episode_number} ของเรื่อง '{comic_title}' เรียบร้อยแล้ว"
            )
    except Exception as e:
        print(f"Failed to send notification: {e}")
    
    return {"message": "Job completed successfully"}

@router.get("/my-jobs/")
async def get_my_jobs(db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    emp_res = await db.execute(sqlalchemy.select(employees.c.id).where(employees.c.user_id == current_user.id))
    employee_profile = emp_res.mappings().first()
    if not employee_profile:
        raise HTTPException(status_code=404, detail="Employee profile not found")
        
    # <<< ลบ Subquery และ Outer Join ที่ซับซ้อนออกทั้งหมด >>>
    # (เราจะพึ่งพา Frontend ในการเรียก /jobs/{job_id}/supplemental-files/ แทน)
    
    jobs_query = (
        sqlalchemy.select(
            jobs.c.id, jobs.c.comic_id, jobs.c.employee_id, jobs.c.episode_number, jobs.c.task_type, jobs.c.rate, jobs.c.status, jobs.c.assigned_date, jobs.c.completed_date, 
            jobs.c.employer_work_file, jobs.c.employee_finished_file, jobs.c.telegram_link, jobs.c.payroll_id, jobs.c.is_revision,
            
            # ดึงเฉพาะไฟล์เสริมที่มาพร้อมกับงานตั้งแต่แรก (supplemental_file)
            jobs.c.supplemental_file, 
            jobs.c.supplemental_file_comment,

            # (ลบ latest_supplemental_file และ comment ออก)
            
            comics.c.title.label("comic_title"),
            comics.c.image_file.label("comic_image_file")
        )
        .select_from(
            jobs.join(comics, jobs.c.comic_id == comics.c.id)
        )
        .where(jobs.c.employee_id == employee_profile['id'])
        # <<< เพิ่ม Group By เพื่อให้แน่ใจว่าได้ Job ID ที่ไม่ซ้ำกัน >>>
        .group_by(jobs.c.id) 
        # --------------------------------------------------------
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
    
    # 1. ตรวจสอบความเป็นเจ้าของงาน
    comic_res = await db.execute(sqlalchemy.select(comics.c.employer_id).where(comics.c.id == job.comic_id))
    owner_id = comic_res.scalar_one_or_none()
    if owner_id != current_user.id:
         raise HTTPException(status_code=403, detail="Not authorized to modify this job")
         
    if job.status != "COMPLETED":
        raise HTTPException(status_code=400, detail="Only completed jobs can be sent for revision")

    # 2. <<< ลบไฟล์งานที่พนักงานส่งมาล่าสุดเท่านั้น (employee_finished_file) >>>
    if job.employee_finished_file and os.path.exists(os.path.join("job_files", job.employee_finished_file)):
        os.remove(os.path.join("job_files", job.employee_finished_file))
    # --------------------------------------------------------------------------
        
    await db.execute(sqlalchemy.update(jobs).where(jobs.c.id == job_id).values(
        status="ASSIGNED", 
        employee_finished_file=None,
        completed_date=None,
        is_revision=True
    ))
    await db.commit()
    
    # 3. ส่ง Notification ไปหาพนักงาน
    try:
        comic_res = await db.execute(sqlalchemy.select(comics.c.title).where(comics.c.id == job.comic_id))
        comic_title = comic_res.scalar_one()

        emp_user_res = await db.execute(sqlalchemy.select(employees.c.user_id).where(employees.c.id == job.employee_id))
        emp_user_id = emp_user_res.scalar_one_or_none()

        if emp_user_id:
            token_query = sqlalchemy.select(fcm_devices.c.device_token).where(fcm_devices.c.user_id == emp_user_id, fcm_devices.c.is_active == True)
            tokens = (await db.execute(token_query)).scalars().all()

            if tokens:
                firebase_config.send_notification(
                    tokens=tokens,
                    title=f"⚠️ มีงานต้องแก้ไข!",
                    body=f"งานตอนที่ {job.episode_number} ของเรื่อง '{comic_title}' ถูกส่งกลับให้แก้ไข"
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

    # 1. ตรวจสอบความเป็นเจ้าของงาน
    comic_res = await db.execute(sqlalchemy.select(comics.c.employer_id).where(comics.c.id == job.comic_id))
    owner_id = comic_res.scalar_one_or_none()
    if owner_id != current_user.id:
         raise HTTPException(status_code=403, detail="Not authorized to modify this job")

    # 2. ลบไฟล์งานหลักและไฟล์ที่พนักงานส่ง (โค้ดเดิม)
    if job.employer_work_file and os.path.exists(os.path.join("job_files", job.employer_work_file)):
        os.remove(os.path.join("job_files", job.employer_work_file))
    if job.employee_finished_file and os.path.exists(os.path.join("job_files", job.employee_finished_file)):
        os.remove(os.path.join("job_files", job.employee_finished_file))

    # 3. <<< ลบ Supplemental Files ทั้งหมดที่เพิ่มมาภายหลัง >>>
    # ค้นหารายการไฟล์เสริมทั้งหมด
    supp_files_query = sqlalchemy.select(job_supplemental_files.c.file_name).where(job_supplemental_files.c.job_id == job_id)
    supp_files_result = await db.execute(supp_files_query)
    supplemental_files_to_delete = supp_files_result.scalars().all()
    
    # ลบไฟล์ออกจาก Disk
    for file_name in supplemental_files_to_delete:
        file_path = os.path.join("job_files", file_name)
        if os.path.exists(file_path):
            os.remove(file_path)

    # ลบไฟล์เสริมที่แนบมาตอนสร้างงานด้วย (ซึ่งอยู่ในคอลัมน์ job.supplemental_file)
    if job.supplemental_file and os.path.exists(os.path.join("job_files", job.supplemental_file)):
        os.remove(os.path.join("job_files", job.supplemental_file))

    # 4. ลบ Record จากตาราง job_supplemental_files
    delete_supp_query = sqlalchemy.delete(job_supplemental_files).where(job_supplemental_files.c.job_id == job_id)
    await db.execute(delete_supp_query)
    # -------------------------------------------------------------
    
    # 5. อัปเดต Job status และล้างชื่อไฟล์ใน Job table
    await db.execute(sqlalchemy.update(jobs).where(jobs.c.id == job_id).values(
        status="ARCHIVED",
        employer_work_file=None,
        employee_finished_file=None,
        # <<< ล้างชื่อไฟล์เสริมที่แนบมาตอนสร้างงานด้วย >>>
        supplemental_file=None, 
        supplemental_file_comment=None,
    ))
    await db.commit()
    return {"message": "Job approved and files have been archived."}

@router.get("/{job_id}/supplemental-files/count", response_model=dict)
async def get_job_supplemental_files_count(job_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    # 1. <<< แก้ไข Query ให้ดึงคอลัมน์ supplemental_file และ comment เข้ามาด้วย >>>
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
async def get_job_by_id(job_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_employer_user)):
    query = sqlalchemy.select(
        jobs.c.id, jobs.c.comic_id, jobs.c.employee_id, jobs.c.episode_number, jobs.c.task_type, jobs.c.rate, jobs.c.status, jobs.c.assigned_date, jobs.c.completed_date, jobs.c.employer_work_file, jobs.c.employee_finished_file, jobs.c.telegram_link, jobs.c.payroll_id, jobs.c.is_revision,
        employees.c.name.label("employee_name"),
        comics.c.title.label("comic_title"),
        comics.c.image_file.label("comic_image_file")
    ).select_from(
        jobs.join(employees, jobs.c.employee_id == employees.c.id)\
            .join(comics, jobs.c.comic_id == comics.c.id)
    ).where(jobs.c.id == job_id, comics.c.employer_id == current_user.id) # <<< กรองตาม job_id และ employer_id
    
    result = (await db.execute(query)).mappings().first()
    
    if not result:
        raise HTTPException(status_code=404, detail="Job not found or not accessible")
        
    return result

@router.post("/{job_id}/add-file", status_code=200)
async def add_supplemental_file_to_job(
    job_id: int,
    comment: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth.get_current_employer_user)
):
    # 1. ตรวจสอบว่า Job มีอยู่จริงและเป็นของ Employer คนนี้
    job_res = await db.execute(
        sqlalchemy.select(jobs.c.id, jobs.c.employee_id, comics.c.employer_id, comics.c.title, jobs.c.episode_number)
        .select_from(jobs.join(comics, jobs.c.comic_id == comics.c.id))
        .where(jobs.c.id == job_id)
    )
    job = job_res.mappings().first()
    if not job or job.employer_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found or not accessible")

    os.makedirs("job_files", exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    new_file_name = f"supp_{timestamp}_job{job_id}_{file.filename}"
    file_path = os.path.join("job_files", new_file_name)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    insert_query = sqlalchemy.insert(job_supplemental_files).values(
        job_id=job_id,
        file_name=new_file_name,
        comment=comment,
        uploaded_at=datetime.datetime.now().isoformat()
    )
    await db.execute(insert_query)
    await db.commit() # <<< ต้องแน่ใจว่ามีการ commit
    
    # 4. (Optional) ส่ง Notification ไปหาพนักงาน
    try:
        emp_user_res = await db.execute(sqlalchemy.select(employees.c.user_id).where(employees.c.id == job.employee_id))
        emp_user_id = emp_user_res.scalar_one_or_none()
        if emp_user_id:
            token_query = sqlalchemy.select(fcm_devices.c.device_token).where(fcm_devices.c.user_id == emp_user_id, fcm_devices.c.is_active == True)
            tokens = (await db.execute(token_query)).scalars().all()
            if tokens:
                firebase_config.send_notification(
                    tokens=tokens,
                    title=f"ไฟล์ใหม่ในงาน: {job.title}",
                    body=f"ผู้จ้างได้เพิ่มไฟล์ใหม่ในงานตอนที่ {job.episode_number}"
                )
    except Exception as e:
        print(f"Failed to send notification about new file: {e}")

    return {"message": "File added successfully", "file_name": new_file_name}

