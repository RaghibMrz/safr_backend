import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from dotenv import load_dotenv

if not os.getenv("GOOGLE_CLOUD_PROJECT"):
    load_dotenv()

def get_database_url():
    if os.getenv("GOOGLE_CLOUD_PROJECT"):
        db_user = os.getenv("DB_USER")
        db_pass = os.getenv("DB_PASS") 
        db_name = os.getenv("DB_NAME")
        connection_name = os.getenv("CLOUD_SQL_CONNECTION_NAME")
        
        return f"postgresql+asyncpg://{db_user}:{db_pass}@/{db_name}?host=/cloudsql/{connection_name}"
    else:
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            if database_url.startswith("postgresql://"):
                database_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
            return database_url
        else:
            db_user = os.getenv("DB_USER", "postgres")
            db_pass = os.getenv("DB_PASS", "MeinYahanSafrKarKeAayiHoon")
            db_name = os.getenv("DB_NAME", "safr")
            db_host = os.getenv("DB_HOST", "127.0.0.1")
            db_port = os.getenv("DB_PORT", "5432")
            
            return f"postgresql+asyncpg://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"

DATABASE_URL = get_database_url()

if DATABASE_URL is None:
    raise ValueError("Database configuration missing")

print(f"Using database: {DATABASE_URL.split('@')[0]}@{DATABASE_URL.split('@')[1].split('?')[0] if '@' in DATABASE_URL else DATABASE_URL}")

engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = async_sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)

Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()