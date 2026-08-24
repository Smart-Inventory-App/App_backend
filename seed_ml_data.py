"""
Seed de datos de consumo para entrenar el modelo ML.
Crea 6 productos ficticios con 60 dias de historial de consumo (12 eventos c/u).
Uso: python seed_ml_data.py
"""
import random
from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal
from app.models.consumption import ConsumptionEvent
from app.models.product import Product

SEED_USER_ID = "seed-ml-user-001"

PRODUCTS = [
    {"nombre": "Leche entera 1L",      "categoria": "Lácteos",    "stock": 20},
    {"nombre": "Arroz largo fino 1kg",  "categoria": "Almacén",    "stock": 15},
    {"nombre": "Aceite de girasol 1L",  "categoria": "Almacén",    "stock": 10},
    {"nombre": "Fideos spaghetti 500g", "categoria": "Almacén",    "stock": 25},
    {"nombre": "Jabón de mano liquido", "categoria": "Limpieza",   "stock": 12},
    {"nombre": "Papel higiénico x4",    "categoria": "Limpieza",   "stock": 8},
]

def main():
    db = SessionLocal()
    try:
        # Crear productos si no existen
        product_ids = []
        for p in PRODUCTS:
            existing = db.query(Product).filter(
                Product.user_id == SEED_USER_ID,
                Product.nombre == p["nombre"],
            ).first()
            if not existing:
                prod = Product(user_id=SEED_USER_ID, **p, vencimiento=None)
                db.add(prod)
                db.flush()
                product_ids.append(prod.id)
                print(f"  Creado producto: {p['nombre']} (id={prod.id})")
            else:
                product_ids.append(existing.id)
                print(f"  Producto existente: {p['nombre']} (id={existing.id})")

        db.commit()

        # Insertar eventos de consumo: 12 eventos por producto en 60 dias
        now = datetime.now(timezone.utc)
        events_added = 0
        for pid in product_ids:
            # Verificar si ya tiene eventos suficientes
            existing_count = db.query(ConsumptionEvent).filter(
                ConsumptionEvent.product_id == pid
            ).count()
            if existing_count >= 12:
                print(f"  Producto {pid}: ya tiene {existing_count} eventos, skip")
                continue

            for i in range(12):
                days_ago = 60 - (i * 5) + random.randint(-1, 1)
                qty = random.randint(1, 4)
                event = ConsumptionEvent(
                    product_id=pid,
                    user_id=SEED_USER_ID,
                    quantity=qty,
                    event_type="consumed",
                    consumed_at=now - timedelta(days=days_ago),
                )
                db.add(event)
                events_added += 1

        db.commit()
        print(f"\nSeed completado: {len(product_ids)} productos, {events_added} eventos nuevos.")
        print("Ya podés entrenar el modelo desde el BackOffice.")

    finally:
        db.close()


if __name__ == "__main__":
    main()
