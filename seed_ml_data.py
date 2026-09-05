"""
Seed de datos de consumo para entrenar el modelo ML.
Crea 6 productos ficticios con 12 eventos cada uno separados por 6 dias (span ~66 dias >= 56 requerido).
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
        # Limpiar eventos existentes del seed user para re-insertar con span correcto
        existing_products = db.query(Product).filter(
            Product.user_id == SEED_USER_ID
        ).all()
        if existing_products:
            pids = [p.id for p in existing_products]
            deleted = db.query(ConsumptionEvent).filter(
                ConsumptionEvent.product_id.in_(pids)
            ).delete(synchronize_session=False)
            db.commit()
            print(f"  Limpiados {deleted} eventos existentes del seed.")

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

        # Insertar eventos: 12 por producto, intervalo 6 dias => span = 66 dias (>= 56 requerido)
        now = datetime.now(timezone.utc)
        events_added = 0
        for pid in product_ids:
            for i in range(12):
                # i=0 -> 66 dias atras (mas viejo), i=11 -> ~0 dias atras (mas nuevo)
                # Jitter solo en eventos intermedios para no afectar el span minimo
                jitter = random.randint(-1, 1) if 0 < i < 11 else 0
                days_ago = 66 - (i * 6) + jitter
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
        print("Span por producto: ~66 dias (minimo requerido: 56 dias). Todos deberan calificar.")
        print("Ya podes entrenar el modelo desde el BackOffice.")

    finally:
        db.close()


if __name__ == "__main__":
    main()
