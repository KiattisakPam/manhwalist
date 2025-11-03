from fastapi import APIRouter, Depends, HTTPException, Form
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
import sqlalchemy
import datetime

from database import get_db
from models import users, employees
from schemas import Token, User, EmployerUpdate
import auth
from config import settings

router = APIRouter(
    tags=["Users and Authentication"]
)

@router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    user = await auth.get_user_from_db(db, email=form_data.username)
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    
    access_token_expires = datetime.timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(data={"sub": user.email}, expires_delta=access_token_expires)
    
    # 📌 [FIX] แปลง result row เป็น dict เพื่อให้ Pydantic validate ได้ถูกต้อง
    user_data = dict(user) 
    # User Schema (Pydantic) จะรวมฟิลด์ telegram_report_chat_id โดยอัตโนมัติ
    user_model = User.model_validate(user_data) 
    
    return {"access_token": access_token, "token_type": "bearer", "user": user_model}

@router.post("/register/employer", status_code=201, response_model=User)
async def register_employer(
    email: str = Form(...),
    password: str = Form(...),
    invitation_code: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    if invitation_code != settings.INVITATION_CODE:
        raise HTTPException(status_code=403, detail="Invalid invitation code")
        
    if await auth.get_user_from_db(db, email=email):
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = auth.get_password_hash(password)
    
    insert_query = sqlalchemy.insert(users).values(
        email=email,
        hashed_password=hashed_password, 
        role="employer"
    )

    result = await db.execute(insert_query)
    await db.commit()

    created_user = {
        "id": result.inserted_primary_key[0],
        "email": email,
        "role": "employer",
        "telegram_report_chat_id": None # <<< ใส่ None เพื่อให้ model validate ผ่าน
    }
    return created_user


@router.post("/users/employee", status_code=201)
async def create_employee_user(
    name: str = Form(...), 
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(auth.get_current_employer_user)
):
    if await auth.get_user_from_db(db, email=email):
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = auth.get_password_hash(password)
    
    user_res = await db.execute(sqlalchemy.insert(users).values(email=email, hashed_password=hashed_password, role="employee"))
    
    await db.execute(sqlalchemy.insert(employees).values(
        name=name, 
        user_id=user_res.inserted_primary_key[0],
        employer_id=current_user.id
    ))
    
    await db.commit()
    return {"message": "Employee created successfully"}

@router.post("/employee/{employee_id}/details", status_code=200)
async def update_employee_details(
    employee_id: int,
    name: str = Form(...),
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth.get_current_employer_user)
):
    # 1. ตรวจสอบ Employee
    emp_res = await db.execute(sqlalchemy.select(employees).where(employees.c.id == employee_id))
    employee = emp_res.mappings().first()
    if not employee or employee.employer_id != current_user.id:
        print(f"DEBUG_UPDATE: Employee ID {employee_id} not found or not owned by employer {current_user.id}")
        raise HTTPException(status_code=404, detail="Employee not found")

    # [LOG] แสดง User ID ที่กำลังจะ Query
    print(f"DEBUG_UPDATE: Querying User ID: {employee.user_id}")
    
    # 2. ตรวจสอบ User
    user_res = await db.execute(sqlalchemy.select(users).where(users.c.id == employee.user_id))
    user = user_res.mappings().first()

    # [LOG] แสดงผลลัพธ์การ Query User
    print(f"DEBUG_UPDATE: Query Result for User ID {employee.user_id}: {user}")
    
    # [CRITICAL FIX] ป้องกัน NoneType Error
    if user is None:
        raise HTTPException(status_code=500, detail="Associated user account not found for this employee. User ID might be corrupted.") # 
    
    # 3. ตรวจสอบ Email ซ้ำ
    if email != user.email:
        # ต้องเช็คว่า email ใหม่ไม่ได้ถูกใช้โดย user คนอื่น (ที่ไม่ใช่ตัวมันเอง)
        existing_user_res = await db.execute(
            sqlalchemy.select(users).where(
                sqlalchemy.and_(
                    users.c.email == email,
                    users.c.id != employee.user_id 
                )
            )
        )
        existing_user = existing_user_res.mappings().first()
        
        if existing_user:
            raise HTTPException(status_code=400, detail="New email is already in use by another user.")
    
    # 4. อัปเดตข้อมูล
    # อัปเดตตาราง employees (อัปเดตชื่อ)
    await db.execute(sqlalchemy.update(employees).where(employees.c.id == employee_id).values(name=name))
    # อัปเดตตาราง users (อัปเดตอีเมล)
    await db.execute(sqlalchemy.update(users).where(users.c.id == employee.user_id).values(email=email))
    
    await db.commit()
    return {"message": "Employee details updated successfully"}


@router.put("/employee/{employee_id}/password", status_code=200)
async def change_employee_password(
    employee_id: int,
    new_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth.get_current_employer_user)
):
    emp_res = await db.execute(sqlalchemy.select(employees).where(employees.c.id == employee_id))
    employee = emp_res.mappings().first()
    if not employee or employee.employer_id != current_user.id:
        raise HTTPException(status_code=404, detail="Employee not found")

    hashed_password = auth.get_password_hash(new_password)
    
    await db.execute(sqlalchemy.update(users).where(users.c.id == employee.user_id).values(hashed_password=hashed_password))
    
    await db.commit()
    return {"message": "Employee password updated successfully"}

@router.put("/me/report-chat-id", status_code=200)
async def update_employer_report_chat_id(
    payload: EmployerUpdate, # รับค่าจาก Schema
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth.get_current_employer_user) # ต้องเป็น Employer เท่านั้น
):
    """อัปเดต Telegram Report Chat ID ของผู้จ้างที่เข้าสู่ระบบ"""
    
    # ล้างค่า Chat ID ถ้าส่งค่าว่างมา
    chat_id_to_save = payload.telegram_report_chat_id.strip() if payload.telegram_report_chat_id else None
    if chat_id_to_save == "":
        chat_id_to_save = None

    await db.execute(
        sqlalchemy.update(users).where(users.c.id == current_user.id).values(
            telegram_report_chat_id=chat_id_to_save
        )
    )
    
    await db.commit()
    return {"message": "Telegram Report Chat ID updated successfully"}

