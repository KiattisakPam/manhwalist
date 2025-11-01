# backend/schemas.py (ฉบับเต็มที่แก้ไขแล้ว)

from pydantic import BaseModel, EmailStr
from typing import Optional, List
import datetime

# --- Pydantic Models ---
class User(BaseModel):
    id: int
    email: EmailStr
    role: str

class UserCreate(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    user: User

class TokenData(BaseModel):
    email: Optional[EmailStr] = None

class EpisodeStatus(BaseModel):
    episode_number: int
    status: str
    job_id: Optional[int] = None
    employee_name: Optional[str] = None
    finished_file_url: Optional[str] = None
    task_type: Optional[str] = None # <<< เพิ่มบรรทัดนี้ที่ขาดไป

class ComicBase(BaseModel):
    title: str
    synopsis: Optional[str] = None
    read_link: Optional[str] = None
    image_file: Optional[str] = None
    local_folder_path: Optional[str] = None
    cloud_storage_link: Optional[str] = None
    last_updated_ep: int = 0
    original_latest_ep: int = 0
    start_episode_at: int = 1
    status: str = 'ACTIVE'
    update_type: Optional[str] = None
    update_value: Optional[str] = None
    pause_start_date: Optional[str] = None
    pause_end_date: Optional[str] = None

class ComicCreate(ComicBase):
    pass

class ComicUpdate(BaseModel):
    title: Optional[str] = None
    synopsis: Optional[str] = None
    read_link: Optional[str] = None
    image_file: Optional[str] = None
    local_folder_path: Optional[str] = None
    cloud_storage_link: Optional[str] = None
    last_updated_ep: Optional[int] = None
    original_latest_ep: Optional[int] = None
    start_episode_at: Optional[int] = None
    status: Optional[str] = None
    update_type: Optional[str] = None
    update_value: Optional[str] = None
    pause_start_date: Optional[str] = None
    pause_end_date: Optional[str] = None

class ComicWithCompletion(ComicBase):
    id: int
    last_updated_date: str
    status_change_date: str
    latest_employee_completed_ep: Optional[int] = None

# --- เพิ่ม Model ของ Job ที่ขาดไป ---
class JobBase(BaseModel):
    id: int
    comic_id: int
    employee_id: int
    episode_number: int
    task_type: str
    rate: float
    status: str
    assigned_date: datetime.datetime
    completed_date: Optional[datetime.datetime] = None
    employer_work_file: Optional[str] = None
    employee_finished_file: Optional[str] = None
    telegram_link: Optional[str] = None
    
class JobWithComicInfo(JobBase):
    employee_name: str
    comic_title: str
    comic_image_file: Optional[str] = None
# -----------------------------------

class PayrollCreate(BaseModel):
    employee_id: int
    job_ids: List[int]

class Program(BaseModel):
    id: int | None = None
    name: str
    path: str
        
class JobSupplementalFile(BaseModel):
    id: int
    job_id: int
    file_name: str
    comment: Optional[str] = None
    uploaded_at: str

# --- เพิ่ม Model ใหม่สำหรับแชท ---
class ChatRoomCreate(BaseModel):
    participant_employee_id: int
    job_id: Optional[int] = None
    
    
class ChatMessage(BaseModel):
    id: int
    room_id: int
    sender_id: int
    message_type: str
    content: str
    sent_at: str

class ChatRoomInfo(BaseModel):
    id: int
    participant_name: str
    participant_role: str
    job_id: Optional[int] = None 
    job_context: Optional[str] = None # <<< เพิ่ม job_context
    last_message: Optional[str] = None
    last_message_time: Optional[str] = None
    unread_count: int = 0

class ChatRoomListResponse(BaseModel):
    total_unread_count: int
    rooms: List[ChatRoomInfo]
    
class EmployeeUpdate(BaseModel):
    name: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    
class EmployerUpdate(BaseModel):
    telegram_report_chat_id: Optional[str] = None