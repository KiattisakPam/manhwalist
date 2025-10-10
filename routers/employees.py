from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
import sqlalchemy
import json
import datetime
from typing import List
from pydantic import BaseModel # <<< เพิ่มบรรทัดนี้

from database import get_db
from models import employees, jobs, comics, payrolls
from schemas import User, JobWithComicInfo
import auth

router = APIRouter(
    prefix="/employees",
    tags=["Employees"],
    dependencies=[Depends(auth.get_current_user)]
)

@router.get("/")
async def get_all_employees(db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_employer_user)):
    # --- แก้ไข Query ให้กรองข้อมูลเฉพาะของ employer ที่ login อยู่ ---
    query = sqlalchemy.select(employees).where(employees.c.employer_id == current_user.id).order_by(employees.c.name)
    result = await db.execute(query)
    return result.mappings().all()


async def _get_summary_logic(employee_id: int, db: AsyncSession):
    query = sqlalchemy.select(
        jobs.c.id,
        jobs.c.comic_id,
        jobs.c.employee_id,
        jobs.c.episode_number,
        jobs.c.task_type,
        jobs.c.rate,
        jobs.c.status,
        jobs.c.assigned_date,
        comics.c.title.label("comic_title")
    ).select_from(
        jobs.join(comics, jobs.c.comic_id == comics.c.id)
    ).where(sqlalchemy.and_(
        jobs.c.employee_id == employee_id,
        # --- แก้ไขเงื่อนไขตรงนี้ ---
        jobs.c.status.in_(['COMPLETED', 'ARCHIVED']), # <<< ให้ดึงงานที่เสร็จแล้วและอนุมัติแล้ว
        # -------------------------
        jobs.c.payroll_id.is_(None)
    ))
    
    result = await db.execute(query)
    unpaid_jobs = result.mappings().all()
    total_owed = sum(job['rate'] for job in unpaid_jobs)
    
    jobs_list = []
    for job in unpaid_jobs:
        job_dict = dict(job)
        if isinstance(job_dict.get('assigned_date'), datetime.date):
             job_dict['assigned_date'] = job_dict['assigned_date'].isoformat()
        jobs_list.append(job_dict)

    return {"total_owed": total_owed, "jobs": jobs_list}

@router.get("/me/unpaid-summary")
async def get_my_unpaid_summary(db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if current_user.role != 'employee':
        raise HTTPException(status_code=403, detail="Only employees can access this endpoint")

    emp_res = await db.execute(sqlalchemy.select(employees.c.id).where(employees.c.user_id == current_user.id))
    employee_profile = emp_res.mappings().first()
    if not employee_profile:
        raise HTTPException(status_code=404, detail="Employee profile not found")
    
    return await _get_summary_logic(employee_profile.id, db)

@router.get("/{employee_id}/unpaid-summary")
async def get_unpaid_summary(employee_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_employer_user)):
    return await _get_summary_logic(employee_id, db)

@router.get("/{employee_id}/latest-payroll")
async def get_latest_payroll(employee_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(auth.get_current_employer_user)):
    payroll_query = sqlalchemy.select(payrolls).where(payrolls.c.employee_id == employee_id).order_by(sqlalchemy.desc(payrolls.c.payment_date)).limit(1)
    payroll_result = await db.execute(payroll_query)
    payroll_info = payroll_result.mappings().first()

    if not payroll_info: return None
    job_ids = json.loads(payroll_info['job_ids'])
    if not job_ids: return {"payroll_info": payroll_info, "jobs": []}

    jobs_query = sqlalchemy.select(
        jobs, comics.c.title.label("comic_title")
    ).select_from(
        jobs.join(comics, jobs.c.comic_id == comics.c.id)
    ).where(jobs.c.id.in_(job_ids))
    
    paid_jobs_result = await db.execute(jobs_query)
    return {"payroll_info": payroll_info, "jobs": [dict(job) for job in paid_jobs_result.mappings().all()]}


# --- Endpoint ใหม่สำหรับยืนยันการจ่ายเงิน ---
class PayrollPayload(BaseModel):
    job_ids: List[int]
    amount_paid: float

@router.post("/{employee_id}/payrolls", status_code=201)
async def create_payroll_for_employee(
    employee_id: int, 
    payload: PayrollPayload,
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(auth.get_current_employer_user)
):
    # สร้าง Payroll record ใหม่
    payroll_query = sqlalchemy.insert(payrolls).values(
        employee_id=employee_id,
        payment_date=datetime.datetime.now().isoformat(),
        amount_paid=payload.amount_paid,
        job_ids=json.dumps(payload.job_ids) # แปลง list เป็น JSON string
    )
    result = await db.execute(payroll_query)
    new_payroll_id = result.inserted_primary_key[0]

    # อัปเดตงานที่จ่ายเงินแล้วทั้งหมดให้มี payroll_id
    update_jobs_query = sqlalchemy.update(jobs).where(
        jobs.c.id.in_(payload.job_ids)
    ).values(payroll_id=new_payroll_id)
    await db.execute(update_jobs_query)
    
    await db.commit()
    return {"message": "Payroll created successfully", "payroll_id": new_payroll_id}

