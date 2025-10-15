import sqlalchemy
from database import metadata

users = sqlalchemy.Table(
    "users", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("email", sqlalchemy.String, unique=True, index=True, nullable=False),
    sqlalchemy.Column("hashed_password", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("role", sqlalchemy.String, nullable=False),
)

comics = sqlalchemy.Table(
    "comics", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("employer_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    sqlalchemy.Column("title", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("synopsis", sqlalchemy.String),
    sqlalchemy.Column("read_link", sqlalchemy.String),
    sqlalchemy.Column("image_file", sqlalchemy.String),
    sqlalchemy.Column("local_folder_path", sqlalchemy.String),
    sqlalchemy.Column("cloud_storage_link", sqlalchemy.String),
    sqlalchemy.Column("last_updated_ep", sqlalchemy.Integer, default=0),
    sqlalchemy.Column("original_latest_ep", sqlalchemy.Integer, default=0),
    sqlalchemy.Column("last_updated_date", sqlalchemy.String),
    sqlalchemy.Column("status", sqlalchemy.String, default='ACTIVE'),
    sqlalchemy.Column("status_change_date", sqlalchemy.String),
    sqlalchemy.Column("update_type", sqlalchemy.String),
    sqlalchemy.Column("update_value", sqlalchemy.String),
    sqlalchemy.Column("pause_start_date", sqlalchemy.String),
    sqlalchemy.Column("pause_end_date", sqlalchemy.String),
    sqlalchemy.Column("start_episode_at", sqlalchemy.Integer, default=1),
)

employees = sqlalchemy.Table(
    "employees", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("employer_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    sqlalchemy.Column("name", sqlalchemy.String, nullable=False, unique=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE")),
)

jobs = sqlalchemy.Table(
    "jobs", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("comic_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("comics.id", ondelete="CASCADE")),
    sqlalchemy.Column("employee_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("employees.id", ondelete="CASCADE")),
    sqlalchemy.Column("episode_number", sqlalchemy.Integer, nullable=False),
    sqlalchemy.Column("task_type", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("rate", sqlalchemy.Float, nullable=False),
    sqlalchemy.Column("status", sqlalchemy.String, nullable=False, default="ASSIGNED"),
    sqlalchemy.Column("assigned_date", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("completed_date", sqlalchemy.String),
    sqlalchemy.Column("employer_work_file", sqlalchemy.String),
    sqlalchemy.Column("employee_finished_file", sqlalchemy.String),
    sqlalchemy.Column("telegram_link", sqlalchemy.String),
    sqlalchemy.Column("payroll_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("payrolls.id"), nullable=True),
    sqlalchemy.Column("is_revision", sqlalchemy.Boolean, default=False, nullable=False),
    sqlalchemy.Column("supplemental_file", sqlalchemy.String),
    sqlalchemy.Column("supplemental_file_comment", sqlalchemy.String),
)

fcm_devices = sqlalchemy.Table(
    "fcm_devices", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    sqlalchemy.Column("device_token", sqlalchemy.String, unique=True, nullable=False),
    sqlalchemy.Column("is_active", sqlalchemy.Boolean, default=True),
)

payrolls = sqlalchemy.Table(
    "payrolls", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("employee_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("employees.id", ondelete="CASCADE")),
    sqlalchemy.Column("payment_date", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("amount_paid", sqlalchemy.Float, nullable=False),
    sqlalchemy.Column("job_ids", sqlalchemy.String, nullable=False),
)

programs = sqlalchemy.Table(
    "programs", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("path", sqlalchemy.String, nullable=False),
)


job_supplemental_files = sqlalchemy.Table(
    "job_supplemental_files", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("job_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True),
    sqlalchemy.Column("file_name", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("comment", sqlalchemy.String),
    sqlalchemy.Column("uploaded_at", sqlalchemy.String, nullable=False),
)


chat_rooms = sqlalchemy.Table(
    "chat_rooms", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("employer_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    sqlalchemy.Column("employee_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
    # job_id สามารถเป็น null ได้ ถ้าเป็นแชททั่วไป
    sqlalchemy.Column("job_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
    sqlalchemy.Column("created_at", sqlalchemy.String, nullable=False),
)

chat_messages = sqlalchemy.Table(
    "chat_messages", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("room_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("chat_rooms.id", ondelete="CASCADE"), nullable=False),
    sqlalchemy.Column("sender_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    sqlalchemy.Column("message_type", sqlalchemy.String, nullable=False, default="text"), # text, image, file
    sqlalchemy.Column("content", sqlalchemy.String, nullable=False), # ถ้าเป็น text ก็คือข้อความ, ถ้าเป็น file ก็คือ file_name
    sqlalchemy.Column("sent_at", sqlalchemy.String, nullable=False),
)

chat_read_status = sqlalchemy.Table(
    "chat_read_status", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("room_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("chat_rooms.id", ondelete="CASCADE"), nullable=False),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    sqlalchemy.Column("last_read_message_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("chat_messages.id", ondelete="SET NULL")),
    sqlalchemy.UniqueConstraint('room_id', 'user_id', name='uq_room_user_read_status')
)


