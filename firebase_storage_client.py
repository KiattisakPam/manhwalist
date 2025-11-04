# backend/firebase_storage_client.py

import firebase_admin
from firebase_admin import credentials, storage
import os
from typing import Optional

# 📌 [FIX 1] ตั้งค่า Storage Bucket
# [*** สำคัญ ***] เปลี่ยน 'comic-secretary.appspot.com' เป็นชื่อ Bucket จริงของคุณ
FIREBASE_BUCKET_NAME = os.environ.get("FIREBASE_BUCKET_NAME", "comic-secretary.appspot.com")


# 📌 [FIX 2] Initialize Firebase Admin SDK
try:
    # Service Account File Name (ต้องมีไฟล์นี้อยู่ใน root ของ Backend)
    cred = credentials.Certificate("firebase-service-account.json") 
    
    firebase_admin.initialize_app(cred, {
        'storageBucket': FIREBASE_BUCKET_NAME
    })
    print("INFO: Firebase Admin SDK initialized successfully for Storage.")
    bucket = storage.bucket()
    
except Exception as e:
    # นี่คือการจัดการ Error เมื่อ Initialization ล้มเหลว (เช่น ไฟล์ .json หาย)
    print(f"ERROR: Failed to initialize Firebase Admin SDK for Storage: {e}")
    bucket = None


# 📌 [FIX 3] ฟังก์ชันอัปโหลด Binary Data
async def upload_file_to_firebase(file_bytes: bytes, destination_blob_name: str, content_type: Optional[str] = 'application/octet-stream') -> str:
    """อัปโหลดไฟล์ (bytes) ไปยัง Firebase Storage และคืนค่า URL สาธารณะ"""
    if not bucket:
        raise Exception("Firebase Storage not initialized.")
    
    blob = bucket.blob(destination_blob_name)
    
    # อัปโหลดไฟล์
    blob.upload_from_string(
        data=file_bytes,
        content_type=content_type
    )
    
    # ตั้งค่าให้ไฟล์เข้าถึงได้แบบสาธารณะ
    blob.make_public()
    
    return blob.public_url # คืนค่า Public URL


# 📌 [FIX 4] ฟังก์ชันลบไฟล์
async def delete_file_from_firebase(blob_name: str):
    """ลบไฟล์ออกจาก Firebase Storage"""
    if not bucket:
        raise Exception("Firebase Storage not initialized.")
    
    blob = bucket.blob(blob_name)
    if blob.exists():
        blob.delete()
        print(f"INFO: Successfully deleted blob: {blob_name}")
        return True
    print(f"WARNING: Blob not found for deletion: {blob_name}")
    return False

# 📌 [FIX 5] ฟังก์ชันดึงไฟล์ (สำหรับ Streaming/Download)
async def download_file_from_firebase(blob_name: str) -> Optional[bytes]:
    """ดาวน์โหลดไฟล์ (bytes) จาก Firebase Storage"""
    if not bucket:
        raise Exception("Firebase Storage not initialized.")
    
    blob = bucket.blob(blob_name)
    if blob.exists():
        return blob.download_as_bytes()
    return None

