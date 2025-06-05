import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from dotenv import load_dotenv

if not os.getenv("GOOGLE_CLOUD_PROJECT"):
    load_dotenv()


def get_database_url():
    if os.getenv("GOOGLE_CLOUD_PROJECT"):
        # Production: Cloud SQL
        db_user = os.getenv("DB_USER")
        db_pass = os.getenv("DB_PASS")
        db_name = os.getenv("DB_NAME")
        connection_name = os.getenv("CLOUD_SQL_CONNECTION_NAME")
        
        return f"postgresql+asyncpg://{db_user}:{db_pass}@/{db_name}?host=/cloudsql/{connection_name}"
    else:
        # Development: local PostgreSQL
        return os.getenv("DATABASE_URL")

DATABASE_URL = get_database_url()

if DATABASE_URL is None:
    raise ValueError("Database configuration missing")

engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except:
            await session.rollback()
            raise
        finally:
            await session.close()