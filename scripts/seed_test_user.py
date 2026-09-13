"""
Script para crear un usuario ficticio de prueba con productos e historial de
consumo, diseñado para ejercitar las tres etapas del predictor ML
(bayesian / moving_average / gbm) y disparar las alertas inteligentes.

Uso:
    python3 scripts/seed_test_user.py [--auth-url URL] [--app-url URL]

Crea usuario y productos vía API, y genera un .sql con los eventos de consumo
backdateados (el endpoint POST /products/{id}/events siempre timestampea con
now(), así que el historial no se puede cargar por HTTP).
"""
import argparse
import sys
from datetime import date, datetime, timedelta, timezone

import requests

AUTH_URL_DEFAULT = "http://localhost:8001"
APP_URL_DEFAULT = "http://localhost:8000"
SQL_OUT_DEFAULT = "seed_consumption_events.sql"

USER_EMAIL = "test.alertas@smartinventory.com"
USER_PASSWORD = "TestAlertas1"

PROFILE = {
    "firstName": "Usuario",
    "lastName": "Prueba",
    "username": "test_alertas",
    "coverageDaysThreshold": 14,
    "expiryDaysThreshold": 30,
    "alertCheckHour": 9,
}

# El predictor elige etapa según cantidad de eventos y días de historia
# (ML/app/predictor/stage.py): <10 eventos o <28 días -> bayesian;
# >=56 días -> gbm; en el medio -> moving_average.
#
# Para las etapas bayesian y moving_average la tasa es determinística:
#   moving_average -> qty / every_days
#   bayesian       -> (1 + total_unidades) / (7 + cantidad_eventos)
# Para gbm la predice el modelo entrenado, así que el resultado depende
# de la versión activa en el BackOffice.
PRODUCTS = [
    {
        "nombre": "Leche Entera", "marca": "La Serenísima", "categoria": "Lácteos",
        "stock": 3, "stock_minimo": 10,
        "descripcion": "Consumo diario alto, stock bajo",
        "events": {"qty": 1, "every_days": 1, "count": 60},  # gbm
    },
    {
        "nombre": "Yogur Natural", "marca": "Danone", "categoria": "Lácteos",
        "stock": 10, "stock_minimo": 8, "vencimiento_en_dias": 10,
        "descripcion": "Consumo lento con vencimiento cercano",
        "events": {"qty": 1, "every_days": 5, "count": 13},  # gbm
    },
    {
        "nombre": "Arroz Largo", "marca": "Gallo", "categoria": "Cereales",
        "stock": 50, "stock_minimo": 10,
        "descripcion": "Consumo moderado, stock holgado",
        "events": {"qty": 2, "every_days": 6, "count": 10},  # moving_average ~0.33/día
    },
    {
        "nombre": "Detergente", "marca": "Magistral", "categoria": "Limpieza",
        "stock": 5, "stock_minimo": 20,
        "descripcion": "Consumo medio, stock por agotarse",
        "events": {"qty": 1, "every_days": 2, "count": 16},  # moving_average 0.5/día
    },
    {
        "nombre": "Fideos Spaghetti", "marca": "Matarazzo", "categoria": "Pastas",
        "stock": 5, "stock_minimo": 10,
        "descripcion": "Justo por encima del umbral — no debe alertar",
        "events": {"qty": 1, "every_days": 4, "count": 10},  # moving_average 0.25/día
    },
    {
        "nombre": "Aceite Girasol", "marca": "Natura", "categoria": "Aceites",
        "stock": 200, "stock_minimo": 10,
        "descripcion": "Pocos eventos — cae al prior bayesiano",
        "events": {"qty": 1, "every_days": 10, "count": 7},  # bayesian
    },
    {
        "nombre": "Café Molido", "marca": "La Virginia", "categoria": "Infusiones",
        "stock": 2, "stock_minimo": 5,
        "descripcion": "Historial mínimo, stock crítico",
        "events": {"qty": 1, "every_days": 3, "count": 3},  # bayesian
    },
]


