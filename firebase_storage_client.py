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
    """อัปโหลดไฟล์ (bytes) ไปยัง Firebase Storage (โดยไม่ encode ชื่อไฟล์เอง)"""
    if not bucket:
        raise Exception("Firebase Storage not initialized.")
    
    # 🛑 [FIX] ใช้ destination_blob_name ตรงๆ (เช่น "job_files/My File.zip")
    blob = bucket.blob(destination_blob_name) 
    
    print(f"FIREBASE_CLIENT_DEBUG: Uploading Blob: {destination_blob_name}")
    
    blob.upload_from_string(
        data=file_bytes,
        content_type=content_type
    )
    
    # 🛑 คืนค่าชื่อเดิมที่ได้รับมา
    return destination_blob_name 

async def delete_file_from_firebase(blob_name: str):
    """ลบไฟล์ออกจาก Firebase Storage (โดยไม่ encode ชื่อไฟล์เอง)"""
    if not bucket:
        raise Exception("Firebase Storage not initialized.")
    
    try:
        # 🛑 [FIX] ใช้ blob_name ตรงๆ
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
    
    # 1. 🛑 [CRITICAL FIX] บังคับให้ชื่อ Blob เป็น UTF-8 bytes ก่อนส่งไป quote
    #    บางครั้ง Python Environment ใช้ Encoding ผิดพลาดกับ urllib.quote
    
    # NOTE: เราไม่ควรเรียก quote ซ้ำที่นี่ ถ้า Blob Name ถูกส่งมาเป็น Unicode string 
    #       (ซึ่งมันควรจะเป็น) Google Client Library ควรจัดการเอง
    
    # เราจะลองเปลี่ยนไปใช้ Blob Name ตรงๆ ที่ถูก Cleanse มาแล้ว และเชื่อมั่นว่า 
    # Google Client Library จะจัดการ Encoding ได้ ถ้ามันรับ string ที่เป็น Unicode

    # 🛑 [FINAL FIX ATTEMPT] เปลี่ยน urllib.quote เป็นการใช้ blob_name ตรงๆ ใน bucket.blob()
    #    เนื่องจาก Blob Name ถูก Unquote ใน files.py แล้ว จึงควรเป็น Unicode string ที่ถูกต้อง
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
        # 🛑 [DEBUG] พิมพ์ชนิดของ Exception เพื่อยืนยันว่าไม่ใช่ Network Error ธรรมดา
        print(f"FIREBASE_CLIENT_ERROR: Unknown error during download for '{blob_name}': {type(e).__name__} - {e}")
        # Error: 'latin-1' codec can't encode...
        
        # 🛑 [CRITICAL FIX] หาก Error ยังคงเกิดที่นี่ ให้สันนิษฐานว่าชื่อไฟล์ 
        # ต้องถูก URL Encode ก่อนเข้าสู่ Google API Call
        
        if type(e).__name__ == 'UnicodeEncodeError':
             # ถ้าเกิด Unicode Error แสดงว่า Environment พยายาม encode ด้วย Latin-1
             # เราต้องกลับไปใช้ urllib.quote และหวังว่ามันจะถูกส่งเป็น UTF-8
             
             # **Undo the previous attempt and retry with quote**
             # Since it failed with Latin-1, let's force the quote process again
             
             encoded_blob_name = urllib.parse.quote(blob_name)
             blob = bucket.blob(encoded_blob_name)
             file_bytes = blob.download_as_bytes()
             return file_bytes
             
        raise Exception(f"Firebase Download Error: {e}") from e
    
