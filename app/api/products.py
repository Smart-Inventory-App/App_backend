from datetime import date
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Literal, Optional

from app.models.alert import Alert
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.activity_log import AdminActivityLog
from app.models.consumption import ConsumptionEvent
from app.models.product import Product
from app.models.profile import DEFAULT_COVERAGE_DAYS, DEFAULT_DIAS_ALERTA_VENCIMIENTO, DEFAULT_OVERSTOCK_DAYS, UserProfile
from app.models.user import AuthUser
from app.schemas.product import (
    ProductCreate,
    ProductDefaults,
    ProductResponse,
    ProductSuggestion,
    ProductUpdate,
)
from app.services.notifications import NotificationService


class EventRequest(BaseModel):
    event_type: Literal["consumed", "expired"]
    quantity: int


class EventCorrection(BaseModel):
    event_type: Literal["consumed", "expired", "restocked"]
    quantity: int


def _stock_effect(event_type: str, quantity: int) -> int:
    return quantity if event_type == "restocked" else -quantity

router = APIRouter(prefix="/products", tags=["products"])

notification_service = NotificationService(api_url=settings.NOTIFICATION_SERVICE_URL)

def _get_user_product(product_id: int, user_id: str, db: Session) -> Product:
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.user_id == user_id,
    ).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado")
    return product


