# database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import sqlalchemy
from config import settings

# --- Database Connection ---
db_url = settings.DATABASE_URL
if db_url.startswith("sqlite"):
    db_url = db_url.replace("sqlite:///", "sqlite+aiosqlite:///")

# *** แก้ไข Logic ตรงนี้ ***
if db_url.startswith("postgres"):
    # บังคับใช้ postgresql+asyncpg:// สำหรับ URI ที่ขึ้นต้นด้วย postgres หรือ postgresql
    if not db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://")
# *** สิ้นสุดการแก้ไข ***



engine = create_async_engine(db_url, connect_args={"check_same_thread": False} if "sqlite" in db_url else {})
metadata = sqlalchemy.MetaData()

# --- Dependency ---
async def get_db() -> AsyncSession:
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    AsyncSessionLocal = async_session
    async with async_session() as session:
        yield session
        
        