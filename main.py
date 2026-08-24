import subprocess
import uvicorn
from app.main import app
from app.core.config import settings
from app.core.database import Base, engine

# Run pending Alembic migrations (adds new columns to existing tables)
subprocess.run(["alembic", "upgrade", "head"], check=True)

# Create any new tables not covered by migrations
Base.metadata.create_all(bind=engine)

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
