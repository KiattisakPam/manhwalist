from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import datetime
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession
import sqlalchemy

from database import engine, metadata
from models import users
from auth import get_password_hash
from routers import (
    users as usersRouter, 
    comics as comicsRouter, 
    jobs as jobsRouter,
    employees as employeesRouter,
    programs as programsRouter,
    files as filesRouter,
    notifications as notificationsRouter,
    settings as settingsRouter
)

app = FastAPI(title="Comic Secretary API")

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Include Routers ---
app.include_router(usersRouter.router)
app.include_router(comicsRouter.router)
app.include_router(jobsRouter.router)
app.include_router(employeesRouter.router)
app.include_router(programsRouter.router)
app.include_router(filesRouter.router)
app.include_router(notificationsRouter.router)
app.include_router(settingsRouter.router)

# --- Event Handlers ---
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all, checkfirst=True)
    
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        query = sqlalchemy.select(users).where(users.c.email == "employer@example.com")
        result = await session.execute(query)
        if result.mappings().first() is None:
            hashed_password = get_password_hash("password123")
            insert_query = sqlalchemy.insert(users).values(
                email="employer@example.com",
                hashed_password=hashed_password,
                role="employer"
            )
            await session.execute(insert_query)
            await session.commit()
            print("="*50)
            print("Default employer created: employer@example.com / password123")
            print("="*50)

@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Welcome to the Comic Secretary API"}


