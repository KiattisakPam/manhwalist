# backend/telegram_config.py (ไฟล์ใหม่)
import os
import httpx
from typing import Optional
from config import settings
from requests_toolbelt.multipart.encoder import MultipartEncoder 
import io
import json

# แก้ไขให้รับพารามิเตอร์ bot_type
async def send_telegram_notification(chat_id: str, message: str, 
                                     bot_type: str, # 'NOTIFY' หรือ 'REPORT'
                                     disable_notification: bool = False) -> Optional[dict]:

    if bot_type == 'REPORT':
        bot_token = settings.TELEGRAM_BOT_TOKEN_REPORT
    else:
        # ใช้ NOTIFY เป็นค่าเริ่มต้นสำหรับงานใหม่
        bot_token = settings.TELEGRAM_BOT_TOKEN_NOTIFY

    if not bot_token:
        print(f"Warning: TELEGRAM_BOT_TOKEN_{bot_type} not set.")
        return None

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown", 
        "disable_notification": disable_notification
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, data=data)
            response.raise_for_status() 
            print(f"INFO: Sent Telegram message to chat_id {chat_id}.")
            return response.json()
    except Exception as e:
        print(f"ERROR: Failed to send Telegram notification to {chat_id}: {e}")
        return None
    
    
    
async def send_telegram_photo(chat_id: str, photo_url: str, caption: Optional[str] = None, bot_type: str = 'REPORT') -> Optional[dict]:
    """ส่งรูปภาพไปยัง Telegram Chat ID ที่กำหนด (ใช้ Bot B สำหรับ Report)"""
    
    if bot_type == 'NOTIFY':
        bot_token = settings.TELEGRAM_BOT_TOKEN_NOTIFY
    else:
        bot_token = settings.TELEGRAM_BOT_TOKEN_REPORT # Bot B

    if not bot_token:
        print(f"Warning: TELEGRAM_BOT_TOKEN_{bot_type} not set.")
        return None

    # ใช้เมธอด sendPhoto ของ Telegram
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    
    data = {
        "chat_id": chat_id,
        "photo": photo_url, # URL ของรูปภาพ
        "caption": caption,
        "parse_mode": "Markdown", 
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, data=data)
            response.raise_for_status() 
            print(f"INFO: Sent Telegram photo to chat_id {chat_id}.")
            return response.json()
    except Exception as e:
        # NOTE: การใช้ response.status_code จะช่วยให้ Debug ได้ดีขึ้น
        error_detail = f"Status {response.status_code}: {response.text}" if 'response' in locals() else str(e)
        print(f"ERROR: Failed to send Telegram photo to {chat_id}: {error_detail}")
        return None
    

async def send_telegram_photo_in_memory(chat_id: str, photo_bytes: bytes, filename: str, caption: Optional[str] = None, bot_type: str = 'REPORT') -> Optional[dict]:
    """ส่งรูปภาพไปยัง Telegram Chat ID ที่กำหนด โดยใช้ข้อมูล Binary (In-Memory)"""
    
    if bot_type == 'NOTIFY':
        bot_token = settings.TELEGRAM_BOT_TOKEN_NOTIFY
    else:
        bot_token = settings.TELEGRAM_BOT_TOKEN_REPORT 

    if not bot_token:
        print(f"Warning: TELEGRAM_BOT_TOKEN_{bot_type} not set.")
        return None

    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    
    # 1. เตรียม Multipart Data
    # 'photo' คือ field name ที่ Telegram Bot คาดหวัง
    m = MultipartEncoder(
        fields={
            'chat_id': str(chat_id),
            'caption': caption if caption else '',
            'parse_mode': 'Markdown',
            # 📌 ส่งไฟล์ Binary: (file_stream, filename, content_type)
            'photo': (filename, io.BytesIO(photo_bytes), 'image/jpeg') 
        }
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url, 
                content=m.to_string(), # ส่ง Multipart Encoder String
                headers={'Content-Type': m.content_type}
            )
            response.raise_for_status() 
            print(f"INFO: Sent Telegram photo (In-Memory) to {chat_id}.")
            return response.json()
    except Exception as e:
        error_detail = f"Status {response.status_code}: {response.text}" if 'response' in locals() else str(e)
        print(f"ERROR: Failed to send Telegram photo (In-Memory) to {chat_id}: {error_detail}")
        return None
    
    
