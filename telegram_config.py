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
    
    