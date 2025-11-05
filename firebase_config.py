# firebase_config.py (ปรับโค้ดให้โหลดจาก ENV)
import firebase_admin
from firebase_admin import credentials, messaging
import os
import json # <<< เพิ่ม import json

# --- แก้ไขตรงนี้ ---
FIREBASE_CREDENTIALS_JSON = os.environ.get('FIREBASE_CREDENTIALS_JSON')

if FIREBASE_CREDENTIALS_JSON:
    try:
        # 📌 [CRITICAL FIX] ตรวจสอบว่า Default App ยังไม่ถูก Initialize
        if not firebase_admin._apps: 
            # โหลด credentials จาก JSON string ใน Environment Variable
            cred_dict = json.loads(FIREBASE_CREDENTIALS_JSON)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            print("INFO: Firebase Admin SDK initialized successfully for Messaging.")
        else:
            print("INFO: Firebase Admin SDK was already initialized.")

        # 📌 [FIX] โหลด Storage Bucket (ถ้าใช้)
        # ตรวจสอบว่าคุณมีโค้ดสำหรับ Storage Initialization แยกต่างหากหรือไม่
        # ถ้าคุณมีโค้ดในไฟล์อื่น (เช่น firebase_storage_client.py) ที่เรียก initialize_app ซ้ำ คุณต้องแก้ตรงนั้นด้วย
        
    except Exception as e:
        print(f"Error initializing Firebase Admin SDK: {e}")
else:
    print("Warning: FIREBASE_CREDENTIALS_JSON environment variable not found. Firebase notifications will be disabled.")
    

def send_notification(tokens: list[str], title: str, body: str):
    if not firebase_admin._apps:
        print("Firebase not initialized, cannot send notification.")
        return

    if not tokens:
        return
    
    message = messaging.MulticastMessage(
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        tokens=tokens,
    )
    try:
        response = messaging.send_multicast(message)
        print(f'Successfully sent message: {response.success_count} successes, {response.failure_count} failures')
    except Exception as e:
        print(f"Error sending notification: {e}")
        
        