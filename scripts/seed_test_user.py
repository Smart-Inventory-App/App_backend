"""
Script para crear un usuario ficticio de prueba con productos
diseñados para disparar las alertas inteligentes del ML.

Uso:
    python scripts/seed_test_user.py [--auth-url URL] [--app-url URL]

Por defecto apunta a los servicios locales en Docker.
"""
import argparse
import requests
import sys
import time

AUTH_URL_DEFAULT = "http://localhost:8001"
APP_URL_DEFAULT  = "http://localhost:8000"

USER_EMAIL    = "test.alertas@smartinventory.com"
USER_PASSWORD = "TestAlertas1"

# Perfil del usuario de prueba
PROFILE_PATCH = {
    "firstName": "Usuario",
    "lastName": "Prueba",
    "username": "test_alertas",
    "coverageDaysThreshold": 14,
    "expiryDaysThreshold": 30,
    "alertCheckHour": 9,
}

# Productos diseñados para cubrir distintos escenarios de alerta
PRODUCTS = [
    # Stock crítico — debería disparar alerta de stockout inminente
    {"nombre": "Leche Entera", "marca": "La Serenísima", "categoria": "Lácteos",
     "stock": 2, "stock_minimo": 10, "descripcion": "Stock crítico para probar alerta baja"},

    # Stock normal — no debería disparar alerta
    {"nombre": "Arroz Largo", "marca": "Gallo", "categoria": "Cereales",
     "stock": 50, "stock_minimo": 10, "descripcion": "Stock normal sin alerta"},

    # Exceso de stock — debería disparar alerta de sobrestock
    {"nombre": "Aceite Girasol", "marca": "Natura", "categoria": "Aceites",
     "stock": 200, "stock_minimo": 10, "descripcion": "Sobrestock para probar alerta overstock"},

    # Vencimiento próximo + stock bajo
    {"nombre": "Yogur Natural", "marca": "Danone", "categoria": "Lácteos",
     "stock": 3, "stock_minimo": 8, "vencimiento": "2026-09-20",
     "descripcion": "Stock bajo + vencimiento próximo"},

    # Stock en el límite exacto del umbral
    {"nombre": "Fideos Spaghetti", "marca": "Matarazzo", "categoria": "Pastas",
     "stock": 14, "stock_minimo": 10, "descripcion": "Stock en límite del umbral"},

    # Producto para simular restock (compraste de menos)
    {"nombre": "Detergente", "marca": "Magistral", "categoria": "Limpieza",
     "stock": 5, "stock_minimo": 20, "descripcion": "Para probar alerta de compraste de menos"},
]


def register(auth_url: str) -> None:
    r = requests.post(f"{auth_url}/auth/register",
                      json={"email": USER_EMAIL, "password": USER_PASSWORD})
    if r.status_code == 201:
        print(f"✓ Usuario registrado: {USER_EMAIL}")
    elif r.status_code == 400 and "already_registered" in r.text:
        print(f"→ Usuario ya existe, continuando...")
    else:
        print(f"✗ Error al registrar: {r.status_code} {r.text}")
        sys.exit(1)


def login(auth_url: str) -> str:
    r = requests.post(f"{auth_url}/auth/login",
                      json={"email": USER_EMAIL, "password": USER_PASSWORD})
    if r.status_code != 200:
        print(f"✗ Error al loguear: {r.status_code} {r.text}")
        sys.exit(1)
    token = r.json()["access_token"]
    print(f"✓ Login OK")
    return token


def patch_profile(app_url: str, token: str) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.put(f"{app_url}/profile/", json=PROFILE_PATCH, headers=headers)
    if r.status_code in (200, 204):
        print(f"✓ Perfil actualizado (coverage_days={PROFILE_PATCH['coverageDaysThreshold']})")
    else:
        print(f"✗ Error al actualizar perfil: {r.status_code} {r.text}")


def create_products(app_url: str, token: str) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    for p in PRODUCTS:
        r = requests.post(f"{app_url}/products/", json=p, headers=headers)
        if r.status_code == 201:
            pid = r.json().get("id", "?")
            print(f"  ✓ [{pid}] {p['nombre']} — stock={p['stock']}, stock_minimo={p.get('stock_minimo','—')}")
        else:
            print(f"  ✗ Error creando {p['nombre']}: {r.status_code} {r.text}")


def trigger_alerts(app_url: str) -> None:
    # Usa el endpoint interno de BackOffice que dispara alertas para todos
    # Si tenés el BackOffice corriendo, podés llamarlo directamente
    print("\n→ Para disparar las alertas manualmente desde BackOffice:")
    print(f"   POST /admin/alerts/run  (dispara a todos los usuarios)")
    print(f"   O desde la página de Machine Learning en el BackOffice")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--auth-url", default=AUTH_URL_DEFAULT)
    parser.add_argument("--app-url",  default=APP_URL_DEFAULT)
    args = parser.parse_args()

    print(f"\n{'='*50}")
    print(f"Seed usuario de prueba")
    print(f"Auth: {args.auth_url}")
    print(f"App:  {args.app_url}")
    print(f"{'='*50}\n")

    register(args.auth_url)
    token = login(args.auth_url)
    patch_profile(args.app_url, token)

    print(f"\nCreando {len(PRODUCTS)} productos...")
    create_products(args.app_url, token)

    trigger_alerts(args.app_url)

    print(f"\n{'='*50}")
    print(f"✓ Listo. Usuario de prueba:")
    print(f"  Email:    {USER_EMAIL}")
    print(f"  Password: {USER_PASSWORD}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
