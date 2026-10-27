import uvicorn
from app.main import app
from app.core.config import settings
from app.core.database import Base, engine
from app.core.schema_guard import ensure_columns

# Create database tables
Base.metadata.create_all(bind=engine)
# Una base anterior a un cambio de esquema no tiene las columnas nuevas: se agregan si faltan
ensure_columns(engine)

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
