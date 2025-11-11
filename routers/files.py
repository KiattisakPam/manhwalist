from fastapi import APIRouter, HTTPException, Path, Depends
from fastapi.responses import FileResponse, StreamingResponse
from google.cloud.exceptions import NotFound, Forbidden
import os  # <--- [FIX] ตรวจสอบว่ามี import os
import pathlib
from typing import Iterator
import firebase_storage_client
import urllib.parse
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from schemas import User
import auth # <--- [FIX] ตรวจสอบว่ามี import auth

router = APIRouter(
    tags=["Files"]
)

COVERS_DIR = pathlib.Path("covers")
JOB_FILES_DIR = pathlib.Path("job_files")
CHAT_FILES_DIR = pathlib.Path("chat_files")

def iter_file(file_bytes: bytes) -> Iterator[bytes]:
    """Iterator เพื่อ stream bytes data"""
    yield file_bytes

@router.get("/covers/{file_name}")
async def get_cover_image(file_name: str = Path(...)):
    # NOTE: โค้ดนี้จะถูกใช้เมื่อเข้าถึง /covers/file.jpg โดยตรง
    file_path = COVERS_DIR / file_name
    
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Image not found at {file_path}")
    
    return FileResponse(file_path)

@router.get("/job-files/{blob_name:path}")
async def get_job_file(
    blob_name: str = Path(...),
    current_user: User = Depends(auth.get_current_user) 
):
    
    # 1. 🛑 [FIX] Decode Path ที่ถูกส่งมา
    final_blob_name = urllib.parse.unquote(blob_name) 
    
    # 2. 🛑 [CRITICAL FIX] จัดการ Path ซ้ำซ้อน (job_files/job_files/...)
    #    ถ้าเริ่มต้นด้วย 'job_files/job_files/' ให้ตัด 'job_files/' ตัวแรกออก
    if final_blob_name.startswith("job_files/job_files/"):
        final_blob_name = final_blob_name.replace("job_files/", "", 1)
        
        
    print(f"DEBUG_DOWNLOAD_START: FINAL BLOB PATH (CLEANED): {final_blob_name}")
    
    try:
        file_bytes = await firebase_storage_client.download_file_from_firebase(final_blob_name)
        
        if file_bytes is None:
            print(f"DEBUG_DOWNLOAD_FAIL: Blob {final_blob_name} NOT FOUND in storage.")
            raise HTTPException(status_code=404, detail="File not found in storage.")
            
        original_file_name = os.path.basename(final_blob_name) 
        
        # 2. คืนค่า Streaming Response
        return StreamingResponse(
            content=iter_file(file_bytes),
            media_type="application/octet-stream", 
            headers={"Content-Disposition": f"attachment; filename=\"{original_file_name}\""}
        )
        
    except NotFound: 
        print(f"DEBUG_DOWNLOAD_FAIL: Blob {final_blob_name} NOT FOUND in storage.")
        raise HTTPException(status_code=404, detail="File not found in storage. (Check Blob Name/Existence)")
    
    except Forbidden: 
        print(f"DEBUG_DOWNLOAD_FAIL: Permission Denied for {final_blob_name}.")
        raise HTTPException(status_code=403, detail="Permission denied to access file.")
        
    except Exception as e:
        print(f"ERROR: Failed to stream file {final_blob_name} from Firebase: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error during file retrieval.")
    
    
# 📌 [CRITICAL FIX] Endpoint สำหรับดึงไฟล์แชท
@router.get("/chat-files/{blob_name:path}")
async def get_chat_file(
    blob_name: str = Path(...),
    current_user: User = Depends(auth.get_current_user) 
):
    
    final_blob_name = urllib.parse.unquote(blob_name) 
    
    # ลบ Prefix ที่ซ้ำซ้อน
    if final_blob_name.startswith("chat-files/chat-files/"):
        final_blob_name = final_blob_name.replace("chat-files/", "", 1)

    print(f"DEBUG_DOWNLOAD: FINAL BLOB PATH (UNQUOTED/CLEANED): {final_blob_name}")
    
    try:
        file_bytes = await firebase_storage_client.download_file_from_firebase(final_blob_name)
        
        if file_bytes is None:
            raise HTTPException(status_code=404, detail="File not found in storage.")
        
        original_file_name = os.path.basename(final_blob_name)
            
        # 🛑 [CRITICAL FIX] ต้องใส่ Quotes รอบ filename ใน Content-Disposition
        return StreamingResponse(
            content=iter_file(file_bytes),
            media_type="application/octet-stream", 
            headers={"Content-Disposition": f"attachment; filename=\"{original_file_name}\""}
        )
    except Exception as e:
        print(f"ERROR: Failed to stream file {final_blob_name} from Firebase: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error during file retrieval.")
    
    