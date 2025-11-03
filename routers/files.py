from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import os
import pathlib

router = APIRouter(
    tags=["Files"]
)

BASE_DIR = pathlib.Path(__file__).parent.parent.parent # ถ้า main.py อยู่ใน src/
COVERS_DIR = BASE_DIR / "covers" # Path: /covers (ถ้า covers อยู่ใน root เดียวกับ main.py)

@router.get("/covers/{file_name}")
async def get_cover_image(file_name: str):
    # <<< [แก้ไข] ใช้ Pathlib ในการสร้าง Path ที่แม่นยำ >>>
    file_path = COVERS_DIR / file_name
    
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Image not found at {file_path}")
    
    # [สำคัญ] FileResponse ควรทำงานได้ แต่ถ้าไม่ทำงาน ให้ตรวจสอบ FileExtension
    return FileResponse(file_path)


@router.get("/job-files/{file_name}")
async def get_job_file(file_name: str):
    file_path = os.path.join("job_files", file_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)

# --- เพิ่ม Endpoint นี้เข้าไป ---
@router.get("/chat_files/{file_name}")
async def get_chat_file(file_name: str):
    file_path = os.path.join("chat_files", file_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)

