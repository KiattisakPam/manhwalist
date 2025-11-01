# backend/telegram_config.py (ไฟล์ใหม่)
import os
import httpx
from typing import Optional
from config import settings

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
    
    
    