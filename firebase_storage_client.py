# backend/firebase_storage_client.py

import firebase_admin
from firebase_admin import credentials, storage
# 📌 [FIX] Import Exception Classes ที่ถูกต้อง
from google.cloud.exceptions import NotFound, Forbidden 
import os
import json 
from typing import Optional, Iterator
from fastapi.responses import StreamingResponse
from google.cloud.storage.blob import Blob # 📌 [FIX] Import Blob Class


# 📌 [FIX 1] ตั้งค่า Storage Bucket 
# ใช้ชื่อ Bucket จาก Environment Variable หรือค่าคงที่
FIREBASE_BUCKET_NAME = os.environ.get("FIREBASE_BUCKET_NAME", "comic-secretary.firebasestorage.app")

try:
    json_credential_str = os.environ.get("FIREBASE_CREDENTIALS_JSON")
    
    # ... (ส่วนการโหลด Credentials เหมือนเดิม) ...
    if json_credential_str:
        cred = credentials.Certificate(json.loads(json_credential_str))
    else:
        # NOTE: การใช้ไฟล์ .json ใน Production อาจไม่ปลอดภัย
        cred = credentials.Certificate("firebase-service-account.json") 
        
    # ----------------------------------------------------
    if not firebase_admin._apps: 
        firebase_admin.initialize_app(cred, {
            'storageBucket': FIREBASE_BUCKET_NAME
        })
        print("INFO: Firebase Admin SDK initialized successfully for Storage.")
    else:
        print("INFO: Firebase Admin SDK already initialized by another worker.") 
    
    # 📌 [FIX] อ้างอิง bucket โดยใช้ชื่อที่ Initialize
    bucket = storage.bucket(FIREBASE_BUCKET_NAME)
    
    
except Exception as e:
    print(f"ERROR: Failed to initialize Firebase Admin SDK for Storage: {e}")
    bucket = None


# 📌 [FIX 3] ฟังก์ชันอัปโหลด Binary Data
async def upload_file_to_firebase(file_bytes: bytes, destination_blob_name: str, content_type: Optional[str] = 'application/octet-stream') -> str:
    """อัปโหลดไฟล์ (bytes) ไปยัง Firebase Storage และคืนค่า URL สาธารณะ"""
    if not bucket:
        raise Exception("Firebase Storage not initialized.")
    
    # 📌 [FIX 4] ต้องใช้ Blob Class จาก google.cloud.storage
    blob = bucket.blob(destination_blob_name) 
    
    print(f"FIREBASE_CLIENT_DEBUG: Uploading Blob: {destination_blob_name}")
    
    # อัปโหลดไฟล์
    blob.upload_from_string(
        data=file_bytes,
        content_type=content_type
    )
    
    # 🛑 [CRITICAL FIX A] ลบ make_public() ออกเพื่อความปลอดภัย 
    # (เราใช้ Service Account ดาวน์โหลด ไม่ต้องใช้ Public URL)
    # blob.make_public() 
    
    # คืนค่า URL ที่ใช้ได้จริง (ไม่ว่าจะเป็น public หรือ private)
    return destination_blob_name # 📌 [FIX] คืนค่า Blob Name แทน Public URL

# 📌 [FIX 4] ฟังก์ชันลบไฟล์
async def delete_file_from_firebase(blob_name: str):
    """ลบไฟล์ออกจาก Firebase Storage"""
    if not bucket:
        raise Exception("Firebase Storage not initialized.")
    
    # 📌 [FIX] ใช้ try/except เพื่อดักจับ NotFound
    try:
        blob = bucket.blob(blob_name)
        # NOTE: .exists() ช้ามาก ใช้ .delete() แล้วดัก Error แทน
        blob.delete()
        print(f"INFO: Successfully deleted blob: {blob_name}")
        return True
    except NotFound:
        print(f"WARNING: Blob not found for deletion: {blob_name}")
        return False
    except Exception as e:
        print(f"ERROR: Failed to delete blob {blob_name}: {e}")
        raise

# 📌 [FIX 5] ฟังก์ชันดึงไฟล์ (สำหรับ Streaming/Download)
async def download_file_from_firebase(blob_name: str) -> bytes:
    """ดาวน์โหลดไฟล์ (bytes) จาก Firebase Storage"""
    if not bucket:
        raise Exception("Firebase Storage not initialized.")
    
    blob = bucket.blob(blob_name)
    
    # 📌 [CRITICAL FIX B] ใช้ try/except เพื่อให้ NotFound ถูกโยนออกไป 
    # และถูกดักจับใน files.py (ซึ่งจะแปลงเป็น HTTP 404)
    try:
        # NOTE: ไม่ต้องใช้ blob.exists() เพราะ download_as_bytes() จะโยน NotFound/Forbidden เอง
        file_bytes = blob.download_as_bytes()
        return file_bytes
    except NotFound as e:
        # 📌 เมื่อไม่พบไฟล์ ให้โยน NotFound ขึ้นไป (files.py จะแปลงเป็น 404)
        print(f"FIREBASE_CLIENT_DEBUG: Download failed - Blob '{blob_name}' Not Found.")
        raise NotFound(f"Blob {blob_name} not found.") from e
    except Forbidden as e:
        # 📌 เมื่อสิทธิ์ถูกปฏิเสธ ให้โยน Forbidden ขึ้นไป (files.py จะแปลงเป็น 403)
        print(f"FIREBASE_CLIENT_ERROR: Permission Denied for {blob_name}. {e}")
        raise Forbidden(f"Permission denied for {blob_name}.") from e
    except Exception as e:
        # 📌 ข้อผิดพลาดทั่วไปอื่นๆ
        print(f"FIREBASE_CLIENT_ERROR: Unknown error during download: {e}")
        raise Exception(f"Firebase Download Error: {e}") from e
    
    