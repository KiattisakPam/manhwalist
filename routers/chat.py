from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
import sqlalchemy
import datetime
import os
import shutil
from typing import List, Dict, Optional
from sqlalchemy.dialects import postgresql
from database import get_db
from models import users, employees, chat_rooms, chat_messages, jobs, comics, chat_read_status, fcm_devices
from schemas import User, ChatRoomInfo, ChatRoomCreate, ChatRoomListResponse
import auth
import firebase_config
import asyncio
import telegram_config
import firebase_storage_client

router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, room_id: int, websocket: WebSocket):
        await websocket.accept()
        if room_id not in self.active_connections:
            self.active_connections[room_id] = []
        self.active_connections[room_id].append(websocket)

    def disconnect(self, room_id: int, websocket: WebSocket):
        if room_id in self.active_connections:
            self.active_connections[room_id].remove(websocket)

    async def broadcast(self, room_id: int, message: dict):
        if room_id in self.active_connections:
            for connection in self.active_connections[room_id]:
                await connection.send_json(message)

manager = ConnectionManager()

@router.websocket("/ws/{room_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    room_id: int,
    token: str,
    db: AsyncSession = Depends(get_db)
):
    try:
        current_user = await auth.get_current_user_from_token(token, db)
    except HTTPException:
        await websocket.close(code=1008)
        return

    current_user_email = current_user.email
    current_user_role = current_user.role

    await manager.connect(room_id, websocket)
    print(f"INFO:     Client {current_user.email} connected to room {room_id}")

    try:
        while True:
            data = await websocket.receive_json()
            print(f"DEBUG:     Received data from {current_user.email}: {data}")

            message_type = data.get("type", "text")

            # --- Logic การลบข้อความ (Delete Logic) ---
            if message_type == 'delete':
                message_id = data.get("message_id")
                if message_id:
                    # (Logic ตรวจสอบสิทธิ์การลบ: Owner หรือ Employer)
                    msg_res = await db.execute(sqlalchemy.select(chat_messages.c.sender_id, chat_messages.c.room_id).where(chat_messages.c.id == message_id))
                    msg_info = msg_res.one_or_none()
                    
                    # (ส่วนตรวจสอบ can_delete ที่ซับซ้อนควรถูกย้ายไปในฟังก์ชัน helper หรือทำให้ง่ายขึ้นเพื่อหลีกเลี่ยง Error)
                    # แต่โดยพื้นฐานคือ:
                    if msg_info and msg_info.sender_id == current_user.id and msg_info.room_id == room_id:
                        await db.execute(sqlalchemy.delete(chat_messages).where(chat_messages.c.id == message_id))
                        await db.commit()
                        await manager.broadcast(room_id, {"type": "delete", "message_id": message_id})
                continue 
            # ----------------------------------------
            
            # --- Logic การบันทึกข้อความ (Save Logic) ---
            content = data.get("content") 
            if content is None:
                print(f"WARNING:  Received message with no 'content' from {current_user.email}. Data: {data}")
                continue

            now = datetime.datetime.now(datetime.timezone.utc).isoformat()

            insert_query = sqlalchemy.insert(chat_messages).values(
                room_id=room_id, sender_id=current_user.id, message_type=message_type,
                content=content, sent_at=now
            )
            result = await db.execute(insert_query)
            await db.commit()

            new_message_id = result.inserted_primary_key[0]
            print(f"INFO:     Message {new_message_id} from {current_user.email} saved to DB.")

            new_message = {
                "id": new_message_id, "room_id": room_id, "sender_id": current_user.id,
                "message_type": message_type, "content": content, "sent_at": now,
                "sender_email": current_user_email, "sender_role": current_user_role,
            }

            await manager.broadcast(room_id, new_message)
            print(f"INFO:     Broadcasting message {new_message_id} to room {room_id}")

            # <<< FIX: วาง Logic การส่ง Notification หลัง Broadcast และก่อนวนซ้ำ >>>
            try:
                # 1. หาข้อมูลห้องแชท (Employer/Employee IDs)
                room_res = await db.execute(sqlalchemy.select(chat_rooms.c.employer_id, chat_rooms.c.employee_id).where(chat_rooms.c.id == room_id))
                room_info = room_res.mappings().first()
                if not room_info: raise Exception("Room info not found")

                target_user_id = None
                sender_name = ""

                # 2. กำหนดผู้รับ (Target User ID)
                if current_user_role == 'employer':
                    emp_res = await db.execute(sqlalchemy.select(employees.c.user_id).where(employees.c.id == room_info.employee_id))
                    target_user_id = emp_res.scalar_one_or_none()
                    sender_name = "ผู้จ้าง" 
                else: # ผู้ส่งคือ Employee
                    target_user_id = room_info.employer_id
                    emp_name_res = await db.execute(sqlalchemy.select(employees.c.name).where(employees.c.user_id == current_user.id))
                    sender_name = emp_name_res.scalar_one_or_none() or "พนักงาน"
                    
                # 3. ส่ง Notification ถ้าพบผู้รับ
                if target_user_id: 
                    # 1. กำหนด employee_id ที่ใช้ดึง Chat ID
                    employee_id_to_check = None
                    if current_user_role == 'employer':
                        # ผู้รับคือ Employee, ดึง ID จาก room_info
                        employee_id_to_check = room_info.employee_id
                        selected_bot_type = 'NOTIFY' # Bot A: ผู้จ้างส่ง
                    else: # ผู้ส่งคือ Employee
                        # ดึง ID ของ Employee ที่กำลังส่งข้อความ (ผู้ส่ง)
                        sender_emp_res = await db.execute(
                             sqlalchemy.select(employees.c.id).where(employees.c.user_id == current_user.id)
                        )
                        employee_id_to_check = sender_emp_res.scalar_one_or_none()
                        selected_bot_type = 'REPORT' # Bot B: พนักงานส่ง
                        
                    # 2. ดึง Chat ID จาก Employee Profile
                    telegram_chat_id = None
                    if employee_id_to_check:
                         emp_chat_res = await db.execute(
                            sqlalchemy.select(employees.c.telegram_chat_id)
                            .where(employees.c.id == employee_id_to_check)
                        )
                         telegram_chat_id = emp_chat_res.scalar_one_or_none()
                    
                    # 3. เตรียม Message สำหรับ Bridge App (ใช้ Logic เดิม)
                    bridge_message = {
                        "type": "NEW_CHAT",
                        "sender": sender_name,
                        "message_preview": content if message_type == 'text' else f"ส่ง{message_type}แนบมา",
                        "room_id": room_id,
                    }

                    # 4. ส่งสัญญาณไป Bridge App (Logic เดิม)
                    await notification_manager.send_personal_notification(target_user_id, bridge_message)

                    # 5. ส่ง Telegram (ใช้ Bot A หรือ Bot B ตามผู้ส่ง)
                    if telegram_chat_id:
                        title = f"✉️ ข้อความใหม่จาก {sender_name}"
                        body_preview = bridge_message['message_preview']
                        
                        # [แก้ไข] ข้อความที่สะอาดที่สุด (ไม่มีลิงก์)
                        telegram_message = (
                            f"*{title}*\n"
                            f"{body_preview}" 
                        )
                        
                        is_user_online = target_user_id in notification_manager.active_user_connections
                        
                        await telegram_config.send_telegram_notification(
                            telegram_chat_id, 
                            telegram_message, 
                            bot_type=selected_bot_type, # <<< [สำคัญ] ใช้ Bot ที่เลือก
                            disable_notification=is_user_online
                        )
                    
                    # 6. ส่ง FCM เป็นตัวสำรอง
                    token_query = sqlalchemy.select(fcm_devices.c.device_token).where(
                        fcm_devices.c.user_id == target_user_id, 
                        fcm_devices.c.is_active == True
                    )
                    tokens = (await db.execute(token_query)).scalars().all()

                    if tokens:
                        firebase_config.send_notification(
                            tokens=tokens,
                            title=f"✉️ ข้อความใหม่จาก {sender_name}",
                            body=bridge_message['message_preview']
                        )
                        print(f"INFO: Successfully sent FCM to User ID {target_user_id}")
            except Exception as e: # <-- โค้ดเดิมจะต่อจากบรรทัดนี้
                
                print(f"ERROR: Failed to send chat notification: {e}")
                
    except WebSocketDisconnect:
        manager.disconnect(room_id, websocket)
        print(f"INFO:     Client {current_user.email} disconnected from room {room_id}")
    except Exception as e:
        # Catch หลักสำหรับ Error อื่น ๆ
        print(f"ERROR:    An error occurred in websocket for user {current_user.email}: {e}")
        manager.disconnect(room_id, websocket)
        

