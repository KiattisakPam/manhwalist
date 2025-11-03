# ตัวอย่างโค้ดใน config.py (สมมติว่าคุณใช้ pydantic-settings)
# (คุณอาจต้องติดตั้ง pydantic-settings ถ้ายังไม่ได้ติดตั้ง)

from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # 📌 [FIX] ต้องตั้งค่าให้ BACKEND_BASE_URL ถูกอ่านจาก Environment Variable ของ Render
    DATABASE_URL: str 
    INVITATION_CODE: str = "DEFAULT_SECRET_CHANGE_ME"
    
    BACKEND_BASE_URL: str = "https://manhwalist-final.onrender.com"
    
    TELEGRAM_BOT_TOKEN_NOTIFY: Optional[str] = None # <<< Bot A
    TELEGRAM_BOT_TOKEN_REPORT: Optional[str] = None # <<< Bot B

    class Config:
        env_file = ".env" # สามารถเพิ่มการอ่านจาก .env ใน Local ได้

settings = Settings()

