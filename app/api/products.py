from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Literal, Optional

from app.models.alert import Alert
from app.core import barcode
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.activity_log import AdminActivityLog
from app.models.consumption import ConsumptionEvent
from app.models.product import Product
from app.models.profile import DEFAULT_COVERAGE_DAYS, DEFAULT_DIAS_ALERTA_VENCIMIENTO, DEFAULT_OVERSTOCK_DAYS, DEFAULT_USER_TYPE, UserProfile
from app.models.user import AuthUser
from app.schemas.product import (
    ProductCreate,
    ProductDefaults,
    ProductResponse,
    ProductSuggestion,
    ProductUpdate,
    ReposicionSuggestion,
)
from app.services import ml_client
from app.services.notifications import NotificationService


class EventRequest(BaseModel):
    event_type: Literal["consumed", "expired"]
    quantity: int = Field(..., le=999999)
    note: Optional[str] = Field(None, max_length=50)


class EventCorrection(BaseModel):
    event_type: Literal["consumed", "expired", "restocked"]
    quantity: int = Field(..., le=999999)
    note: Optional[str] = Field(None, max_length=50)


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


def _get_user(user_id: str, db: Session) -> AuthUser:
    try:
        uid = UUID(str(user_id))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    user = db.query(AuthUser).filter(
        AuthUser.id == uid
    ).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    return user

