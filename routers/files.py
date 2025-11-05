from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
import os
import pathlib
from typing import Iterator
import firebase_storage_client

router = APIRouter(
    tags=["Files"]
)

# 📌 [FIX] ฟังก์ชัน helper สำหรับสร้าง StreamingResponse
def iter_file(file_bytes: bytes) -> Iterator[bytes]:
    """Iterator เพื่อ stream bytes data"""
    yield file_bytes

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
    """
    ดึงไฟล์งานหลัก/ไฟล์เสริมจาก Firebase Storage
    file_name ที่ส่งมาต้องเป็น Blob Name ที่ถูกต้อง (เช่น job_files/work_timestamp_name.zip)
    """
    
    # 🛑 [CRITICAL FIX] แก้ปัญหา Path ซ้ำซ้อนที่เกิดจาก Frontend/DB
    # เราเชื่อว่า Blob Name ที่ถูกเก็บใน DB มี 'job_files/' นำหน้าอยู่แล้ว
    blob_name = file_name 
    
    # 📌 [FIX] ถ้าเกิด Path ซ้ำซ้อน (job_files/job_files/...) ให้ตรวจสอบว่า Frontend ส่งมาอย่างไร
    # หาก Frontend ส่งแค่ 'work_timestamp_name.zip' มา (ไม่มี job_files/ นำหน้า) ให้ใส่ Path ให้ถูก
    if not file_name.startswith("job_files/") and not file_name.startswith("chat_files/"):
        blob_name = f"job_files/{file_name}"

    print(f"DEBUG_DOWNLOAD: Attempting to download blob: {blob_name}")

    try:
        # 📌 [FIX] ดาวน์โหลดไฟล์ Binary จาก Firebase
        file_bytes = await firebase_storage_client.download_file_from_firebase(blob_name)
        
        if file_bytes is None:
            raise HTTPException(status_code=404, detail="File not found in storage.")
            
        # 📌 [FIX] ใช้ StreamingResponse ส่งไฟล์ Binary กลับไป
        return StreamingResponse(
            content=iter_file(file_bytes),
            media_type="application/octet-stream", 
            headers={"Content-Disposition": f"attachment; filename={file_name}"}
        )
    except Exception as e:
        print(f"ERROR: Failed to stream file {blob_name} from Firebase: {e}")
        # ถ้าเกิด 404/403/500 ให้แจ้ง Error กลับไป
        raise HTTPException(status_code=500, detail="Internal Server Error during file retrieval.")
    
    
@router.get("/chat-files/{file_name}")
async def get_chat_file(file_name: str):
    blob_name = f"chat_files/{file_name}" 
    
    try:
        file_bytes = await firebase_storage_client.download_file_from_firebase(blob_name)
        
        if file_bytes is None:
            raise HTTPException(status_code=404, detail="File not found in storage.")
            
        return StreamingResponse(
            content=iter_file(file_bytes),
            media_type="application/octet-stream", 
            headers={"Content-Disposition": f"attachment; filename={file_name}"}
        )
    except Exception as e:
        print(f"ERROR: Failed to stream file {blob_name} from Firebase: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error during file retrieval.")
    
    