# --- REST API Endpoints ---
@router.post("/rooms/find-or-create")
async def find_or_create_room_for_employer(
    participant_employee_id: int = Form(...),
    job_id: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth.get_current_employer_user)
):
    # 1. ค้นหาห้องแชททั่วไประหว่าง Employer และ Employee (job_id = None)
    query = sqlalchemy.select(chat_rooms).where(
        sqlalchemy.and_(
            chat_rooms.c.employer_id == current_user.id,
            chat_rooms.c.employee_id == participant_employee_id,
            chat_rooms.c.job_id.is_(None) 
        )
    )
    result = await db.execute(query)
    room = result.mappings().first()
    
    room_id = None
    
    if room:
        room_id = room.id
    else:
        # *** FIX: ถ้าไม่พบห้อง ให้สร้างห้องใหม่ทันที (ตามตรรกะ Find or Create) ***
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        insert_query = sqlalchemy.insert(chat_rooms).values(
            employer_id=current_user.id,
            employee_id=participant_employee_id,
            job_id=None,
            created_at=now
        )
        res = await db.execute(insert_query)
        room_id = res.inserted_primary_key[0]
        
    # 2. ถ้ามีการระบุ job_id มา (จากการกดปุ่ม 'คุยงานเรื่องนี้') ให้สร้าง System Message
    if job_id is not None:
        job_info_res = await db.execute(
            sqlalchemy.select(comics.c.title, jobs.c.episode_number)
            .select_from(jobs.join(comics, jobs.c.comic_id == comics.c.id))
            .where(jobs.c.id == job_id)
        )
        job_info = job_info_res.mappings().first()
        
        if job_info:
            context_content = f"CONTEXT:{job_info.title} (ตอนที่ {job_info.episode_number})::{job_id}"
            
            # แทรก System Message
            insert_query = sqlalchemy.insert(chat_messages).values(
                room_id=room_id,
                sender_id=current_user.id,
                message_type="context", 
                content=context_content,
                sent_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )
            await db.execute(insert_query)
        
    await db.commit()
    
    if room_id is None:
        raise HTTPException(status_code=500, detail="Failed to retrieve or create room ID.")
        
    return {"room_id": room_id}


