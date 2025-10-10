# backend/routers/users.py

from fastapi import APIRouter, Depends, HTTPException, Form
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
import sqlalchemy
import datetime

from database import get_db
from models import users, employees
from schemas import Token, User
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
    user_model = User.model_validate(user)
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
    
    # --- ส่วนที่แก้ไข ---
    # 1. ทำการเข้ารหัสรหัสผ่านก่อน
    hashed_password = auth.get_password_hash(password)
    
    # 2. นำรหัสผ่านที่เข้ารหัสแล้ว (hashed_password) ไปบันทึก
    insert_query = sqlalchemy.insert(users).values(
        email=email,
        hashed_password=hashed_password, 
        role="employer"
    )
    # -------------------

    result = await db.execute(insert_query)
    await db.commit()

    created_user = {
        "id": result.inserted_primary_key[0],
        "email": email,
        "role": "employer"
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
    
    # --- แก้ไข Query ให้เพิ่ม employer_id ตอนสร้าง ---
    await db.execute(sqlalchemy.insert(employees).values(
        name=name, 
        user_id=user_res.inserted_primary_key[0],
        employer_id=current_user.id # <<< เพิ่ม employer_id
    ))
    
    await db.commit()
    return {"message": "Employee created successfully"}

