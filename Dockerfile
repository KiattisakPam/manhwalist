# ใช้ Base Image ที่มี Python 3.11 ที่เสถียร
FROM python:3.11-slim

# ตั้งค่า Environment Variable ที่จำเป็น
ENV PYTHONUNBUFFERED 1
ENV PORT 8080

# ติดตั้ง Dependencies ของระบบ (จำเป็นสำหรับการ Build PostgreSQL Driver)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# ตั้งค่า Working Directory
WORKDIR /app

# คัดลอก requirements.txt และติดตั้งแพ็กเกจ
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# คัดลอกโค้ดส่วนที่เหลือ (backend_main.py, config.py, ฯลฯ)
COPY . /app

# Command ที่จะรันเมื่อ Container เริ่มทำงาน
CMD gunicorn main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT
