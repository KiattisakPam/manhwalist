# backend/firebase_storage_client.py

import firebase_admin
from firebase_admin import credentials, storage
from google.cloud.exceptions import NotFound, Forbidden 
import os
import json 
from typing import Optional, Iterator
from fastapi.responses import StreamingResponse
# 🛑 ไม่ต้อง import urllib.parse
from google.cloud.storage.blob import Blob 

# ตั้งค่า Storage Bucket 
FIREBASE_BUCKET_NAME = os.environ.get("FIREBASE_BUCKET_NAME", "comic-secretary.firebasestorage.app")

try:
    json_credential_str = os.environ.get("FIREBASE_CREDENTIALS_JSON")
    
    if json_credential_str:
        cred = credentials.Certificate(json.loads(json_credential_str))
    else:
        # Fallback (ถ้ายังใช้ไฟล์ .json)
        cred = credentials.Certificate("firebase-service-account.json") 
        
    if not firebase_admin._apps: 
        firebase_admin.initialize_app(cred, {
            'storageBucket': FIREBASE_BUCKET_NAME
        })
        print("INFO: Firebase Admin SDK initialized successfully for Storage.")
    else:
        print("INFO: Firebase Admin SDK already initialized by another worker.") 
    
    bucket = storage.bucket(FIREBASE_BUCKET_NAME)
    
except Exception as e:
    print(f"ERROR: Failed to initialize Firebase Admin SDK for Storage: {e}")
    bucket = None


async def upload_file_to_firebase(file_bytes: bytes, destination_blob_name: str, content_type: Optional[str] = 'application/octet-stream') -> str:
    """อัปโหลดไฟล์ (bytes) ไปยัง Firebase Storage และคืนค่า URL สาธารณะ"""
    if not bucket:
        raise Exception("Firebase Storage not initialized.")
    
    # 🛑 [CRITICAL FIX] ใช้ Blob Name (Unicode String) ตรงๆ ให้ Google Client Library จัดการ Encoding
    blob = bucket.blob(destination_blob_name) 
    
    print(f"FIREBASE_CLIENT_DEBUG: Uploading Blob: {destination_blob_name}")
    
    blob.upload_from_string(
        data=file_bytes,
        content_type=content_type
    )
    
    return destination_blob_name

async def delete_file_from_firebase(blob_name: str):
    """ลบไฟล์ออกจาก Firebase Storage"""
    if not bucket:
        raise Exception("Firebase Storage not initialized.")
    
    # 🛑 [CRITICAL FIX] ใช้ Blob Name (Unicode String) ตรงๆ
    try:
        blob = bucket.blob(blob_name)
        blob.delete()
        print(f"INFO: Successfully deleted blob: {blob_name}")
        return True
    except NotFound:
        print(f"WARNING: Blob not found for deletion: {blob_name}")
        return False
    except Exception as e:
        print(f"ERROR: Failed to delete blob {blob_name}: {e}")
        raise

async def download_file_from_firebase(blob_name: str) -> bytes:
    """ดาวน์โหลดไฟล์ (bytes) จาก Firebase Storage"""
    if not bucket:
        raise Exception("Firebase Storage not initialized.")
    
    # 🛑 [CRITICAL FIX] ใช้ Blob Name (Unicode String) ตรงๆ
    blob = bucket.blob(blob_name)
    
    try:
        file_bytes = blob.download_as_bytes()
        return file_bytes
    except NotFound as e:
        print(f"FIREBASE_CLIENT_DEBUG: Download failed - Blob '{blob_name}' Not Found.")
        raise NotFound(f"Blob {blob_name} not found.") from e
    except Forbidden as e:
        print(f"FIREBASE_CLIENT_ERROR: Permission Denied for Blob: {blob_name}. {e}")
        raise Forbidden(f"Permission denied for {blob_name}.") from e
    except Exception as e:
        print(f"FIREBASE_CLIENT_ERROR: Unknown error during download for '{blob_name}': {type(e).__name__} - {e}")
        raise Exception(f"Firebase Download Error: {e}") from e
    
