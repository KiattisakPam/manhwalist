import os
import json
import datetime
from fastapi import FastAPI, HTTPException, File, UploadFile, Depends
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# --- Import การตั้งค่า ---
from config import settings

# --- Database Connection ---
# ตรวจสอบว่าเป็น PostgreSQL หรือ SQLite แล้วสร้าง Engine ให้เหมาะสม
if settings.DATABASE_URL.startswith("postgresql") or settings.DATABASE_URL.startswith("postgres"):
    # เพิ่ม +asyncpg เข้าไปใน URL สำหรับ SQLAlchemy
    
    # 1. แทนที่ postgres:// ด้วย postgresql://
    db_url = settings.DATABASE_URL.replace("postgres://", "postgresql://") 

    # 2. เพิ่ม +asyncpg เข้าไป
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
    
    # ถ้าจำเป็นต้องใช้ SSL (แนะนำให้ใส่ connect_args)
    engine = create_async_engine(db_url, pool_size=5, max_overflow=0, connect_args={"ssl": "require"})
else: # SQLite
    engine = create_async_engine(settings.DATABASE_URL)

metadata = sqlalchemy.MetaData()

# --- SQLAlchemy Table Definitions ---
comics = sqlalchemy.Table(
    "comics", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("title", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("synopsis", sqlalchemy.String),
    sqlalchemy.Column("read_link", sqlalchemy.String),
    sqlalchemy.Column("image_file", sqlalchemy.String),
    sqlalchemy.Column("local_folder_path", sqlalchemy.String),
    sqlalchemy.Column("last_updated_ep", sqlalchemy.Integer, default=0),
    sqlalchemy.Column("original_latest_ep", sqlalchemy.Integer, default=0),
    sqlalchemy.Column("last_updated_date", sqlalchemy.String),
    sqlalchemy.Column("status", sqlalchemy.String, default='ACTIVE'),
    sqlalchemy.Column("status_change_date", sqlalchemy.String),
    sqlalchemy.Column("update_type", sqlalchemy.String),
    sqlalchemy.Column("update_value", sqlalchemy.String),
    sqlalchemy.Column("pause_start_date", sqlalchemy.String),
    sqlalchemy.Column("pause_end_date", sqlalchemy.String),
)

employees = sqlalchemy.Table(
    "employees", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String, nullable=False, unique=True),
)

