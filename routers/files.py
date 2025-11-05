from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import FileResponse, StreamingResponse
import os
import pathlib
from typing import Iterator
import firebase_storage_client

router = APIRouter(
    tags=["Files"]
)

# 📌 [FIX] ใช้ Pathlib สำหรับ Local Path (ถ้ามีการใช้ FileResponse)
COVERS_DIR = pathlib.Path("covers")
JOB_FILES_DIR = pathlib.Path("job_files")
CHAT_FILES_DIR = pathlib.Path("chat_files")

# 📌 [FIX] ฟังก์ชัน helper สำหรับสร้าง StreamingResponse
def iter_file(file_bytes: bytes) -> Iterator[bytes]:
    """Iterator เพื่อ stream bytes data"""
    yield file_bytes

@router.get("/covers/{file_name}")
async def get_cover_image(file_name: str = Path(...)):
    # 📌 [FIX] หากภาพปกถูกเก็บใน Local (สำหรับ Development/Cache)
    #    โค้ดนี้จะใช้เมื่อเรียกผ่าน app.mount("/covers", StaticFiles...) ใน main.py
    file_path = COVERS_DIR / file_name
    
    if not file_path.is_file():
        # ถ้าไม่มีใน Local, ลองดึงจาก Firebase (ถ้าต้องการ Fallback)
        # NOTE: การใช้ StaticFiles ใน main.py จะทำให้โค้ดส่วนนี้อาจถูกข้าม
        #       แต่ถ้าคุณเปลี่ยน main.py เป็น Router จะใช้โค้ดนี้
        raise HTTPException(status_code=404, detail=f"Image not found at {file_path}")
    
    return FileResponse(file_path)

# 📌 [CRITICAL FIX] Endpoint สำหรับดึงไฟล์งาน/ไฟล์เสริม
@router.get("/job-files/{blob_name:path}")
async def get_job_file(blob_name: str = Path(...)):
    """ดึงไฟล์งานหลัก/ไฟล์เสริมจาก Firebase Storage"""
    
    # 📌 [FIX] ตรวจสอบว่า Blob Name มี Path Folder 'job_files/' นำหน้าหรือไม่
    if not blob_name.startswith("job_files/"):
        blob_name = f"job_files/{blob_name}"

    print(f"DEBUG_DOWNLOAD: Attempting to download job blob: {blob_name}")

    try:
        # 📌 [FIX] ดาวน์โหลดไฟล์ Binary จาก Firebase
        file_bytes = await firebase_storage_client.download_file_from_firebase(blob_name)
        
        if file_bytes is None:
            raise HTTPException(status_code=404, detail="File not found in storage.")
            
        # 📌 [FIX] ใช้ StreamingResponse ส่งไฟล์ Binary กลับไป
        original_file_name = os.path.basename(blob_name) # ดึงชื่อไฟล์สุดท้าย
        
        return StreamingResponse(
            content=iter_file(file_bytes),
            media_type="application/octet-stream", 
            headers={"Content-Disposition": f"attachment; filename={original_file_name}"}
        )
    except Exception as e:
        print(f"ERROR: Failed to stream file {blob_name} from Firebase: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error during file retrieval.")
    
# 📌 [CRITICAL FIX] Endpoint สำหรับดึงไฟล์แชท
@router.get("/chat-files/{blob_name:path}")
async def get_chat_file(blob_name: str = Path(...)):
    """ดึงไฟล์แชทจาก Firebase Storage"""
    
    if not blob_name.startswith("chat_files/"):
        blob_name = f"chat_files/{blob_name}"

    print(f"DEBUG_DOWNLOAD: Attempting to download chat blob: {blob_name}")

    try:
        file_bytes = await firebase_storage_client.download_file_from_firebase(blob_name)
        
        if file_bytes is None:
            raise HTTPException(status_code=404, detail="File not found in storage.")
        
        original_file_name = os.path.basename(blob_name)
            
        return StreamingResponse(
            content=iter_file(file_bytes),
            media_type="application/octet-stream", 
            headers={"Content-Disposition": f"attachment; filename={original_file_name}"}
        )
    except Exception as e:
        print(f"ERROR: Failed to stream file {blob_name} from Firebase: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error during file retrieval.")
    
    