@router.get("/rooms/all", response_model=ChatRoomListResponse)
async def get_all_chat_rooms_for_employer(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth.get_current_employer_user)
):
    print("\n--- [API CALL] /chat/rooms/all ---")
    print(f"User making request: ID={current_user.id}, Email={current_user.email}")

    sub_latest_msg = sqlalchemy.select(
        chat_messages.c.room_id,
        sqlalchemy.func.max(chat_messages.c.id).label('latest_msg_id'),
        sqlalchemy.func.max(chat_messages.c.sent_at).label('latest_sent_at')
    ).group_by(chat_messages.c.room_id).alias('latest_msg')

    rooms_query = sqlalchemy.select(
        chat_rooms.c.id, chat_rooms.c.job_id, chat_rooms.c.employee_id,
        employees.c.name.label('employee_name'),
        jobs.c.episode_number.label('job_episode_number'),
        comics.c.title.label('comic_title'),
        chat_messages.c.content.label('last_message_content'),
        sub_latest_msg.c.latest_sent_at.label('last_message_time'),
        chat_messages.c.message_type.label('last_message_type')
    ).select_from(
        chat_rooms.join(employees, chat_rooms.c.employee_id == employees.c.id)
        .outerjoin(jobs, chat_rooms.c.job_id == jobs.c.id) 
        .outerjoin(comics, jobs.c.comic_id == comics.c.id)
        .outerjoin(sub_latest_msg, chat_rooms.c.id == sub_latest_msg.c.room_id)
        .outerjoin(chat_messages, chat_messages.c.id == sub_latest_msg.c.latest_msg_id)
    ).where(chat_rooms.c.employer_id == current_user.id)
    rooms_query = rooms_query.order_by(sqlalchemy.desc(sub_latest_msg.c.latest_sent_at)) 

    room_results = (await db.execute(rooms_query)).mappings().all()

    total_unread_count = 0
    response_list = []

    print(f"Found {len(room_results)} chat room(s) for this user.")

    for room in room_results:
        print(f"\n[DEBUG] Processing Room ID: {room.id}")
        print(f"[DEBUG] Room Employee ID: {room.employee_id}") # <--- LOG ใหม่
        
        # 1. ค้นหา User ID ของพนักงาน
        employee_user_id_res = await db.execute(
            sqlalchemy.select(employees.c.user_id)
            .where(employees.c.id == room.employee_id)
        )
        employee_user_id = employee_user_id_res.scalar_one_or_none() 
        print(f"[DEBUG] Employee User ID: {employee_user_id}") # <--- LOG ใหม่

        unread_count = 0
        
        if employee_user_id is not None: 
            # 2. ดึง ID ของข้อความที่อ่านล่าสุด
            last_read_res = await db.execute(
                sqlalchemy.select(chat_read_status.c.last_read_message_id)
                .where(chat_read_status.c.room_id == room.id, chat_read_status.c.user_id == current_user.id)
            )
            last_read_message_id = last_read_res.scalar_one_or_none() or 0 
            print(f"[DEBUG] Last Read Message ID for User {current_user.id}: {last_read_message_id}") # <--- LOG ใหม่

            # 3. Query เพื่อนับข้อความที่ยังไม่ได้อ่าน
            unread_count_query = sqlalchemy.select(sqlalchemy.func.count(chat_messages.c.id)).where(
                chat_messages.c.room_id == room.id,
                # เงื่อนไขการนับที่ถูกต้อง (นับเฉพาะข้อความที่ส่งจากพนักงาน)
                chat_messages.c.sender_id == employee_user_id, 
                chat_messages.c.id > last_read_message_id 
            )
        
            unread_count = await db.scalar(unread_count_query) or 0
            print(f"[DEBUG] Calculated Unread Count: {unread_count} for Room {room.id}") # <<< เพิ่ม Log นี้        
        total_unread_count += unread_count # <--- ต้องรวม Unread Count ตรงนี้ด้วย

        job_context = None
        if room.job_id is not None and room.comic_title is not None and room.job_episode_number is not None:
            job_context = f"{room.comic_title} (ตอนที่ {room.job_episode_number})"

        last_msg_content = None
        if room.last_message_content:
            if room.last_message_type == 'text':
                last_msg_content = room.last_message_content
            elif room.last_message_type == 'image':
                last_msg_content = "รูปภาพ..."
            elif room.last_message_type == 'file':
                last_msg_content = "ไฟล์แนบ..."
            elif room.last_message_type == 'context':
                last_msg_content = "มีการแชร์งาน..."

        room_info = {
            "id": room.id,
            "participant_name": room.employee_name,
            "participant_role": "employee",
            "job_id": room.job_id,
            "job_context": job_context, 
            "last_message": last_msg_content,
            "last_message_time": room.last_message_time,
            "unread_count": unread_count,
        }
        response_list.append(room_info)
        

    print("--- [API CALL END] ---")
    return {"total_unread_count": total_unread_count, "rooms": response_list}

