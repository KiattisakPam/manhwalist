from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
import sqlalchemy
import datetime
import os
import shutil
from typing import Optional, List

from models import fcm_devices 
from database import get_db
from models import jobs, comics, employees, users
from schemas import User, JobWithComicInfo
import auth
import firebase_config

router = APIRouter(
    prefix="/jobs",
    tags=["Jobs"],
    dependencies=[Depends(auth.get_current_user)]
)


@router.get("/all/", response_model=List[JobWithComicInfo])
async def get_all_jobs(db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_employer_user)):
    # --- แก้ไข Query ให้กรองข้อมูลเฉพาะของ employer ที่ login อยู่ ---
    query = sqlalchemy.select(
        jobs,
        employees.c.name.label("employee_name"),
        comics.c.title.label("comic_title"),
        comics.c.image_file.label("comic_image_file")
    ).select_from(
        jobs.join(employees, jobs.c.employee_id == employees.c.id)\
            .join(comics, jobs.c.comic_id == comics.c.id)
    ).where(comics.c.employer_id == current_user.id).order_by(sqlalchemy.desc(jobs.c.assigned_date)) # <<< เพิ่ม .where()
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
    work_file: UploadFile = File(...)
):
    
    # --- เพิ่ม Logic ตรวจสอบความเป็นเจ้าของก่อนสร้าง ---
    comic_res = await db.execute(sqlalchemy.select(comics).where(comics.c.id == comic_id))
    comic = comic_res.mappings().first()
    if not comic or comic.employer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Comic not found or not owned by user")

    employee_res = await db.execute(sqlalchemy.select(employees).where(employees.c.id == employee_id))
    employee = employee_res.mappings().first()
    if not employee or employee.employer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Employee not found or not owned by user")
    # ---------------------------------------------
        
    os.makedirs("job_files", exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    file_name = f"emp_{timestamp}_ep{episode_number}_{work_file.filename}"
    file_path = os.path.join("job_files", file_name)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(work_file.file, buffer)

    job_data = {
        "comic_id": comic_id, "employee_id": employee_id, "episode_number": episode_number,
        "task_type": task_type, "rate": rate, "assigned_date": datetime.datetime.now().isoformat(),
        "employer_work_file": file_name, "telegram_link": telegram_link,
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

    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    new_file_name = f"fin_{timestamp}_ep{job['episode_number']}_{finished_file.filename}"
    new_file_path = os.path.join("job_files", new_file_name)
    with open(new_file_path, "wb") as buffer:
        shutil.copyfileobj(finished_file.file, buffer)

    if job['employer_work_file']:
        old_file_path = os.path.join("job_files", job['employer_work_file'])
        if os.path.exists(old_file_path):
            os.remove(old_file_path)

    await db.execute(sqlalchemy.update(jobs).where(jobs.c.id == job_id).values(
        status="COMPLETED", employee_finished_file=new_file_name,
        completed_date=datetime.datetime.now().isoformat()
    ))
    await db.commit()

    try:
        comic_res = await db.execute(sqlalchemy.select(comics.c.title).where(comics.c.id == job.comic_id))
        comic_title = comic_res.scalar_one()

        emp_res = await db.execute(sqlalchemy.select(employees.c.name).where(employees.c.id == job.employee_id))
        employee_name = emp_res.scalar_one()

        employer_query = sqlalchemy.select(users).where(users.c.role == 'employer')
        employers = (await db.execute(employer_query)).mappings().all()
        
        for employer in employers:
            token_query = sqlalchemy.select(fcm_devices.c.device_token).where(fcm_devices.c.user_id == employer.id, fcm_devices.c.is_active == True)
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

    # --- แก้ไข Query ตรงนี้ให้ชัดเจนขึ้น ---
    # ระบุทุกคอลัมน์ที่ต้องการเลือกออกมาจากตาราง jobs โดยตรง
    # แทนการใช้ `jobs` ทั้งตาราง
    jobs_query = (
        sqlalchemy.select(
            jobs.c.id,
            jobs.c.comic_id,
            jobs.c.employee_id,
            jobs.c.episode_number,
            jobs.c.task_type,
            jobs.c.rate,
            jobs.c.status,
            jobs.c.assigned_date,
            jobs.c.completed_date,
            jobs.c.employer_work_file,
            jobs.c.employee_finished_file,
            jobs.c.telegram_link,
            jobs.c.payroll_id,
            jobs.c.is_revision,
            comics.c.title.label("comic_title"),
            comics.c.image_file.label("comic_image_file")
        )
        .join(comics, jobs.c.comic_id == comics.c.id)
        .where(jobs.c.employee_id == employee_profile['id'])
        .order_by(jobs.c.assigned_date.desc())
    )
    jobs_res = await db.execute(jobs_query)
    # ------------------------------------
    return jobs_res.mappings().all()


@router.put("/{job_id}/request-revision", status_code=200)
async def request_revision(job_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_employer_user)):
    job_res = await db.execute(sqlalchemy.select(jobs).where(jobs.c.id == job_id))
    job = job_res.mappings().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "COMPLETED":
        raise HTTPException(status_code=400, detail="Only completed jobs can be sent for revision")

    if job.employee_finished_file and os.path.exists(os.path.join("job_files", job.employee_finished_file)):
        os.remove(os.path.join("job_files", job.employee_finished_file))
        
    # --- แก้ไข Query ให้ตั้งค่า is_revision เป็น True ---
    await db.execute(sqlalchemy.update(jobs).where(jobs.c.id == job_id).values(
        status="ASSIGNED", 
        employee_finished_file=None,
        completed_date=None,
        is_revision=True # <<< เพิ่มบรรทัดนี้
    ))
    await db.commit()
    return {"message": "Job has been sent back for revision."}



@router.post("/{job_id}/approve-archive", status_code=200)
async def approve_and_archive_job(job_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_employer_user)):
    """
    นายจ้างอนุมัติงาน เปลี่ยน status เป็น ARCHIVED และลบไฟล์ทั้งหมดเพื่อประหยัดพื้นที่
    """
    job_res = await db.execute(sqlalchemy.select(jobs).where(jobs.c.id == job_id))
    job = job_res.mappings().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # ลบไฟล์งานของนายจ้าง
    if job.employer_work_file and os.path.exists(os.path.join("job_files", job.employer_work_file)):
        os.remove(os.path.join("job_files", job.employer_work_file))
    # ลบไฟล์งานของพนักงาน
    if job.employee_finished_file and os.path.exists(os.path.join("job_files", job.employee_finished_file)):
        os.remove(os.path.join("job_files", job.employee_finished_file))

    await db.execute(sqlalchemy.update(jobs).where(jobs.c.id == job_id).values(
        status="ARCHIVED",
        employer_work_file=None,
        employee_finished_file=None
    ))
    await db.commit()
    return {"message": "Job approved and files have been archived."}


