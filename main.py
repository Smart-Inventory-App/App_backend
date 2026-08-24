import uvicorn
from app.main import app
from app.core.config import settings
from app.core.database import Base, engine

# Create database tables
Base.metadata.create_all(bind=engine)

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