def register(auth_url: str) -> None:
    r = requests.post(f"{auth_url}/auth/register",
                      json={"email": USER_EMAIL, "password": USER_PASSWORD})
    if r.status_code == 201:
        print(f"✓ Usuario registrado: {USER_EMAIL}")
    elif r.status_code == 400 and "already_registered" in r.text:
        print("→ Usuario ya existe, continuando...")
    else:
        print(f"✗ Error al registrar: {r.status_code} {r.text}")
        sys.exit(1)


def login(auth_url: str) -> str:
    r = requests.post(f"{auth_url}/auth/login",
                      json={"email": USER_EMAIL, "password": USER_PASSWORD})
    if r.status_code != 200:
        print(f"✗ Error al loguear: {r.status_code} {r.text}")
        sys.exit(1)
    print("✓ Login OK")
    return r.json()["access_token"]


def put_profile(app_url: str, headers: dict) -> str:
    r = requests.put(f"{app_url}/profile/", json=PROFILE, headers=headers)
    if r.status_code not in (200, 204):
        print(f"✗ Error al actualizar perfil: {r.status_code} {r.text}")
        sys.exit(1)
    print(f"✓ Perfil actualizado (cobertura={PROFILE['coverageDaysThreshold']}d, "
          f"vencimiento={PROFILE['expiryDaysThreshold']}d)")
    return r.json()["sub"]


def create_products(app_url: str, headers: dict) -> list[tuple[int, dict]]:
    created = []
    for p in PRODUCTS:
        payload = {k: v for k, v in p.items() if k not in ("events", "vencimiento_en_dias")}
        if "vencimiento_en_dias" in p:
            payload["vencimiento"] = (date.today() + timedelta(days=p["vencimiento_en_dias"])).isoformat()

        r = requests.post(f"{app_url}/products/", json=payload, headers=headers)
        if r.status_code != 201:
            print(f"  ✗ {p['nombre']}: {r.status_code} {r.text}")
            continue
        pid = r.json()["id"]
        created.append((pid, p))
        ev = p["events"]
        print(f"  ✓ [{pid}] {p['nombre']} — stock={p['stock']}, "
              f"{ev['count']} eventos c/{ev['every_days']}d")
    return created


def build_events_sql(created: list[tuple[int, dict]], user_id: str) -> str:
    now = datetime.now(timezone.utc)
    rows = []
    for pid, p in created:
        ev = p["events"]
        for i in range(ev["count"]):
            days_ago = (ev["count"] - 1 - i) * ev["every_days"]
            ts = (now - timedelta(days=days_ago)).isoformat()
            rows.append(f"  ({pid}, '{user_id}', {ev['qty']}, 'consumed', '{ts}')")

    ids = ", ".join(str(pid) for pid, _ in created)
    return (
        "BEGIN;\n\n"
        f"DELETE FROM consumption_events WHERE product_id IN ({ids});\n\n"
        "INSERT INTO consumption_events "
        "(product_id, user_id, quantity, event_type, consumed_at) VALUES\n"
        + ",\n".join(rows)
        + ";\n\nCOMMIT;\n"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--auth-url", default=AUTH_URL_DEFAULT)
    parser.add_argument("--app-url", default=APP_URL_DEFAULT)
    parser.add_argument("--sql-out", default=SQL_OUT_DEFAULT)
    args = parser.parse_args()

    print(f"\nAuth: {args.auth_url}\nApp:  {args.app_url}\n")

    register(args.auth_url)
    token = login(args.auth_url)
    headers = {"Authorization": f"Bearer {token}"}
    user_id = put_profile(args.app_url, headers)

    print(f"\nCreando {len(PRODUCTS)} productos...")
    created = create_products(args.app_url, headers)
    if not created:
        print("✗ No se creó ningún producto, abortando.")
        sys.exit(1)

    with open(args.sql_out, "w") as f:
        f.write(build_events_sql(created, user_id))

    total = sum(p["events"]["count"] for _, p in created)
    print(f"\n✓ {args.sql_out} — {total} eventos de consumo para {len(created)} productos")
    print("\nCargalos en la base (el endpoint HTTP no permite fechas pasadas):")
    print(f"  psql \"$DATABASE_URL\" -f {args.sql_out}")
    print("\nDespués, 'Lanzar a todos' en el BackOffice → ML.")
    print(f"\nUsuario: {USER_EMAIL} / {USER_PASSWORD}\n")


if __name__ == "__main__":
    main()