@router.post("/rooms/employee/find-or-create")
async def find_or_create_room_for_employee(
    job_id: Optional[int] = Form(None), 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth.get_current_user)
):
    emp_res = await db.execute(sqlalchemy.select(employees).where(employees.c.user_id == current_user.id))
    employee = emp_res.mappings().first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee profile not found")

    # 1. ค้นหาห้องแชททั่วไปเท่านั้น
    query = sqlalchemy.select(chat_rooms).where(
        sqlalchemy.and_(
            chat_rooms.c.employer_id == employee.employer_id,
            chat_rooms.c.employee_id == employee.id,
            chat_rooms.c.job_id.is_(None) 
        )
    )
    result = await db.execute(query)
    room = result.mappings().first()
    
    room_id = None
    
    if room:
        room_id = room.id
    else:
        # *** FIX: ถ้าไม่พบห้อง (ถูกลบไป) ให้สร้างห้องใหม่ทันที (เหมือน Employer) ***
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        insert_query = sqlalchemy.insert(chat_rooms).values(
            employer_id=employee.employer_id,
            employee_id=employee.id,
            job_id=None,
            created_at=now
        )
        res = await db.execute(insert_query)
        room_id = res.inserted_primary_key[0] # ดึง ID ที่สร้างใหม่
        
    # 2. ถ้ามีการระบุ job_id มา (จากการกดปุ่ม 'คุยงานเรื่องนี้') ให้สร้าง System Message
    if job_id is not None:
        job_comic_query = sqlalchemy.select(
            jobs.c.episode_number,
            comics.c.title.label("comic_title")
        ).select_from(
            jobs.join(comics, jobs.c.comic_id == comics.c.id)
        ).where(jobs.c.id == job_id)
        
        job_info = (await db.execute(job_comic_query)).mappings().first()
        
        if job_info:
            context_content = f"CONTEXT:{job_info.comic_title} (ตอนที่ {job_info.episode_number})::{job_id}"
            
            # แทรก System Message
            insert_query = sqlalchemy.insert(chat_messages).values(
                room_id=room_id,
                sender_id=current_user.id,
                message_type="context",
                content=context_content,
                sent_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )
            await db.execute(insert_query)
        
    await db.commit()
    
    if room_id is None:
        raise HTTPException(status_code=500, detail="Failed to retrieve or create room ID.")
        
    return {"room_id": room_id}


