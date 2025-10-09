import sqlalchemy
from database import metadata

# --- SQLAlchemy Table Definitions ---
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
    # --- เพิ่มบรรทัดนี้ ---
    sqlalchemy.Column("is_revision", sqlalchemy.Boolean, default=False, nullable=False),
)


# --- เพิ่มตารางนี้เข้าไป ---
fcm_devices = sqlalchemy.Table(
    "fcm_devices", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    sqlalchemy.Column("device_token", sqlalchemy.String, unique=True, nullable=False),
    sqlalchemy.Column("is_active", sqlalchemy.Boolean, default=True),
)
# -------------------------

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

