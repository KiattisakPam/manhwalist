from fastapi import APIRouter, HTTPException, Path, Depends
from fastapi.responses import FileResponse, StreamingResponse
from google.cloud.exceptions import NotFound, Forbidden
import os
import pathlib
from typing import Iterator
import firebase_storage_client
import urllib.parse
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from schemas import User

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
    final_blob_name = blob_name 

    if not final_blob_name.startswith("job_files/"):
        final_blob_name = f"job_files/{blob_name}" # ใช้ blob_name เดิม (ที่ยังไม่ได้ encode)
    else:
        final_blob_name = blob_name

    print(f"DEBUG_DOWNLOAD_START: Attempting to fetch RAW blob path: {final_blob_name} by user {current_user.email}")
    
    try:
        file_bytes = await firebase_storage_client.download_file_from_firebase(final_blob_name)
        
        if file_bytes is None:
            print(f"DEBUG_DOWNLOAD_FAIL: Blob {final_blob_name} NOT FOUND in storage.")
            raise HTTPException(status_code=404, detail="File not found in storage.")
            
        original_file_name = os.path.basename(final_blob_name) 
        
        # 🛑 [CRITICAL FIX] ต้องใส่ Quotes รอบ filename ใน Content-Disposition
        return StreamingResponse(
            content=iter_file(file_bytes),
            media_type="application/octet-stream", 
            headers={"Content-Disposition": f"attachment; filename=\"{original_file_name}\""}
        )
        
    except NotFound: 
        print(f"DEBUG_DOWNLOAD_FAIL: Blob {final_blob_name} NOT FOUND in storage.")
        raise HTTPException(status_code=404, detail="File not found in storage. (Check Blob Name/Existence)")
    
    except Forbidden: 
        print(f"DEBUG_DOWNLOAD_FAIL: Permission Denied for {final_blob_name}. (Check Firebase Service Account)")
        raise HTTPException(status_code=403, detail="Permission denied to access file.")
        
    except Exception as e:
        print(f"ERROR: Failed to stream file {final_blob_name} from Firebase: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error during file retrieval.")
    
    
# 📌 [CRITICAL FIX] Endpoint สำหรับดึงไฟล์แชท
@router.get("/chat-files/{blob_name:path}")
async def get_chat_file(blob_name: str = Path(...),current_user: User = Depends(auth.get_current_user)):
    """ดึงไฟล์แชทจาก Firebase Storage"""
    
    if not blob_name.startswith("chat_files/"):
        final_blob_name = f"chat_files/{blob_name}" # 📌 [FIX] ใช้ final_blob_name
    else:
        final_blob_name = blob_name # 📌 [FIX] ใช้ final_blob_name

    print(f"DEBUG_DOWNLOAD: Attempting to download chat blob: {final_blob_name}")

    try:
        file_bytes = await firebase_storage_client.download_file_from_firebase(final_blob_name)
        
        if file_bytes is None:
            raise HTTPException(status_code=404, detail="File not found in storage.")
        
        original_file_name = os.path.basename(final_blob_name) # 📌 [FIX] ใช้ final_blob_name
            
        # 🛑 [CRITICAL FIX] ต้องใส่ Quotes รอบ filename ใน Content-Disposition
        return StreamingResponse(
            content=iter_file(file_bytes),
            media_type="application/octet-stream", 
            headers={"Content-Disposition": f"attachment; filename=\"{original_file_name}\""}
        )
    except Exception as e:
        print(f"ERROR: Failed to stream file {final_blob_name} from Firebase: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error during file retrieval.")
    
    