@router.get("/rooms/{room_id}/messages", response_model=List[dict])
async def get_message_history(
    room_id: int, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth.get_current_user)
):
    # <<< แก้ไข Query ตรงนี้: Join กับ users >>>
    query = sqlalchemy.select(
        chat_messages,
        users.c.email.label('sender_email'),  # ดึง email
        users.c.role.label('sender_role')    # ดึง role
    ).select_from(
        chat_messages.join(users, chat_messages.c.sender_id == users.c.id)
    ).where(chat_messages.c.room_id == room_id).order_by(chat_messages.c.sent_at)
    # -------------------------
    
    result = await db.execute(query)
    return result.mappings().all()




@router.post("/rooms/{room_id}/upload-file")
async def upload_chat_file(
    room_id: int, 
    file: UploadFile = File(...),
    current_user: User = Depends(auth.get_current_user)
):
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')
    
    # 1. สร้าง Blob Name
    new_file_name_raw = f"chat_{room_id}_{timestamp}_{file.filename}"
    blob_name = f"chat_files/{new_file_name_raw}"
    
    # 2. อ่านไฟล์เป็น bytes และอัปโหลดไป Firebase
    file_bytes = await file.read()
    await firebase_storage_client.upload_file_to_firebase(
        file_bytes, 
        blob_name,
        content_type=file.content_type
    )

    # 3. คืนค่า Blob Name เต็ม (Backend/chat-files/ ถูกใช้เป็น Base URL ใน Frontend)
    return {"file_name": blob_name}


@router.post("/rooms/{room_id}/read/{last_message_id}")
async def mark_room_as_read(
    room_id: int,
    last_message_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth.get_current_user)
):
    # FIX: ตรวจสอบว่า last_message_id ไม่เป็น 0 ก่อนที่จะดำเนินการ update
    if last_message_id <= 0:
        return {"message": "Invalid last_message_id", "last_marked_id": 0}
        
    # 1. ดึง ID ข้อความที่ใหญ่ที่สุดในห้อง
    max_message_id = await db.scalar(
        sqlalchemy.select(sqlalchemy.func.max(chat_messages.c.id))
        .where(chat_messages.c.room_id == room_id)
    )
    
    # 2. ใช้ ID ที่ส่งมา หรือ ID ข้อความล่าสุด ถ้า ID ที่ส่งมาใหญ่กว่า
    id_to_mark = min(last_message_id, max_message_id or last_message_id)
    
    # 3. ดำเนินการ Update/Insert (ใช้ on_conflict_do_update ของ PostgreSQL)
    # เราใช้ postgresql.insert เพราะมันทำงานร่วมกับ AsyncSession ได้ดีกว่า
    insert_stmt = postgresql.insert(chat_read_status).values(
        room_id=room_id,
        user_id=current_user.id,
        last_read_message_id=id_to_mark
    )
    # กำหนดเงื่อนไขการชนกัน: ถ้า unique index (room_id, user_id) ชนกัน ให้ทำการอัปเดต
    update_query = insert_stmt.on_conflict_do_update(
        index_elements=['room_id', 'user_id'], # ใช้ unique constraint ที่กำหนดไว้ใน models.py
        set_={'last_read_message_id': id_to_mark}
    )
    
    await db.execute(update_query)
    await db.commit()
    
    return {"message": "Read status updated", "last_marked_id": id_to_mark, "max_id_in_room": max_message_id}