def _get_or_create_profile(user_id: str, db: Session) -> UserProfile:
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if not profile:
        profile = UserProfile(user_id=user_id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def _find_matching_product(
    user_id: str, nombre: str, marca: Optional[str], vencimiento, db: Session
) -> Optional[Product]:
    query = db.query(Product).filter(
        Product.user_id == user_id,
        func.lower(func.trim(Product.nombre)) == nombre.strip().lower(),
    )
    if vencimiento is None:
        query = query.filter(Product.vencimiento.is_(None))
    else:
        query = query.filter(Product.vencimiento == vencimiento)
    marca_norm = marca.strip().lower() if marca else None
    if marca_norm is None:
        query = query.filter(Product.marca.is_(None))
    else:
        query = query.filter(func.lower(func.trim(Product.marca)) == marca_norm)
    return query.first()

def _log_activity(
    db: Session,
    event_type: str,
    actor_email: Optional[str],
    target_user_id: str,
    target_email: Optional[str],
    description: str,
) -> None:
    db.add(
        AdminActivityLog(
            event_type=event_type,
            actor_email=actor_email,
            target_user_id=target_user_id,
            target_email=target_email,
            description=description,
        )
    )
    db.commit()


def _get_user(user_id: int, db: Session) -> AuthUser:
    user = db.query(AuthUser).filter(
        AuthUser.id == user_id
    ).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    return user

def _create_alert(product: Product, alert_type: str, alert_level: str, db: Session) -> None:
    alert = Alert(
        user_id=UUID(product.user_id),
        product_id=product.id,
        type=alert_type,
        level=alert_level,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    print(f"\n\nSe creó alerta de tipo '{alert_type}' y nivel '{alert_level}' para el producto '{product.nombre}'\n\n")

def _delete_alert(product: Product, alert_type: str, db: Session) -> None:
    db.query(Alert).filter(
        Alert.user_id == UUID(product.user_id),
        Alert.product_id == product.id,
        Alert.type == alert_type,
    ).delete()
    db.commit()
    print(f"\n\nSe eliminó alerta de tipo '{alert_type}' para el producto '{product.nombre}'\n\n")

# def _notificate_low_stock(token: str, product: Product):
#     message_title = "Stock Bajo"
#     message_body = "Hay pocas unidades del producto "+product.nombre+" ("+str(product.stock)+" unidades)."
#     return notification_service.send_notification(token, message_title, message_body, "")

# def _notificate_expirancy(token: str, product: Product, expirancy_days: int):
#     message_title = "Producto próximo a vencerse"
#     message_body = "El producto "+product.nombre+" vence en "+str(expirancy_days)+"dias."
#     return notification_service.send_notification(token, message_title, message_body, "")

# def _check_product_state(product: Product, user: AuthUser, profile: UserProfile, db: Session):
#     stock_warning = profile.stock_minimo or DEFAULT_STOCK_MINIMO
#     expirancy_warning = profile.dias_alerta_vencimiento or DEFAULT_DIAS_ALERTA_VENCIMIENTO
#     product_alerts = db.query(Alert).filter(Alert.product_id == product.id).all()
#     if product.stock < stock_warning:
#         if any(alert.type == "stock" and alert.level == "critical" for alert in product_alerts):
#             response_status = _notificate_low_stock(profile.notification_token, product)
#             print("\n\nse envio la notificacion de stock: "+str(response_status)+"\n\n")
#         else:
#             _create_alert(product, "stock", "critical", db)
#             response_status = _notificate_low_stock(profile.notification_token, product)
#             print("\n\nse envio la notificacion de stock: "+str(response_status)+"\n\n")
#     elif any(alert.type == "stock" for alert in product_alerts):
#         db.query(Alert).filter(Alert.product_id == product.id, Alert.type == "stock").delete()
#         db.commit()
#     if product.vencimiento != None:
#         expirancy_days = (product.vencimiento - date.today()).days
#         if expirancy_days < expirancy_warning:
#             if expirancy_days <= 1:
#                 if not any(alert.type == "expiry" and (alert.level == "critical" or alert.level == "warning") for alert in product_alerts):
#                     _create_alert(product, "expiry", "critical", db)
#                 if any(alert.type == "expiry" and alert.level == "warning" for alert in product_alerts):
#                     alert = next(alert for alert in product_alerts if alert.type == "expiry" and alert.level == "warning")
#                     alert.level = "critical"
#                     db.commit()
#                     db.refresh(alert)
#             else:
#                 if not any(alert.type == "expiry" and alert.level == "warning" for alert in product_alerts):
#                     _create_alert(product, "expiry", "warning", db)
#             response_status = _notificate_expirancy(profile.notification_token, product, expirancy_days)
#             print("\n\nse envio la notificacion de vencimiento: "+str(response_status)+"\n\n")
#         elif any(alert.type == "expiry" for alert in product_alerts):
#             db.query(Alert).filter(Alert.product_id == product.id, Alert.type == "expiry").delete()
#             db.commit()

def _notificate_low_coverage(token: str, product: Product, days: int):
    label = "día" if days == 1 else "días"
    notification_service.send_notification(
        token,
        "Stock por agotarse",
        f"{product.nombre} se agotará en aproximadamente {days} {label}.",
    )

def _notificate_overstock(token: str, product: Product, days: int):
    notification_service.send_notification(
        token,
        "Compraste más de lo necesario",
        f"Tenés {product.nombre} para aproximadamente {days} días. Quizás compraste de más.",
    )

def _notificate_understock(token: str, product: Product, days: int):
    notification_service.send_notification(
        token,
        "Compraste menos de lo necesario",
        f"Aun con la compra, {product.nombre} te alcanza solo para {days} días. Considerá comprar más.",
    )

def _notificate_slow_pace(token: str, product: Product, days_until_expiry: int, units_wasted: int):
    notification_service.send_notification(
        token,
        "Riesgo de vencimiento por bajo consumo",
        f"Al ritmo actual, {units_wasted} unidad{'es' if units_wasted != 1 else ''} de {product.nombre} vencer{'án' if units_wasted != 1 else 'á'} en {days_until_expiry} días.",
    )

def _notificate_expirancy(token: str, product: Product, expirancy_days: int):
    notification_service.send_notification(
        token,
        "Producto próximo a vencerse",
        f"El producto {product.nombre} vence en {expirancy_days} días.",
    )

async def _check_product_state(
    product: Product, user: AuthUser, profile: UserProfile, db: Session,
    stock_increased: bool = False,
) -> dict | None:
    """
    Evalúa el estado de un producto y envía alertas según corresponda.
    Retorna el resultado ML (daily_rate, days_until_stockout, stage) o None.
    """
    # Alerta de vencimiento (estática — no requiere ML). El producto puede
    # tener su propia regla; si no, se usa la del perfil del usuario.
    expirancy_warning = (
        product.dias_alerta_vencimiento or profile.dias_alerta_vencimiento or DEFAULT_DIAS_ALERTA_VENCIMIENTO
    )
    product_alerts = db.query(Alert).filter(Alert.product_id == product.id).all()
    if product.vencimiento is not None:
        expirancy_days = (product.vencimiento - date.today()).days
        expiry_alerts = [alert for alert in product_alerts if alert.type == "expiry"]
        if expiry_alerts:
            alert = expiry_alerts[0]
            if expirancy_days > expirancy_warning:
                _delete_alert(product, "expiry", db)
            elif alert.level == "warning" and expirancy_days <= 1:
                alert.level = "critical"
                db.commit()
                db.refresh(alert)
                print(f"\n\nSe actualizó alerta de tipo 'expiry' a nivel 'critical' para el producto '{product.nombre}'\n\n")
                _notificate_expirancy(user.firebase_token, product, expirancy_days)
        elif expirancy_days < expirancy_warning:
            _create_alert(product, "expiry", "warning" if expirancy_days > 1 else "critical", db)
            _notificate_expirancy(user.firebase_token, product, expirancy_days)

    if not settings.ML_SERVICE_URL:
        return None
    coverage_threshold = product.stock_minimo or profile.stock_minimo or DEFAULT_COVERAGE_DAYS
    try:
        events = (
            db.query(ConsumptionEvent)
            .filter(ConsumptionEvent.product_id == product.id)
            .order_by(ConsumptionEvent.consumed_at.asc())
            .all()
        )
        events_data = [
            {
                "quantity": e.quantity,
                "event_type": e.event_type,
                "consumed_at": e.consumed_at.isoformat(),
                "product_id": e.product_id,
            }
            for e in events
        ]
        product_data = {
            "id": product.id,
            "stock": product.stock,
            "stock_minimo": product.stock_minimo,
            "categoria": product.categoria,
            "nombre": product.nombre,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{settings.ML_SERVICE_URL}/models/predict-product",
                json={"events": events_data, "product": product_data},
                headers={"X-Internal-Token": settings.INTERNAL_SERVICE_TOKEN},
            )
        if r.status_code == 200:
            result = r.json()
            days_until_stockout = result.get("days_until_stockout")
            daily_rate = result.get("daily_rate")

            # Alerta de bajo stock — se suprime en restock porque el caller
            # decide entre "compraste de más" o "compraste de menos"
            if not stock_increased and days_until_stockout is not None and days_until_stockout < coverage_threshold:
                _delete_alert(product, "stock_low_coverage", db)
                _create_alert(product, "stock_low_coverage", "warning" if days_until_stockout > 1 else "critical", db)
                _notificate_low_coverage(user.firebase_token, product, days_until_stockout)

            # Alerta de ritmo lento vs. vencimiento
            if (
                product.vencimiento is not None
                and days_until_stockout is not None
                and daily_rate is not None
                and daily_rate > 0
            ):
                days_until_expiry = (product.vencimiento - date.today()).days
                if 0 < days_until_expiry < days_until_stockout:
                    units_wasted = max(0, product.stock - int(daily_rate * days_until_expiry))
                    if units_wasted > 0:
                        _delete_alert(product, "slow_pace", db)
                        _create_alert(product, "slow_pace", "warning", db)
                        _notificate_slow_pace(user.firebase_token, product, days_until_expiry, units_wasted)

            return result
    except Exception:
        pass
    return None



SORTABLE_FIELDS = {
    "nombre": Product.nombre,
    "stock": Product.stock,
    "vencimiento": Product.vencimiento,
    "categoria": Product.categoria,
}


@router.get("/", response_model=list[ProductResponse])
async def list_products(
    search: Optional[str] = Query(None),
    categoria: Optional[str] = Query(None),
    ubicacion: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None, pattern="^(nombre|stock|vencimiento|categoria)$"),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user["sub"]
    query = db.query(Product).filter(Product.user_id == user_id)
    if search:
        term = f"%{search}%"
        query = query.filter(
            Product.nombre.ilike(term) | Product.marca.ilike(term)
        )
    if categoria:
        query = query.filter(Product.categoria.ilike(categoria))
    if ubicacion:
        query = query.filter(Product.ubicacion.ilike(ubicacion))
    if sort_by:
        column = SORTABLE_FIELDS[sort_by]
        query = query.order_by(column.desc() if sort_dir == "desc" else column.asc())
    else:
        query = query.order_by(Product.created_at.desc())
    return query.all()


@router.get("/filters/options")
async def get_filter_options(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user["sub"]
    base = db.query(Product).filter(Product.user_id == user_id)
    categorias = [
        row[0] for row in base.with_entities(Product.categoria).distinct().all()
        if row[0]
    ]
    ubicaciones = [
        row[0] for row in base.with_entities(Product.ubicacion).distinct().all()
        if row[0]
    ]
    marcas = [
        row[0] for row in base.with_entities(Product.marca).distinct().all()
        if row[0]
    ]
    return {"categorias": sorted(categorias), "ubicaciones": sorted(ubicaciones), "marcas": sorted(marcas)}


@router.get("/suggest", response_model=list[ProductSuggestion])
async def suggest_products(
    q: str = Query(..., min_length=1),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user["sub"]
    rows = (
        db.query(Product)
        .filter(Product.user_id == user_id, Product.nombre.ilike(f"%{q}%"))
        .order_by(Product.created_at.desc())
        .limit(50)
        .all()
    )
    seen: set[str] = set()
    suggestions: list[ProductSuggestion] = []
    for p in rows:
        key = p.nombre.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        suggestions.append(
            ProductSuggestion(
                id=p.id,
                nombre=p.nombre,
                marca=p.marca,
                categoria=p.categoria,
                ubicacion=p.ubicacion,
                vencimiento=p.vencimiento,
                stock_minimo=p.stock_minimo,
                dias_alerta_vencimiento=p.dias_alerta_vencimiento,
            )
        )
        if len(suggestions) >= 8:
            break
    return suggestions


@router.get("/defaults", response_model=ProductDefaults)
async def get_defaults(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user["sub"]).first()
    if not profile:
        return ProductDefaults()
    return ProductDefaults(last_categoria=profile.last_categoria, last_ubicacion=profile.last_ubicacion)


@router.post("/", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    data: ProductCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user["sub"]
    actor_email = current_user.get("email")

    profile = _get_or_create_profile(user_id, db)
    profile.last_categoria = data.categoria
    profile.last_ubicacion = data.ubicacion
    db.commit()

    existing = _find_matching_product(user_id, data.nombre, data.marca, data.vencimiento, db)
    if existing:
        existing.stock += data.stock
        db.add(ConsumptionEvent(
            product_id=existing.id,
            user_id=user_id,
            quantity=data.stock,
            event_type="restocked",
        ))
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
        db.refresh(existing)
        _log_activity(
            db, "product_updated", actor_email, user_id, actor_email,
            f"{actor_email or user_id} sumó {data.stock} unidades a \"{existing.nombre}\" (stock: {existing.stock})",
        )
        user = _get_user(user_id, db)
        result = await _check_product_state(existing, user, profile, db, stock_increased=True)
        if result:
            days_until_stockout = result.get("days_until_stockout")
            coverage_threshold = existing.stock_minimo or profile.stock_minimo or DEFAULT_COVERAGE_DAYS
            overstock_threshold = max(DEFAULT_OVERSTOCK_DAYS, 4 * coverage_threshold)
            if days_until_stockout is not None and days_until_stockout > overstock_threshold:
                _delete_alert(existing, "overstock", db)
                _create_alert(existing, "overstock", "warning", db)
                _notificate_overstock(user.firebase_token, existing, days_until_stockout)
            elif days_until_stockout is not None and days_until_stockout < coverage_threshold:
                _delete_alert(existing, "understock", db)
                _create_alert(existing, "understock", "warning" if days_until_stockout > 1 else "critical", db)
                _notificate_understock(user.firebase_token, existing, days_until_stockout)
        return ProductResponse.model_validate(existing, from_attributes=True).model_copy(update={"merged": True})

    product = Product(user_id=user_id, **data.model_dump())
    db.add(product)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    db.refresh(product)
    _log_activity(
        db, "product_created", actor_email, user_id, actor_email,
        f"{actor_email or user_id} cargó \"{product.nombre}\" (stock: {product.stock}) desde la app",
    )
    return product


@router.get("/expired", response_model=list[ProductResponse])
async def get_expired_products(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = date.today()
    return (
        db.query(Product)
        .filter(
            Product.user_id == current_user["sub"],
            Product.vencimiento < today,
            Product.stock > 0,
        )
        .all()
    )


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_user_product(product_id, current_user["sub"], db)


@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    data: ProductUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user["sub"]
    actor_email = current_user.get("email")
    product = _get_user_product(product_id, user_id, db)

    update_dict = data.model_dump(exclude_unset=True)
    new_stock_value = update_dict.get("stock")
    old_stock = product.stock
    stock_increased = new_stock_value is not None and new_stock_value > old_stock

    if new_stock_value is not None and new_stock_value < old_stock:
        db.add(ConsumptionEvent(
            product_id=product.id,
            user_id=product.user_id,
            quantity=old_stock - new_stock_value,
            event_type="consumed",
        ))
    elif stock_increased:
        db.add(ConsumptionEvent(
            product_id=product.id,
            user_id=product.user_id,
            quantity=new_stock_value - old_stock,
            event_type="restocked",
        ))

    changed_fields = list(update_dict.keys())
    for field, value in update_dict.items():
        setattr(product, field, value)

    user = _get_user(user_id, db)
    profile = _get_or_create_profile(user_id, db)
    result = await _check_product_state(product, user, profile, db, stock_increased=stock_increased)

    if result and stock_increased:
        days_until_stockout = result.get("days_until_stockout")
        coverage_threshold = product.stock_minimo or profile.stock_minimo or DEFAULT_COVERAGE_DAYS
        overstock_threshold = max(DEFAULT_OVERSTOCK_DAYS, 4 * coverage_threshold)
        if days_until_stockout is not None and days_until_stockout > overstock_threshold:
            _notificate_overstock(user.firebase_token, product, days_until_stockout)
        elif days_until_stockout is not None and days_until_stockout < coverage_threshold:
            _notificate_understock(user.firebase_token, product, days_until_stockout)

    db.commit()
    db.refresh(product)
    if changed_fields:
        _log_activity(
            db, "product_updated", actor_email, user_id, actor_email,
            f"{actor_email or user_id} editó \"{product.nombre}\" ({', '.join(changed_fields)}) desde la app",
        )
    return product


@router.get("/{product_id}/consumption")
async def get_consumption_history(
    product_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_user_product(product_id, current_user["sub"], db)
    events = (
        db.query(ConsumptionEvent)
        .filter(ConsumptionEvent.product_id == product_id)
        .order_by(ConsumptionEvent.consumed_at.asc())
        .all()
    )
    return [
        {"id": e.id, "quantity": e.quantity, "event_type": e.event_type, "consumed_at": e.consumed_at}
        for e in events
    ]


@router.post("/{product_id}/events", status_code=status.HTTP_201_CREATED)
async def register_event(
    product_id: int,
    data: EventRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user["sub"]
    product = _get_user_product(product_id, user_id, db)
    if data.quantity <= 0 or data.quantity > product.stock:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cantidad inválida",
        )
    db.add(ConsumptionEvent(
        product_id=product.id,
        user_id=product.user_id,
        quantity=data.quantity,
        event_type=data.event_type,
    ))
    product.stock = max(0, product.stock - data.quantity)
    db.commit()
    db.refresh(product)
    user = _get_user(user_id, db)
    profile = _get_or_create_profile(user_id, db)
    await _check_product_state(product, user, profile, db)
    return {"event_type": data.event_type, "quantity": data.quantity, "remaining_stock": product.stock}


def _get_own_consumption_event(product_id: int, event_id: int, db: Session) -> ConsumptionEvent:
    event = db.query(ConsumptionEvent).filter(
        ConsumptionEvent.id == event_id,
        ConsumptionEvent.product_id == product_id,
    ).first()
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registro de consumo no encontrado")
    return event


@router.put("/{product_id}/events/{event_id}")
async def update_consumption_event(
    product_id: int,
    event_id: int,
    data: EventCorrection,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user["sub"]
    actor_email = current_user.get("email")
    product = _get_user_product(product_id, user_id, db)
    event = _get_own_consumption_event(product_id, event_id, db)

    new_stock = (
        product.stock
        - _stock_effect(event.event_type, event.quantity)
        + _stock_effect(data.event_type, data.quantity)
    )
    if new_stock < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No se puede corregir: dejaría el stock en negativo",
        )

    old_quantity = event.quantity
    event.quantity = data.quantity
    event.event_type = data.event_type
    product.stock = new_stock
    db.commit()
    db.refresh(product)

    user = _get_user(user_id, db)
    profile = _get_or_create_profile(user_id, db)
    await _check_product_state(product, user, profile, db)
    _log_activity(
        db, "product_updated", actor_email, user_id, actor_email,
        f"{actor_email or user_id} corrigió un consumo de \"{product.nombre}\" "
        f"(de {old_quantity} a {data.quantity} unidades) desde la app",
    )
    return {"event_type": event.event_type, "quantity": event.quantity, "remaining_stock": product.stock}


@router.delete("/{product_id}/events/{event_id}")
async def delete_consumption_event(
    product_id: int,
    event_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user["sub"]
    actor_email = current_user.get("email")
    product = _get_user_product(product_id, user_id, db)
    event = _get_own_consumption_event(product_id, event_id, db)

    quantity = event.quantity
    motivo = event.event_type
    new_stock = product.stock - _stock_effect(motivo, quantity)
    if new_stock < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No se puede borrar: dejaría el stock en negativo",
        )
    product.stock = new_stock
    db.delete(event)
    db.commit()
    db.refresh(product)

    user = _get_user(user_id, db)
    profile = _get_or_create_profile(user_id, db)
    await _check_product_state(product, user, profile, db)
    _log_activity(
        db, "product_updated", actor_email, user_id, actor_email,
        f"{actor_email or user_id} eliminó un registro de consumo de \"{product.nombre}\" "
        f"({quantity} unidades, {motivo}) desde la app",
    )
    return {"remaining_stock": product.stock}


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user["sub"]
    actor_email = current_user.get("email")
    product = _get_user_product(product_id, user_id, db)
    nombre = product.nombre
    db.delete(product)
    db.commit()
    _log_activity(
        db, "product_deleted", actor_email, user_id, actor_email,
        f"{actor_email or user_id} eliminó \"{nombre}\" desde la app",
    )
