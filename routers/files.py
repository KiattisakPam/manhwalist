from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
import os
import pathlib
import firebase_storage_client

router = APIRouter(
    tags=["Files"]
)

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
    # file_name ในที่นี้คือชื่อไฟล์ที่ถูกส่งมาใน Endpoint, แต่ blob_name ต้องรวม Folder ด้วย
    blob_name = f"job_files/{file_name}" 
    
    try:
        # 📌 [FIX] ดาวน์โหลดไฟล์ Binary จาก Firebase
        file_bytes = await firebase_storage_client.download_file_from_firebase(blob_name)
        
        if file_bytes is None:
            raise HTTPException(status_code=404, detail="File not found in storage.")
            
        # 📌 [FIX] ใช้ StreamingResponse ส่งไฟล์ Binary กลับไป
        return StreamingResponse(
            content=iter([file_bytes]),
            media_type="application/octet-stream", # หรือตามประเภทไฟล์
            headers={"Content-Disposition": f"attachment; filename={file_name}"}
        )
    except Exception as e:
        print(f"ERROR: Failed to stream file {blob_name} from Firebase: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error during file retrieval.")
    
    
@router.get("/chat-files/{file_name}")
async def get_chat_file(file_name: str):
    blob_name = f"chat_files/{file_name}" 
    
    try:
        file_bytes = await firebase_storage_client.download_file_from_firebase(blob_name)
        
        if file_bytes is None:
            raise HTTPException(status_code=404, detail="File not found in storage.")
            
        return StreamingResponse(
            content=iter([file_bytes]),
            media_type="application/octet-stream", 
            headers={"Content-Disposition": f"attachment; filename={file_name}"}
        )
    except Exception as e:
        print(f"ERROR: Failed to stream file {blob_name} from Firebase: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error during file retrieval.")
    
    