@router.delete("/rooms/{room_id}")
async def delete_chat_room(
    room_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth.get_current_user)
):
    # 1. ตรวจสอบว่าห้องแชทมีอยู่จริง และเป็นห้องแชททั่วไป (job_id is None)
    room_res = await db.execute(sqlalchemy.select(chat_rooms).where(chat_rooms.c.id == room_id))
    room = room_res.mappings().first()
    if not room:
        raise HTTPException(status_code=404, detail="Chat Room not found")

    # 2. ตรวจสอบสิทธิ์ (is_owner/is_employee เหมือนเดิม)
    is_owner = (current_user.role == 'employer' and current_user.id == room.employer_id)
    
    is_employee = False
    if current_user.role == 'employee':
        emp_res = await db.execute(sqlalchemy.select(employees.c.id).where(employees.c.user_id == current_user.id))
        employee_profile = emp_res.mappings().first()
        if employee_profile and employee_profile.id == room.employee_id:
            is_employee = True
            
    if not is_owner and not is_employee:
        raise HTTPException(status_code=403, detail="Not authorized to delete this chat room")
        
    # 3. ดำเนินการลบ
    print(f"INFO: Attempting to delete chat room data for room_id: {room_id}")

    # 🛑 [CRITICAL FIX] ค้นหาและลบไฟล์จริงใน Firebase ก่อนลบข้อความ
    file_query = sqlalchemy.select(chat_messages.c.content).where(
        chat_messages.c.room_id == room_id,
        chat_messages.c.message_type.in_(['image', 'file']) 
    )
    file_results = (await db.execute(file_query)).scalars().all()

    deleted_files_count = 0
    for blob_name in file_results:
        # blob_name ที่ถูกเก็บคือ Blob Name เต็ม (chat_files/filename.jpg)
        try:
            await firebase_storage_client.delete_file_from_firebase(blob_name)
            deleted_files_count += 1
        except Exception as e:
            # ไม่ต้อง raise error เพราะต้องการลบห้องแชทให้สำเร็จ
            print(f"ERROR: Failed to delete file {blob_name} from Firebase: {e}")

    print(f"INFO: Processed {len(file_results)} message records; Deleted {deleted_files_count} physical files.")
    # ------------------------------------------------------------------
    
    # ลบ chat_read_status
    await db.execute(
        sqlalchemy.delete(chat_read_status).where(chat_read_status.c.room_id == room_id)
    )

    # ลบ chat_messages
    await db.execute(
        sqlalchemy.delete(chat_messages).where(chat_messages.c.room_id == room_id)
    )

    # ลบ chat_rooms 
    await db.execute(
        sqlalchemy.delete(chat_rooms).where(chat_rooms.c.id == room_id)
    )

    await db.commit()
    print(f"INFO: Chat room {room_id} deleted successfully and DB committed.")
    
    return {"message": "Chat room deleted successfully"}


@router.get("/rooms/my-unread-count")
async def get_my_unread_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth.get_current_user)
):
    if current_user.role != 'employee':
        raise HTTPException(status_code=403, detail="Only employees can access this endpoint")
        
    # 1. ดึง Employee Profile
    emp_res = await db.execute(sqlalchemy.select(employees.c.id).where(employees.c.user_id == current_user.id))
    employee_profile = emp_res.mappings().first()
    if not employee_profile:
        return {"total_unread": 0}
        
    # 2. ค้นหาห้องแชททั่วไป (Unified Chat)
    room_query = sqlalchemy.select(chat_rooms.c.id).where(
        sqlalchemy.and_(
            chat_rooms.c.employee_id == employee_profile.id,
            chat_rooms.c.job_id.is_(None)
        )
    )
    room_id = await db.scalar(room_query)
    
    if not room_id:
        return {"total_unread": 0}
        
    # 3. ดึง last_read_message_id
    last_read_res = await db.execute(
        sqlalchemy.select(chat_read_status.c.last_read_message_id)
        .where(chat_read_status.c.room_id == room_id, chat_read_status.c.user_id == current_user.id)
    )
    last_read_message_id = last_read_res.scalar_one_or_none() or 0
    
    # 4. นับข้อความที่ยังไม่ได้อ่าน
    unread_count_query = sqlalchemy.select(sqlalchemy.func.count(chat_messages.c.id)).where(
        chat_messages.c.room_id == room_id,
        chat_messages.c.sender_id != current_user.id # ไม่นับข้อความที่ตัวเองส่ง
    )
    if last_read_message_id:
        unread_count_query = unread_count_query.where(chat_messages.c.id > last_read_message_id)
        
    total_unread = await db.scalar(unread_count_query) or 0
        
    return {"total_unread": total_unread}


