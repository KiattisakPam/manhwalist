from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Pydantic จะอ่านค่านี้จาก Environment Variable ก่อน
    # ถ้าไม่เจอ จะอ่านจากไฟล์ .env ที่เราสร้างไว้
    DATABASE_URL: str

    class Config:
        env_file = ".env"

# สร้าง instance ของ Settings เพื่อให้ไฟล์อื่นเรียกใช้ได้
settings = Settings()

