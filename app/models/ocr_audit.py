from sqlalchemy import Column, DateTime, Float, Integer, String, func

from app.core.database import Base


class OCRScanAudit(Base):
    """Un renglón por cada ejecución del módulo de OCR.

    Tabla compartida con el backoffice (`ocr_scan_audit`, que la crea ese
    servicio): es de donde el panel de OCR saca el uso, los tiempos y la
    confianza. La foto no se guarda en ningún lado, así que sin este renglón
    los escaneos de la app no dejarían rastro y el panel sólo vería los que se
    hacen desde el propio backoffice.

    Guarda lo mínimo: ni la imagen ni el texto completo, sólo un recorte para
    reconocer de qué escaneo se trata.
    """
    __tablename__ = "ocr_scan_audit"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, unique=True, nullable=True, index=True)
    user_id = Column(String, index=True, nullable=True)
    user_email = Column(String, index=True, nullable=False)
    origen = Column(String, nullable=False)
    doc_type = Column(String, nullable=False, index=True)
    engine = Column(String, nullable=True)
    status = Column(String, nullable=False)
    confianza = Column(Float, nullable=True)
    processing_ms = Column(Integer, nullable=True)
    campos = Column(Integer, nullable=True)
    resumen = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