class NotificationManager:
    """จัดการการเชื่อมต่อ WebSocket ของผู้ใช้แต่ละคน (สำหรับ Bridge/Foreground App)"""
    def __init__(self):
        # Dictionary สำหรับเก็บ WebSocket Connection ของ User แต่ละคน
        # {user_id: [websocket1, websocket2, ...]}
        self.active_user_connections: Dict[int, List[WebSocket]] = {}
        
    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.active_user_connections:
            self.active_user_connections[user_id] = []
        self.active_user_connections[user_id].append(websocket)
        
    def disconnect(self, user_id: int, websocket: WebSocket):
        if user_id in self.active_user_connections:
            self.active_user_connections[user_id].remove(websocket)
            if not self.active_user_connections[user_id]:
                 del self.active_user_connections[user_id] # ลบ key ถ้า List ว่าง

    # ฟังก์ชันนี้ถูกเรียกใช้เมื่อมี Event เกิดขึ้นในระบบ (เช่น สร้างงานใหม่)
    async def send_personal_notification(self, user_id: int, message: dict):
        if user_id in self.active_user_connections:
            for connection in self.active_user_connections[user_id]:
                await connection.send_json(message)
                
notification_manager = NotificationManager()

@router.websocket("/ws/updates/{user_id}")
async def updates_websocket_endpoint(
    websocket: WebSocket,
    user_id: int,
    token: str,
    db: AsyncSession = Depends(get_db)
):
    """Endpoint สำหรับให้ Bridge App เชื่อมต่อ"""
    current_user = None
    
    try:
        # 1. ตรวจสอบ Token และดึง User
        # NOTE: ตรวจสอบให้แน่ใจว่า auth.get_current_user_from_token ทำงานถูกต้อง
        current_user = await auth.get_current_user_from_token(token, db)
        
    except HTTPException as e:
        # [FIX 1] จัดการ HTTPException ที่เกิดจากการตรวจสอบ Token
        # โค้ด 1008 คือ Policy Violation (ใช้สำหรับ Unauthorized/Forbidden ใน WS)
        print(f"ERROR: Token validation failed for WS: {e.detail}")
        await websocket.close(code=1008, reason=f"Invalid token: {e.detail}")
        return

    # 2. ตรวจสอบ User ID (ป้องกันการสวมรอย)
    if current_user.id != user_id:
         print(f"ERROR: Unauthorized access attempt. Token ID {current_user.id} != Path ID {user_id}")
         await websocket.close(code=1008, reason="Unauthorized user ID mismatch")
         return

    # 3. เชื่อมต่อสำเร็จ
    await notification_manager.connect(user_id, websocket)
    print(f"INFO:     Bridge App connected for User ID {user_id}")
    try:
        # [CRITICAL FIX] ใช้ Loop ที่จัดการ Timeout และ Receive พร้อมกัน
        while True:
            # รอกิจกรรมจาก Client เป็นเวลา 25 วินาที
            try:
                # ถ้าไม่ได้รับข้อความใดๆ ภายใน 25 วินาที จะเกิด asyncio.TimeoutError
                # ซึ่งทำให้ loop ทำงานต่อและรักษา Connection alive ได้
                await asyncio.wait_for(
                    websocket.receive_text(), 
                    timeout=25.0 
                )
            except asyncio.TimeoutError:
                pass # ปล่อยให้ Loop ทำงานต่อ (Heartbeat)
            
    except WebSocketDisconnect:
        notification_manager.disconnect(user_id, websocket)
        print(f"INFO:     Bridge App disconnected for User ID {user_id}")
    except Exception as e:
        print(f"ERROR:    Bridge App error for User ID {user_id}: {e}")
        notification_manager.disconnect(user_id, websocket)

# NOTE: Endpoint /ws/{room_id} ของ Chat จะยังคงอยู่และใช้ manager ตัวเดิม
