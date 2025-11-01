# backend/tasks.py (ไฟล์ใหม่สำหรับ Background tasks)

import asyncio
import datetime
import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession
from database import AsyncSessionLocal # <<< ต้องสร้าง session maker สำหรับใช้ภายนอก dependency
from routers.comics import get_comics_to_update_tomorrow
from routers.users import get_user_from_db # ใช้เพื่อดึง Chat ID ของผู้จ้าง
import telegram_config
from models import users # ต้องเข้าถึงตาราง users

# NOTE: ต้องปรับ database.py เพื่อ Export AsyncSessionLocal
# (สมมติว่าคุณได้ทำแล้ว โดยให้ AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))

async def run_daily_update_notification():
    """รันทุกคืนเพื่อแจ้งเตือนเรื่องที่จะอัปเดตในวันพรุ่งนี้"""
    print(f"INFO: Running Daily Update Check at {datetime.datetime.now(datetime.timezone.utc)}")

    async with AsyncSessionLocal() as db:
        # 1. ดึง User IDs ของผู้จ้างทั้งหมด
        employer_ids_res = await db.execute(
            sqlalchemy.select(users.c.id, users.c.telegram_report_chat_id).where(users.c.role == 'employer')
        )
        employers_info = employer_ids_res.mappings().all()
        
        for employer in employers_info:
            employer_id = employer.id
            report_chat_id = employer.telegram_report_chat_id
            
            if not report_chat_id:
                print(f"WARNING: Employer {employer_id} has no Report Chat ID set. Skipping notification.")
                continue

            # 2. ดึงการ์ตูนที่จะอัปเดตวันพรุ่งนี้
            comics_list = await get_comics_to_update_tomorrow(db, employer_id)

            if not comics_list:
                print(f"INFO: No comics scheduled for update tomorrow for employer {employer_id}.")
                continue
            
            # 3. เตรียมข้อความแจ้งเตือน
            tomorrow_date = (datetime.datetime.now(datetime.timezone.utc).date() + datetime.timedelta(days=1)).strftime('%d/%m')
            
            message_parts = [
                f"🌟 *แจ้งเตือนอัปเดตวันพรุ่งนี้ ({tomorrow_date})* 🌟",
                "รายการการ์ตูนที่มีกำหนดอัปเดตตามตาราง:",
                ""
            ]
            
            for i, comic in enumerate(comics_list):
                # โหลดภาพปก
                image_url = f"{telegram_config.settings.BACKEND_BASE_URL}/covers/{comic.image_file}" if comic.image_file else None
                
                # รายละเอียด
                detail = f"กำหนด: {comic.update_type} ({comic.update_value})"
                if comic.pause_start_date and comic.pause_end_date:
                    detail = f"สถานะ: พักงาน ({comic.pause_start_date} - {comic.pause_end_date})"
                    
                message_parts.append(f"{i+1}. *{comic.title}*")
                message_parts.append(f"  _ล่าสุด (ทำแล้ว):_ Ep {comic.last_updated_ep}")
                message_parts.append(f"  _ต้นฉบับถึง:_ Ep {comic.original_latest_ep}")
                message_parts.append(f"  _{detail}_\n")

                # NOTE: Telegram Markdown ไม่รองรับการฝังภาพในข้อความ แต่เราสามารถส่งภาพแยกได้ (ต้องใช้ Bot API method photo)
                # เราจะส่งข้อความเป็นข้อความธรรมดาก่อน

            final_message = "\n".join(message_parts)

            # 4. ส่ง Telegram Notification
            await telegram_config.send_telegram_notification(
                report_chat_id, 
                final_message,
                bot_type='REPORT' # ใช้ Bot B
            )
            print(f"INFO: Sent daily update notification to employer {employer_id}")

if __name__ == '__main__':
    # ตัวอย่างการรัน (ใช้สำหรับการทดสอบ)
    asyncio.run(run_daily_update_notification())
    
    