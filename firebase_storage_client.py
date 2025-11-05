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
import urllib.parse

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
    
    # 🛑 [CRITICAL FIX A] บังคับ Encode Blob Name ก่อนใช้งานใน Client (เพื่อให้สอดคล้องกับการดาวน์โหลด)
    encoded_blob_name = urllib.parse.quote(destination_blob_name)
    blob = bucket.blob(encoded_blob_name) 
    
    print(f"FIREBASE_CLIENT_DEBUG: Uploading Encoded Blob: {encoded_blob_name}")
    
    # อัปโหลดไฟล์
    blob.upload_from_string(
        data=file_bytes,
        content_type=content_type
    )
    
    return destination_blob_name # 📌 [FIX] คืนค่า Blob Name แทน Public URL

# 📌 [FIX 4] ฟังก์ชันลบไฟล์
async def delete_file_from_firebase(blob_name: str):
    """ลบไฟล์ออกจาก Firebase Storage"""
    if not bucket:
        raise Exception("Firebase Storage not initialized.")
    
    # 📌 [CRITICAL FIX] บังคับ Encode ชื่อ Blob ก่อนเรียก Blob
    encoded_blob_name = urllib.parse.quote(blob_name)
    
    try:
        blob = bucket.blob(encoded_blob_name)
        blob.delete()
        print(f"INFO: Successfully deleted encoded blob: {encoded_blob_name}")
        return True
    except NotFound:
        print(f"WARNING: Encoded Blob not found for deletion: {encoded_blob_name}")
        return False
    except Exception as e:
        print(f"ERROR: Failed to delete blob {encoded_blob_name}: {e}")
        raise

# 📌 [FIX 5] ฟังก์ชันดึงไฟล์ (สำหรับ Streaming/Download)
async def download_file_from_firebase(blob_name: str) -> bytes:
    """ดาวน์โหลดไฟล์ (bytes) จาก Firebase Storage"""
    if not bucket:
        raise Exception("Firebase Storage not initialized.")
    
    # 🛑 [CRITICAL FIX C] บังคับ Encode Blob Name
    encoded_blob_name = urllib.parse.quote(blob_name)
    blob = bucket.blob(encoded_blob_name)
    
    try:
        file_bytes = blob.download_as_bytes()
        return file_bytes
    except NotFound as e:
        print(f"FIREBASE_CLIENT_DEBUG: Download failed - Encoded Blob '{encoded_blob_name}' Not Found.")
        raise NotFound(f"Blob {blob_blob_name} not found.") from e
    except Forbidden as e:
        print(f"FIREBASE_CLIENT_ERROR: Permission Denied for Encoded Blob: {encoded_blob_name}. {e}")
        raise Forbidden(f"Permission denied for {blob_name}.") from e
    except Exception as e:
        print(f"FIREBASE_CLIENT_ERROR: Unknown error during download: {e}")
        raise Exception(f"Firebase Download Error: {e}") from e
    
    

    