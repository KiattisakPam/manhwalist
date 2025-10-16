from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
import sqlalchemy
import datetime
import os
import shutil
from typing import List, Dict, Optional

from database import get_db
from models import users, employees, chat_rooms, chat_messages, jobs, comics, chat_read_status
from schemas import User, ChatRoomInfo, ChatRoomCreate, ChatRoomListResponse
import auth

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
    print(f"INFO:     Client {current_user.email} connected to room {room_id}") # DEBUG: เพิ่ม log การเชื่อมต่อ

    try:
        while True:
            data = await websocket.receive_json()
            print(f"DEBUG:    Received data from {current_user.email}: {data}") # DEBUG: แสดงข้อมูลที่ได้รับ

            message_type = data.get("type", "text")

            if message_type == 'delete':
                message_id = data.get("message_id")
                if message_id:
                    # <<< แก้ไข: ตรวจสอบความเป็นเจ้าของและ room_id ของข้อความ >>>
                    msg_res = await db.execute(sqlalchemy.select(chat_messages.c.sender_id, chat_messages.c.room_id).where(chat_messages.c.id == message_id))
                    msg_info = msg_res.one_or_none()
                
                    # ตรวจสอบว่าข้อความมีอยู่, ผู้ใช้ปัจจุบันเป็นเจ้าของ, และข้อความนั้นอยู่ในห้องนี้จริง
                    if msg_info and msg_info.sender_id == current_user.id and msg_info.room_id == room_id:
                        await db.execute(sqlalchemy.delete(chat_messages).where(chat_messages.c.id == message_id))
                        await db.commit()
                        await manager.broadcast(room_id, {"type": "delete", "message_id": message_id})
                    # ------------------------------------------
                continue 

            # --- ส่วนที่แก้ไข ---
            # ใช้ .get() เพื่อป้องกัน KeyError ถ้าหาก frontend ไม่ได้ส่ง 'content' มา
            content = data.get("content") 
            if content is None:
                print(f"WARNING:  Received message with no 'content' from {current_user.email}. Data: {data}")
                continue # ข้ามไปรอรับข้อความถัดไป ไม่ให้โปรแกรมแครช
            # --------------------

            now = datetime.datetime.now().isoformat()

            insert_query = sqlalchemy.insert(chat_messages).values(
                room_id=room_id,
                sender_id=current_user.id,
                message_type=message_type,
                content=content,
                sent_at=now
            )
            result = await db.execute(insert_query)
            await db.commit()

            new_message_id = result.inserted_primary_key[0]
            print(f"INFO:     Message {new_message_id} from {current_user.email} saved to DB.") # DEBUG

            new_message = {
                "id": new_message_id,
                "room_id": room_id, "sender_id": current_user.id,
                "message_type": message_type, "content": content, "sent_at": now,
                "sender_email": current_user_email, 
                "sender_role": current_user_role,
            }

            await manager.broadcast(room_id, new_message)
            print(f"INFO:     Broadcasting message {new_message_id} to room {room_id}") # DEBUG

    except WebSocketDisconnect:
        manager.disconnect(room_id, websocket)
        print(f"INFO:     Client {current_user.email} disconnected from room {room_id}")
    except Exception as e:
        # เพิ่มการดักจับ Error ทั่วไป เพื่อดูว่ามีปัญหาอะไรเกิดขึ้น
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
        now = datetime.datetime.now().isoformat()
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
                sent_at=datetime.datetime.now().isoformat()
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
        now = datetime.datetime.now().isoformat()
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
                sent_at=datetime.datetime.now().isoformat()
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
    current_user: User = Depends(auth.get_current_user) # <<< เพิ่ม
):
    os.makedirs("chat_files", exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    file_name = f"chat_{room_id}_{timestamp}_{file.filename}"
    file_path = os.path.join("chat_files", file_name)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    return {"file_name": file_name}

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
    
    # 3. ดำเนินการ Update/Insert
    update_query = sqlalchemy.dialects.sqlite.insert(chat_read_status).values(
        room_id=room_id,
        user_id=current_user.id,
        last_read_message_id=id_to_mark
    )
    update_query = update_query.on_conflict_do_update(
        index_elements=['room_id', 'user_id'],
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

    # <<< FIX 1: ค้นหาและลบไฟล์จริงก่อนลบข้อความ >>>
    file_query = sqlalchemy.select(chat_messages.c.content).where(
        chat_messages.c.room_id == room_id,
        chat_messages.c.message_type.in_(['image', 'file']) 
    )
    file_results = (await db.execute(file_query)).scalars().all()

    deleted_files_count = 0
    for file_name in file_results:
        # file_name ใน content จะเป็นชื่อไฟล์โดยตรง
        file_path = os.path.join("chat_files", file_name)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                deleted_files_count += 1
            except Exception as e:
                print(f"ERROR: Failed to delete file {file_path}: {e}")

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
