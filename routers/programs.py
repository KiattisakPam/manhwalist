# backend/routers/programs.py

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import sqlalchemy
from typing import List
from sqlalchemy import select, func
from database import get_db
from models import programs
from schemas import User, Program
import auth

router = APIRouter(
    prefix="/programs",
    tags=["Programs"],
    dependencies=[Depends(auth.get_current_user)]
)

@router.get("/", response_model=List[Program])
async def get_programs(db: AsyncSession = Depends(get_db)):
    query = sqlalchemy.select(programs).order_by(programs.c.name)
    result = await db.execute(query)
    
    # ดึงข้อมูลออกมาเก็บไว้ในตัวแปร programs_list
    programs_list = result.mappings().all() 
    
    # <<< เพิ่มบรรทัดนี้เพื่อ Debug List ที่จะส่งกลับไป >>>
    print(f"DEBUG: Programs List (Count: {len(programs_list)}): {programs_list}")
    
    # <<< FIX: คืนค่า programs_list ที่ถูกดึงออกมาแล้ว แทนการเรียก result.mappings().all() ซ้ำ >>>
    return programs_list # เดิมคือ return result.mappings().all() ซึ่งจะคืนค่าว่างเปล่า


@router.post("/", status_code=201)
async def create_program(program: Program, db: AsyncSession = Depends(get_db)):
    query = sqlalchemy.insert(programs).values(name=program.name, path=program.path).returning(programs.c.id) # 1. ใช้ RETURNING
    new_id = (await db.execute(query)).scalar_one() # 2. ใช้ scalar_one() รับ ID
    await db.commit()
    
    print(f"DEBUG: New Program ID created: {new_id}")
    
    return {"id": new_id, **program.model_dump()} # 3. ส่ง ID ที่เป็น int กลับไป

@router.delete("/{program_id}")
async def delete_program(program_id: int, db: AsyncSession = Depends(get_db)):
    query = sqlalchemy.delete(programs).where(programs.c.id == program_id)
    await db.execute(query)
    await db.commit()
    return {"message": "Program deleted"}
