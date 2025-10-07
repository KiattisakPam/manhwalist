# ตัวอย่างโค้ดใน config.py (สมมติว่าคุณใช้ pydantic-settings)
# (คุณอาจต้องติดตั้ง pydantic-settings ถ้ายังไม่ได้ติดตั้ง)

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # 'DATABASE_URL' จะถูกอ่านจาก Environment Variable ในระบบโฮสต์
    # ถ้าไม่มีค่า (เช่น รันบนเครื่อง local โดยไม่มี .env) จะใช้ค่า default
    DATABASE_URL: str 

    class Config:
        env_file = ".env" # สามารถเพิ่มการอ่านจาก .env ใน Local ได้

settings = Settings()

