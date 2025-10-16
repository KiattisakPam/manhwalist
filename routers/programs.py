# backend/routers/programs.py

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import sqlalchemy
from typing import List

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
    return result.mappings().all()

@router.post("/", status_code=201)
async def create_program(program: Program, db: AsyncSession = Depends(get_db)):
    query = sqlalchemy.insert(programs).values(name=program.name, path=program.path)
    result = await db.execute(query)
    await db.commit()
    # <<< จุดที่ต้องตรวจสอบ: result.inserted_primary_key[0] อาจเป็น Null >>>
    return {"id": result.inserted_primary_key[0], **program.model_dump()}

@router.delete("/{program_id}")
async def delete_program(program_id: int, db: AsyncSession = Depends(get_db)):
    query = sqlalchemy.delete(programs).where(programs.c.id == program_id)
    await db.execute(query)
    await db.commit()
    return {"message": "Program deleted"}