def _create_alert(product: Product, alert_type: str, alert_level: str, db: Session, units_wasted: int, stockout_date: int) -> None:
    alert = Alert(
        user_id=UUID(product.user_id),
        product_id=product.id,
        type=alert_type,
        level=alert_level,
        units_wasted=units_wasted,
        days_until_stockout=stockout_date
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

def _clear_alert(product: Product, alert_type: str, current_alerts: list[Alert], db: Session) -> None:
    """Borra la alerta de ese tipo si existe: la condición que la generó ya no se cumple.

    Sin esto una alerta nacía y no se iba nunca: reponer un producto con «stock
    crítico» lo dejaba marcado como crítico con 200 unidades en la alacena.
    """
    if any(alert.type == alert_type for alert in current_alerts):
        _delete_alert(product, alert_type, db)


async def _notificate_low_coverage(token: str, product: Product, days: int, user_email: str):
    label = "día" if days == 1 else "días"
    await notification_service.send_notification(
        token,
        "Stock por agotarse",
        f"{product.nombre} se agotará en aproximadamente {days} {label}.",
        user_email
    )

async def _notificate_overstock(token: str, product: Product, days: int, user_email: str):
    await notification_service.send_notification(
        token,
        "Compraste más de lo necesario",
        f"Tenés {product.nombre} para aproximadamente {days} días. Quizás compraste de más.",
        user_email
    )

async def _notificate_understock(token: str, product: Product, days: int, user_email: str):
    await notification_service.send_notification(
        token,
        "Compraste menos de lo necesario",
        f"Aun con la compra, {product.nombre} te alcanza solo para {days} días. Considerá comprar más.",
        user_email
    )

async def _notificate_slow_pace(token: str, product: Product, days_until_expiry: int, units_wasted: int, user_email: str):
    await notification_service.send_notification(
        token,
        "Riesgo de vencimiento por bajo consumo",
        f"Al ritmo actual, {units_wasted} unidad{'es' if units_wasted != 1 else ''} de {product.nombre} vencer{'án' if units_wasted != 1 else 'á'} en {days_until_expiry} días.",
        user_email
    )

async def _notificate_expirancy(token: str, product: Product, expirancy_days: int, user_email: str):
    await notification_service.send_notification(
        token,
        "Producto próximo a vencerse",
        f"El producto {product.nombre} vence en {expirancy_days} días.",
        user_email
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
                await _notificate_expirancy(user.firebase_token, product, expirancy_days, user.email)
        elif expirancy_days < expirancy_warning:
            _create_alert(product, "expiry", "warning" if expirancy_days > 1 else "critical", db, None, None)
            await _notificate_expirancy(user.firebase_token, product, expirancy_days, user.email)

    if not settings.ML_SERVICE_URL:
        return None
    coverage_threshold = product.stock_minimo or profile.stock_minimo or DEFAULT_COVERAGE_DAYS
    segment = profile.user_type or DEFAULT_USER_TYPE
    events = (
        db.query(ConsumptionEvent)
        .filter(ConsumptionEvent.product_id == product.id)
        .order_by(ConsumptionEvent.consumed_at.asc())
        .all()
    )
    product_data = {
        "id": product.id,
        "stock": product.stock,
        "stock_minimo": product.stock_minimo,
        "categoria": product.categoria,
        "nombre": product.nombre,
    }
    result = await ml_client.predict(events, product_data, segment=segment)
    if not result:
        return None

    days_until_stockout = result.get("days_until_stockout")
    daily_rate = result.get("daily_rate")

    # Alerta de bajo stock — se suprime en restock porque el caller
    # decide entre "compraste de más" o "compraste de menos"
    low_coverage = days_until_stockout is not None and days_until_stockout < coverage_threshold
    if low_coverage:
        if not stock_increased:
            _delete_alert(product, "stock_low_coverage", db)
            _create_alert(product, "stock_low_coverage", "warning" if days_until_stockout > 1 else "critical", db, None, days_until_stockout)
            await _notificate_low_coverage(user.firebase_token, product, days_until_stockout, user.email)
    else:
        # La cobertura se recuperó (p. ej. repusieron stock): la alerta ya no corresponde.
        _clear_alert(product, "stock_low_coverage", product_alerts, db)

    # Alerta de ritmo lento vs. vencimiento
    slow_pace_risk = False
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
                slow_pace_risk = True
                _delete_alert(product, "slow_pace", db)
                _create_alert(product, "slow_pace", "warning", db, units_wasted, None)
                await _notificate_slow_pace(user.firebase_token, product, days_until_expiry, units_wasted, user.email)
    if not slow_pace_risk:
        # Cambió el vencimiento, el ritmo de consumo o el stock: ya no se va a desperdiciar nada.
        _clear_alert(product, "slow_pace", product_alerts, db)

    return result



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


def _to_suggestion(p: Product) -> ProductSuggestion:
    """Los datos de un producto que la app copia al formulario al elegirlo."""
    return ProductSuggestion(
        id=p.id,
        nombre=p.nombre,
        marca=p.marca,
        categoria=p.categoria,
        ubicacion=p.ubicacion,
        vencimiento=p.vencimiento,
        stock=p.stock,
        stock_minimo=p.stock_minimo,
        dias_alerta_vencimiento=p.dias_alerta_vencimiento,
        descripcion=p.descripcion,
        imagen_url=p.imagen_url,
        codigo_barras=p.codigo_barras,
    )


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
        .order_by(Product.nombre.asc(), Product.vencimiento.asc())
        .limit(10)
        .all()
    )
    return [_to_suggestion(p) for p in rows]


@router.get("/by-barcode/{codigo}", response_model=Optional[ProductSuggestion])
async def product_by_barcode(
    codigo: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Qué producto del usuario tiene este código de barras, si alguno.

    Devuelve `null` en vez de 404 porque no encontrarlo es un resultado normal:
    es lo que le dice a la app que abra un alta nueva con el código ya cargado.

    El código se normaliza antes de buscar por la misma razón por la que se
    normaliza al guardarlo: el mismo envase leído por el escáner y escrito a mano
    tiene que encontrarse a sí mismo.
    """
    try:
        normalizado = barcode.normalizar(codigo)
    except barcode.CodigoInvalido as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    if not normalizado:
        return None

    product = (
        db.query(Product)
        .filter(Product.user_id == current_user["sub"], Product.codigo_barras == normalizado)
        .order_by(Product.vencimiento.asc().nullslast(), Product.id.asc())
        .first()
    )
    if not product:
        return None

    return _to_suggestion(product)


@router.get("/by-barcode/{codigo}/all", response_model=list[ProductSuggestion])
async def products_by_barcode(
    codigo: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Todos los productos del usuario con este código de barras (puede haber varios lotes).

    Si el código viene vacío devuelve una lista vacía; si viene mal escrito, un 422.
    """
    try:
        normalizado = barcode.normalizar(codigo)
    except barcode.CodigoInvalido as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    if not normalizado:
        return []

    rows = (
        db.query(Product)
        .filter(Product.user_id == current_user["sub"], Product.codigo_barras == normalizado)
        .order_by(Product.vencimiento.asc().nullslast(), Product.id.asc())
        .all()
    )
    return [_to_suggestion(p) for p in rows]


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
        if data.codigo_barras and not existing.codigo_barras:
            existing.codigo_barras = data.codigo_barras
        db.add(ConsumptionEvent(
            product_id=existing.id,
            user_id=user_id,
            quantity=data.stock,
            event_type="restocked",
            actor_email=actor_email,
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
                await _notificate_overstock(user.firebase_token, existing, days_until_stockout, user.email)
            elif days_until_stockout is not None and days_until_stockout < coverage_threshold:
                await _notificate_understock(user.firebase_token, existing, days_until_stockout, user.email)
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


@router.get("/reposicion-sugerida", response_model=list[ReposicionSuggestion])
async def get_reposicion_sugerida(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Para cada producto en riesgo de agotarse antes de la cobertura mínima
    configurada, sugiere cuánto reponer para volver a esa cobertura, en base a
    la tasa de consumo diaria que predice el ML.
    """
    user_id = current_user["sub"]
    profile = _get_or_create_profile(user_id, db)
    segment = profile.user_type or DEFAULT_USER_TYPE

    products = (
        db.query(Product)
        .filter(Product.user_id == user_id, Product.stock > 0)
        .all()
    )

    suggestions: list[ReposicionSuggestion] = []
    for product in products:
        coverage_threshold = product.stock_minimo or profile.stock_minimo or DEFAULT_COVERAGE_DAYS
        events = (
            db.query(ConsumptionEvent)
            .filter(ConsumptionEvent.product_id == product.id)
            .order_by(ConsumptionEvent.consumed_at.asc())
            .all()
        )
        product_data = {
            "id": product.id,
            "stock": product.stock,
            "stock_minimo": product.stock_minimo,
            "categoria": product.categoria,
            "nombre": product.nombre,
        }
        result = await ml_client.predict(events, product_data, segment=segment)
        if not result:
            continue

        daily_rate = result.get("daily_rate") or 0.0
        days_until_stockout = result.get("days_until_stockout")
        if daily_rate <= 0 or days_until_stockout is None:
            continue
        if days_until_stockout >= coverage_threshold:
            continue

        suggested_qty = max(0, round(daily_rate * coverage_threshold) - product.stock)
        if suggested_qty <= 0:
            continue

        suggestions.append(ReposicionSuggestion(
            product_id=product.id,
            nombre=product.nombre,
            stock=product.stock,
            imagen_url=product.imagen_url,
            daily_rate=round(daily_rate, 3),
            days_until_stockout=days_until_stockout,
            suggested_qty=suggested_qty,
        ))

    suggestions.sort(key=lambda s: s.days_until_stockout if s.days_until_stockout is not None else 999)
    return suggestions


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
            actor_email=actor_email,
        ))
    elif stock_increased:
        db.add(ConsumptionEvent(
            product_id=product.id,
            user_id=product.user_id,
            quantity=new_stock_value - old_stock,
            event_type="restocked",
            actor_email=actor_email,
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
            await _notificate_overstock(user.firebase_token, product, days_until_stockout, user.email)
        elif days_until_stockout is not None and days_until_stockout < coverage_threshold:
            await _notificate_understock(user.firebase_token, product, days_until_stockout, user.email)

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
    reversed_ids = {e.reverses_event_id for e in events if e.reverses_event_id is not None}
    return [
        {
            "id": e.id,
            "quantity": e.quantity,
            "event_type": e.event_type,
            "consumed_at": e.consumed_at,
            "note": e.note,
            "actor_email": e.actor_email,
            "reverses_event_id": e.reverses_event_id,
            "reversed": e.id in reversed_ids,
        }
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
    actor_email = current_user.get("email")
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
        actor_email=actor_email,
        note=data.note,
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
    if event.reverses_event_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este registro ya es una corrección — no se puede corregir de nuevo",
        )
    already_reversed = db.query(ConsumptionEvent).filter(
        ConsumptionEvent.reverses_event_id == event.id
    ).first()
    if already_reversed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este registro ya fue corregido — corregí la versión más reciente",
        )
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

    reversal_type = "consumed" if event.event_type == "restocked" else "restocked"
    db.add(ConsumptionEvent(
        product_id=product.id,
        user_id=product.user_id,
        quantity=event.quantity,
        event_type=reversal_type,
        actor_email=actor_email,
        note=f"Corrección: revierte el registro #{event.id}",
        reverses_event_id=event.id,
    ))
    new_event = ConsumptionEvent(
        product_id=product.id,
        user_id=product.user_id,
        quantity=data.quantity,
        event_type=data.event_type,
        actor_email=actor_email,
        note=data.note or f"Corrige el registro #{event.id} (antes: {event.quantity} {event.event_type})",
    )
    db.add(new_event)
    product.stock = new_stock
    db.commit()
    db.refresh(product)
    db.refresh(new_event)

    user = _get_user(user_id, db)
    profile = _get_or_create_profile(user_id, db)
    await _check_product_state(product, user, profile, db)
    _log_activity(
        db, "product_updated", actor_email, user_id, actor_email,
        f"{actor_email or user_id} corrigió un consumo de \"{product.nombre}\" "
        f"(de {event.quantity} a {data.quantity} unidades) desde la app",
    )
    return {"event_type": new_event.event_type, "quantity": new_event.quantity, "remaining_stock": product.stock}


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
    reversal_type = "consumed" if motivo == "restocked" else "restocked"
    db.add(ConsumptionEvent(
        product_id=product.id,
        user_id=product.user_id,
        quantity=quantity,
        event_type=reversal_type,
        actor_email=actor_email,
        note=f"Deshecho: revierte el registro #{event.id}",
        reverses_event_id=event.id,
    ))
    product.stock = new_stock
    db.commit()
    db.refresh(product)

    user = _get_user(user_id, db)
    profile = _get_or_create_profile(user_id, db)
    await _check_product_state(product, user, profile, db)
    _log_activity(
        db, "product_updated", actor_email, user_id, actor_email,
        f"{actor_email or user_id} deshizo un registro de consumo de \"{product.nombre}\" "
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
    # alerts.product_id no tiene ON DELETE CASCADE: en Postgres, borrar un producto con alertas
    # falla con un 500 si antes no se borran sus alertas.
    db.query(Alert).filter(Alert.product_id == product.id).delete(synchronize_session=False)
    db.delete(product)
    db.commit()
    _log_activity(
        db, "product_deleted", actor_email, user_id, actor_email,
        f"{actor_email or user_id} eliminó \"{nombre}\" desde la app",
    )
