from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
import sqlalchemy
import datetime
import os
import shutil
from typing import List

from database import get_db
from models import comics, jobs
from schemas import ComicCreate, ComicWithCompletion, ComicUpdate, EpisodeStatus, User
import auth

router = APIRouter(
    prefix="/comics",
    tags=["Comics"],
    dependencies=[Depends(auth.get_current_user)]
)


@router.post("/upload-image/", tags=["Files"])
async def upload_image(file: UploadFile = File(...), current_user: User = Depends(auth.get_current_employer_user)):
    os.makedirs("covers", exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
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
    now = datetime.datetime.now().isoformat()
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
    comic_res = await db.execute(sqlalchemy.select(comics.c.id).where(comics.c.id == comic_id))
    comic = comic_res.mappings().first()
    if not comic:
        raise HTTPException(status_code=404, detail="Comic not found")

    # --- แก้ไข Query ทั้งหมด ---
    # ดึง "งาน" ทั้งหมดที่เกี่ยวกับการ์ตูนเรื่องนี้ ไม่ใช่สถานะตอน
    jobs_query = (
        sqlalchemy.select(
            jobs.c.episode_number,
            jobs.c.status,
            jobs.c.id.label("job_id"),
            employees.c.name.label("employee_name"),
            jobs.c.employee_finished_file,
            jobs.c.task_type
        )
        .join(employees, jobs.c.employee_id == employees.c.id)
        .where(jobs.c.comic_id == comic_id)
        .order_by(jobs.c.episode_number)
    )
    jobs_result = await db.execute(jobs_query)
    
    # ส่งข้อมูล "งาน" ทั้งหมดกลับไปให้ Frontend จัดการ
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
    
    update_data['last_updated_date'] = datetime.datetime.now().isoformat()

    query = sqlalchemy.update(comics).where(comics.c.id == comic_id).values(**update_data)
    await db.execute(query)
    await db.commit()
    return {"message": "Comic updated successfully"}