async def send_telegram_media_group(chat_id: str, photo_urls: list[str], bot_type: str = 'REPORT', caption: Optional[str] = None) -> Optional[dict]:
    """ส่งหลายรูปภาพเป็นอัลบั้ม (Media Group) ไปยัง Telegram Chat ID ที่กำหนด"""
    
    if bot_type == 'NOTIFY':
        bot_token = settings.TELEGRAM_BOT_TOKEN_NOTIFY
    else:
        bot_token = settings.TELEGRAM_BOT_TOKEN_REPORT 

    if not bot_token or not photo_urls:
        print(f"Warning: Cannot send media group. Token not set or photo_urls is empty.")
        return None

    url = f"https://api.telegram.org/bot{bot_token}/sendMediaGroup"
    
    # 1. สร้างรายการ InputMediaPhoto objects
    media_list = []
    for i, photo_url in enumerate(photo_urls):
        media_item = {
            "type": "photo",
            "media": photo_url,
        }
        # ใส่ caption ให้เฉพาะภาพแรกเท่านั้น
        if i == 0 and caption:
             media_item["caption"] = caption
             media_item["parse_mode"] = "Markdown"
        
        media_list.append(media_item)

    data = {
        "chat_id": chat_id,
        "media": json.dumps(media_list) # ต้องแปลง list เป็น JSON String
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client: # เพิ่ม timeout สำหรับ Media Group
            response = await client.post(url, data=data)
            response.raise_for_status() 
            print(f"INFO: Sent Telegram media group to {chat_id}.")
            return response.json()
    except Exception as e:
        error_detail = f"Status {response.status_code}: {response.text}" if 'response' in locals() else str(e)
        print(f"ERROR: Failed to send Telegram media group to {chat_id}: {error_detail}")
        return None
    
    
# 📌 [FIX] สร้างฟังก์ชันใหม่สำหรับส่งเป็น Document/File
async def send_telegram_document_in_memory(chat_id: str, document_bytes: bytes, filename: str, caption: Optional[str] = None, bot_type: str = 'REPORT') -> Optional[dict]:
    """ส่งไฟล์ไปยัง Telegram Chat ID ที่กำหนด โดยใช้ข้อมูล Binary (In-Memory) เป็น Document"""
    
    if bot_type == 'NOTIFY':
        bot_token = settings.TELEGRAM_BOT_TOKEN_NOTIFY
    else:
        bot_token = settings.TELEGRAM_BOT_TOKEN_REPORT 

    if not bot_token:
        print(f"Warning: TELEGRAM_BOT_TOKEN_{bot_type} not set.")
        return None

    # 📌 ใช้เมธอด sendDocument
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    
    # 1. เตรียม Multipart Data
    # 'document' คือ field name ที่ Telegram Bot คาดหวัง
    m = MultipartEncoder(
        fields={
            'chat_id': str(chat_id),
            'caption': caption if caption else '',
            'parse_mode': 'Markdown',
            # 📌 ส่งไฟล์ Binary: ใช้ field 'document'
            'document': (filename, io.BytesIO(document_bytes), 'image/jpeg') 
        }
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url, 
                content=m.to_string(), 
                headers={'Content-Type': m.content_type}
            )
            response.raise_for_status() 
            print(f"INFO: Sent Telegram document (In-Memory) to {chat_id}.")
            return response.json()
    except Exception as e:
        error_detail = f"Status {response.status_code}: {response.text}" if 'response' in locals() else str(e)
        print(f"ERROR: Failed to send Telegram document (In-Memory) to {chat_id}: {error_detail}")
        return None

# หมายเหตุ: ไม่ต้องแก้ไข send_telegram_photo_in_memory แต่ปล่อยให้มันอยู่เฉยๆ


    