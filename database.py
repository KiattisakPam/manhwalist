# database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import sqlalchemy
from config import settings

# --- Database Connection ---
db_url = settings.DATABASE_URL
if db_url.startswith("sqlite"):
    db_url = db_url.replace("sqlite:///", "sqlite+aiosqlite:///")
elif db_url.startswith("postgres"):
    db_url = db_url.replace("postgres://", "postgresql+asyncpg://")

engine = create_async_engine(db_url, connect_args={"check_same_thread": False} if "sqlite" in db_url else {})
metadata = sqlalchemy.MetaData()

# --- Dependency ---
async def get_db() -> AsyncSession:
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        
        