jobs = sqlalchemy.Table(
    "jobs", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("comic_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("comics.id", ondelete="CASCADE")),
    sqlalchemy.Column("employee_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("employees.id", ondelete="CASCADE")),
    sqlalchemy.Column("task_type", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("start_episode", sqlalchemy.Integer, nullable=False),
    sqlalchemy.Column("end_episode", sqlalchemy.Integer, nullable=False),
    sqlalchemy.Column("rate_per_episode", sqlalchemy.Float, nullable=False),
    sqlalchemy.Column("total_cost", sqlalchemy.Float, nullable=False),
    sqlalchemy.Column("status", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("assigned_date", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("completed_date", sqlalchemy.String),
    sqlalchemy.Column("payroll_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("payrolls.id", ondelete="SET NULL")),
)

payrolls = sqlalchemy.Table(
    "payrolls", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("employee_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("employees.id", ondelete="CASCADE")),
    sqlalchemy.Column("payment_date", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("amount_paid", sqlalchemy.Float, nullable=False),
    sqlalchemy.Column("job_ids", sqlalchemy.String, nullable=False),
)

programs = sqlalchemy.Table(
    "programs", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("path", sqlalchemy.String, nullable=False),
)

app = FastAPI()

# --- Event Handlers ---
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

# --- Dependency ---
async def get_db() -> AsyncSession:
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session

# --- CORS ---
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- Pydantic Models ---
class Comic(BaseModel):
    title: str
    synopsis: Optional[str] = None
    read_link: Optional[str] = None
    image_file: Optional[str] = None
    local_folder_path: Optional[str] = None
    last_updated_ep: int = 0
    original_latest_ep: int = 0
    last_updated_date: str
    status: str = 'ACTIVE'
    status_change_date: str
    update_type: Optional[str] = None
    update_value: Optional[str] = None
    pause_start_date: Optional[str] = None
    pause_end_date: Optional[str] = None

class ComicUpdate(BaseModel):
    title: Optional[str] = None
    synopsis: Optional[str] = None
    read_link: Optional[str] = None
    image_file: Optional[str] = None
    local_folder_path: Optional[str] = None
    last_updated_ep: Optional[int] = None
    original_latest_ep: Optional[int] = None
    last_updated_date: Optional[str] = None
    status: Optional[str] = None
    status_change_date: Optional[str] = None
    update_type: Optional[str] = None
    update_value: Optional[str] = None
    pause_start_date: Optional[str] = None
    pause_end_date: Optional[str] = None

class Employee(BaseModel):
    name: str

class JobBase(BaseModel):
    comic_id: int
    employee_id: int
    task_type: str
    start_episode: int
    end_episode: int
    rate_per_episode: float

class Job(JobBase):
    id: int
    total_cost: float
    status: str
    assigned_date: str
    completed_date: Optional[str] = None
    employee_name: str

class JobWithComicInfo(Job):
    comic_title: str
    comic_image_file: Optional[str] = None

class PayrollCreate(BaseModel):
    employee_id: int
    amount_paid: float
    job_ids: List[int]
    
class Program(BaseModel):
    name: str
    path: str

# --- API Endpoints ---

# --- Comic Endpoints ---
@app.get("/comics")
async def get_all_comics(db: AsyncSession = Depends(get_db)):
    query = sqlalchemy.select(comics).order_by(sqlalchemy.desc(comics.c.last_updated_date))
    result = await db.execute(query)
    return result.mappings().all()

@app.get("/comics/{comic_id}")
async def get_comic_by_id(comic_id: int, db: AsyncSession = Depends(get_db)):
    query = sqlalchemy.select(comics).where(comics.c.id == comic_id)
    result = await db.execute(query)
    comic = result.mappings().first()
    if comic is None:
        raise HTTPException(status_code=404, detail="Comic not found")
    return comic

@app.post("/comics", status_code=201)
async def create_comic(comic: Comic, db: AsyncSession = Depends(get_db)):
    query = sqlalchemy.insert(comics).values(**comic.dict())
    result = await db.execute(query)
    await db.commit()
    return {"id": result.inserted_primary_key[0], **comic.dict()}

@app.put("/comics/{comic_id}")
async def update_comic(comic_id: int, comic_update: ComicUpdate, db: AsyncSession = Depends(get_db)):
    update_data = comic_update.dict(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No update data provided")
    query = sqlalchemy.update(comics).where(comics.c.id == comic_id).values(**update_data)
    await db.execute(query)
    await db.commit()
    return {"message": f"Comic with id {comic_id} updated successfully"}

@app.delete("/comics/{comic_id}")
async def delete_comic(comic_id: int, db: AsyncSession = Depends(get_db)):
    query = sqlalchemy.delete(comics).where(comics.c.id == comic_id)
    await db.execute(query)
    await db.commit()
    return {"message": "Comic and all related jobs deleted"}

# --- Image Endpoints ---
@app.post("/upload-image")
async def upload_image(file: UploadFile = File(...)):
    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    base_name = os.path.splitext(file.filename)[0].replace(' ', '_').encode('ascii', 'ignore').decode('ascii')
    extension = os.path.splitext(file.filename)[1]
    new_file_name = f"cover_{timestamp}_{base_name}{extension}"
    file_path = os.path.join("covers", new_file_name)
    os.makedirs("covers", exist_ok=True)
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())
    return {"file_name": new_file_name}

@app.get("/covers/{file_name}")
async def get_cover_image(file_name: str):
    file_path = os.path.join("covers", file_name)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="Image not found")

# --- Employee Endpoints ---
@app.get("/employees")
async def get_all_employees(db: AsyncSession = Depends(get_db)):
    query = sqlalchemy.select(employees).order_by(employees.c.name)
    result = await db.execute(query)
    return result.mappings().all()

@app.post("/employees", status_code=201)
async def create_employee(employee: Employee, db: AsyncSession = Depends(get_db)):
    try:
        query = sqlalchemy.insert(employees).values(name=employee.name)
        result = await db.execute(query)
        await db.commit()
        return {"id": result.inserted_primary_key[0], **employee.dict()}
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Employee with this name already exists")

@app.delete("/employees/{employee_id}")
async def delete_employee(employee_id: int, db: AsyncSession = Depends(get_db)):
    query = sqlalchemy.delete(employees).where(employees.c.id == employee_id)
    await db.execute(query)
    await db.commit()
    return {"message": "Employee deleted"}

# --- Job Endpoints ---
@app.get("/comics/{comic_id}/jobs")
async def get_jobs_for_comic(comic_id: int, db: AsyncSession = Depends(get_db)):
    query = sqlalchemy.select(jobs, employees.c.name.label("employee_name"))\
        .join(employees, jobs.c.employee_id == employees.c.id)\
        .where(jobs.c.comic_id == comic_id)\
        .order_by(sqlalchemy.desc(jobs.c.assigned_date))
    result = await db.execute(query)
    return result.mappings().all()

@app.post("/jobs", status_code=201)
async def create_job(job_data: JobBase, db: AsyncSession = Depends(get_db)):
    total_cost = (job_data.end_episode - job_data.start_episode + 1) * job_data.rate_per_episode
    assigned_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    query = sqlalchemy.insert(jobs).values(
        **job_data.dict(),
        total_cost=total_cost,
        status="ASSIGNED",
        assigned_date=assigned_date
    )
    result = await db.execute(query)
    await db.commit()
    return {"id": result.inserted_primary_key[0], **job_data.dict(), "total_cost": total_cost, "status": "ASSIGNED", "assigned_date": assigned_date}

@app.put("/jobs/{job_id}/complete")
async def complete_job(job_id: int, db: AsyncSession = Depends(get_db)):
    completed_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    query = sqlalchemy.update(jobs).where(jobs.c.id == job_id).values(status='COMPLETED', completed_date=completed_date)
    await db.execute(query)
    await db.commit()
    return {"message": "Job marked as completed"}

@app.get("/jobs/all")
async def get_all_jobs(db: AsyncSession = Depends(get_db)):
    query = sqlalchemy.select(
        jobs, 
        employees.c.name.label("employee_name"), 
        comics.c.title.label("comic_title"),
        comics.c.image_file.label("comic_image_file")
    ).select_from(
        jobs.join(employees, jobs.c.employee_id == employees.c.id)\
            .join(comics, jobs.c.comic_id == comics.c.id)
    ).order_by(sqlalchemy.desc(jobs.c.assigned_date))
    result = await db.execute(query)
    return result.mappings().all()

# --- Payroll Endpoints ---
@app.get("/employees/{employee_id}/unpaid-summary")
async def get_unpaid_summary(employee_id: int, db: AsyncSession = Depends(get_db)):
    query = sqlalchemy.select(
        jobs, 
        comics.c.title.label("comic_title")
    ).select_from(
        jobs.join(comics, jobs.c.comic_id == comics.c.id)
    ).where(sqlalchemy.and_(
        jobs.c.employee_id == employee_id,
        jobs.c.status == 'COMPLETED',
        jobs.c.payroll_id.is_(None)
    ))
    result = await db.execute(query)
    unpaid_jobs = result.mappings().all()
    total_owed = sum(job['total_cost'] for job in unpaid_jobs)
    return {"total_owed": total_owed, "jobs": unpaid_jobs}

@app.post("/payrolls", status_code=201)
async def process_payroll(payroll_data: PayrollCreate, db: AsyncSession = Depends(get_db)):
    try:
        # Find and delete old payrolls
        old_payrolls_query = sqlalchemy.select(payrolls).where(payrolls.c.employee_id == payroll_data.employee_id)
        old_payrolls_result = await db.execute(old_payrolls_query)
        for old_payroll in old_payrolls_result.mappings().all():
            delete_query = sqlalchemy.delete(payrolls).where(payrolls.c.id == old_payroll['id'])
            await db.execute(delete_query)
        
        # Create new payroll
        payment_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        insert_payroll_query = sqlalchemy.insert(payrolls).values(
            employee_id=payroll_data.employee_id,
            payment_date=payment_date,
            amount_paid=payroll_data.amount_paid,
            job_ids=json.dumps(payroll_data.job_ids)
        )
        result = await db.execute(insert_payroll_query)
        payroll_id = result.inserted_primary_key[0]
        
        # Update jobs
        update_jobs_query = sqlalchemy.update(jobs).where(jobs.c.id.in_(payroll_data.job_ids)).values(payroll_id=payroll_id)
        await db.execute(update_jobs_query)
        
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
        
    return {"message": "Payroll processed successfully", "payroll_id": payroll_id}

@app.get("/employees/{employee_id}/latest-payroll")
async def get_latest_payroll(employee_id: int, db: AsyncSession = Depends(get_db)):
    payroll_query = sqlalchemy.select(payrolls).where(payrolls.c.employee_id == employee_id).order_by(sqlalchemy.desc(payrolls.c.payment_date)).limit(1)
    payroll_result = await db.execute(payroll_query)
    payroll_info = payroll_result.mappings().first()

    if not payroll_info:
        return None

    job_ids = json.loads(payroll_info['job_ids'])
    if not job_ids:
        return {"payroll_info": payroll_info, "jobs": []}

    jobs_query = sqlalchemy.select(
        jobs, 
        comics.c.title.label("comic_title")
    ).select_from(
        jobs.join(comics, jobs.c.comic_id == comics.c.id)
    ).where(jobs.c.id.in_(job_ids))
    
    paid_jobs_result = await db.execute(jobs_query)
    return {"payroll_info": payroll_info, "jobs": paid_jobs_result.mappings().all()}

# --- Program Launcher Endpoints ---
@app.get("/programs")
async def get_programs(db: AsyncSession = Depends(get_db)):
    query = sqlalchemy.select(programs).order_by(programs.c.name)
    result = await db.execute(query)
    return result.mappings().all()

@app.post("/programs", status_code=201)
async def create_program(program: Program, db: AsyncSession = Depends(get_db)):
    query = sqlalchemy.insert(programs).values(name=program.name, path=program.path)
    result = await db.execute(query)
    await db.commit()
    return {"id": result.inserted_primary_key[0], **program.dict()}

@app.delete("/programs/{program_id}")
async def delete_program(program_id: int, db: AsyncSession = Depends(get_db)):
    query = sqlalchemy.delete(programs).where(programs.c.id == program_id)
    await db.execute(query)
    await db.commit()
    return {"message": "Program deleted"}

