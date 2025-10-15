from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import os

router = APIRouter(
    tags=["Files"]
)

@router.get("/covers/{file_name}")
async def get_cover_image(file_name: str):
    file_path = os.path.join("covers", file_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Image not found")
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

