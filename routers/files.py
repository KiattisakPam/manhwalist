from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import os
import pathlib

router = APIRouter(
    tags=["Files"]
)

BASE_DIR = pathlib.Path(__file__).parent.parent 
COVERS_DIR = BASE_DIR / "covers" # Path: backend/covers

@router.get("/covers/{file_name}")
async def get_cover_image(file_name: str):
    # <<< [แก้ไข] ใช้ Pathlib ในการสร้าง Path ที่แม่นยำ >>>
    file_path = COVERS_DIR / file_name
    
    if not file_path.is_file():
        # ลองใช้ os.path.join เป็น Fallback (เพื่อความเข้ากันได้)
        fallback_path = os.path.join("covers", file_name)
        if not os.path.exists(fallback_path):
             raise HTTPException(status_code=404, detail="Image not found")
        file_path = fallback_path
    
    # NOTE: FileResponse ใน FastAPI/Starlette มักจะเพิ่ม Header ที่ถูกต้องให้อยู่แล้ว
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

