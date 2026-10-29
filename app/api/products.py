import asyncio
import logging
import re
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Literal, Optional

from app.models.alert import Alert
from app.core import barcode, matching
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.activity_log import AdminActivityLog
from app.models.consumption import ConsumptionEvent
from app.models.product import Product
from app.services import alert_engine, alert_rules, alert_texts
from app.services.restock import suggested_restock
from app.models.profile import DEFAULT_COVERAGE_DAYS, DEFAULT_DIAS_ALERTA_VENCIMIENTO, DEFAULT_OVERSTOCK_DAYS, DEFAULT_USER_TYPE, UserProfile
from app.models.user import AuthUser
from app.schemas.product import (
    ProductCreate,
    ProductDefaults,
    ProductResponse,
    ProductSuggestion,
    ProductUpdate,
    ReposicionSuggestion,
    StockChange,
    StockTotalResponse,
)
from app.services import ml_client
from app.utils.sorting import alphabetical_key
from app.services.notifications import NotificationService

logger = logging.getLogger(__name__)

_ML_CONCURRENCY = 8


class EventRequest(BaseModel):
    event_type: Literal["consumed", "expired", "sold", "rented"]
    quantity: int = Field(..., le=999999)
    note: Optional[str] = Field(None, max_length=50)


class RestockRequest(BaseModel):
    quantity: int = Field(..., gt=0, le=999999)


class EventCorrection(BaseModel):
    event_type: Literal["consumed", "expired", "sold", "rented", "restocked"]
    quantity: int = Field(..., le=999999)
    note: Optional[str] = Field(None, max_length=50)


# Nota con la que queda asentado un cambio de stock hecho al editar el producto (no una entrada ni una salida)
STOCK_EDIT_NOTE = "Modificación de stock"


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

async def _notificate_low_coverage(token: str, product: Product, days: int, user_email: str, limit_days=None, daily_rate=None):
    await notification_service.send_notification(
        token,
        "Stock por agotarse",
        alert_texts.low_coverage_body(product.nombre, days),
        user_email,
        kind="low_coverage", product_name=product.nombre, days=days, limit_days=limit_days, daily_rate=daily_rate,
    )

async def _notificate_overstock(token: str, product: Product, days: int, user_email: str, limit_days=None, daily_rate=None):
    limit = limit_days or DEFAULT_COVERAGE_DAYS
    await notification_service.send_notification(
        token,
        "Compraste más de lo necesario",
        alert_texts.overstock_body(product.nombre, days, limit),
        user_email,
        kind="overstock", product_name=product.nombre, days=days, limit_days=limit, daily_rate=daily_rate,
    )

async def _notificate_understock(token: str, product: Product, days: int, user_email: str, limit_days=None, daily_rate=None):
    limit = limit_days or DEFAULT_COVERAGE_DAYS
    await notification_service.send_notification(
        token,
        "Compraste menos de lo necesario",
        alert_texts.understock_body(product.nombre, days, limit),
        user_email,
        kind="understock", product_name=product.nombre, days=days, limit_days=limit, daily_rate=daily_rate,
    )

async def _notificate_slow_pace(token: str, product: Product, days_until_expiry: int, units_wasted: int, user_email: str):
    await notification_service.send_notification(
        token,
        "Riesgo de vencimiento por bajo consumo",
        alert_texts.slow_pace_body(product.nombre, units_wasted, days_until_expiry),
        user_email,
        kind="slow_pace", product_name=product.nombre, days=days_until_expiry, units=units_wasted,
    )

async def _notificate_expirancy(token: str, product: Product, expirancy_days: int, user_email: str, limit_days=None):
    await notification_service.send_notification(
        token,
        "Producto próximo a vencerse",
        alert_texts.expiry_body(product.nombre, expirancy_days),
        user_email,
        kind="expiry", product_name=product.nombre, days=expirancy_days, limit_days=limit_days,
    )

async def _check_product_state(
    product: Product, user: AuthUser, profile: UserProfile, db: Session,
    stock_increased: bool = False,
) -> dict | None:
    """
    Evalúa el estado de un producto y envía alertas según corresponda.
    Retorna el resultado ML (daily_rate, days_until_stockout, stage) o None.

    Los límites y los niveles salen de `alert_rules`, los mismos que usan el job y la lectura de alertas.
    """
    existing = db.query(Alert).filter(Alert.product_id == product.id).all()

    # Alerta de vencimiento (estática — no requiere ML). El producto puede tener su propia regla; si no, se usa la
    # del perfil del usuario.
    expiry_days = alert_engine.sync_product_expiry(db, product, profile, existing)
    if expiry_days is not None:
        limit, _ = alert_rules.expiry_limit(product.dias_alerta_vencimiento, profile)
        await _notificate_expirancy(user.firebase_token, product, expiry_days, user.email, limit_days=limit)

    # Sin stock no hay nada que agotar ni que se pueda vencer
    if product.stock <= 0:
        alert_engine.clear_alerts(db, existing, "stock_low_coverage", "slow_pace", *alert_engine.LEGACY_TYPES)
        return None

    if not settings.ML_SERVICE_URL:
        return None
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

    # Las llamadas de red ya se toleran en ml_client; esto cubre el resto de la
    # evaluación (DB, notificaciones): una falla acá no debe tumbar el alta o la
    # edición del producto que la disparó, que ya quedó guardado.
    try:
        await _apply_ml_alerts(product, user, db, existing, result, profile, stock_increased)
    except Exception:
        logger.exception("No se pudieron evaluar las alertas de ML del producto %s", product.id)
        db.rollback()
        return None

    return result


async def _apply_ml_alerts(
    product: Product, user: AuthUser, db: Session, existing: list[Alert],
    result: dict, profile: UserProfile, stock_increased: bool,
) -> None:
    """Deja las alertas del modelo predictivo (stock mínimo con reposición sugerida, y ritmo lento) según la predicción."""
    days_until_stockout = alert_rules.whole_days(result.get("days_until_stockout"))
    daily_rate = result.get("daily_rate")

    # Alerta de stock mínimo: se crea o actualiza siempre. Se avisa solo si es crítica y no se acaba de reponer (al
    # reponer, el aviso lo da el de «compraste de menos o de más»)
    level, _ = alert_engine.apply_coverage(db, product, profile, existing, days_until_stockout, daily_rate)
    if level == "critical" and not stock_increased:
        limit, _ = alert_rules.coverage_limit(product.stock_minimo, profile)
        await _notificate_low_coverage(
            user.firebase_token, product, days_until_stockout, user.email, limit_days=limit, daily_rate=daily_rate,
        )

    # Alerta de ritmo lento vs. vencimiento
    units_wasted = None
    days_until_expiry = None
    if (
        product.vencimiento is not None
        and days_until_stockout is not None
        and daily_rate is not None
        and daily_rate > 0
    ):
        days_until_expiry = alert_rules.days_until(product.vencimiento)
        if 0 < days_until_expiry < days_until_stockout:
            units_wasted = max(0, product.stock - int(daily_rate * days_until_expiry))
    if alert_engine.apply_slow_pace(db, product, profile, existing, days_until_expiry, units_wasted):
        await _notificate_slow_pace(user.firebase_token, product, days_until_expiry, units_wasted, user.email)



SORTABLE_FIELDS = {
    "nombre": Product.nombre,
    "stock": Product.stock,
    "vencimiento": Product.vencimiento,
    "categoria": Product.categoria,
}


def _filter_products(query, search: Optional[str], categoria: Optional[str], ubicacion: Optional[str]):
    """Los filtros del inventario: el texto busca en el nombre y en la marca; categoría y ubicación son exactas.

    Los comparten el listado y el stock total, así el total siempre es el de los productos que se ven en la lista.
    """
    if search:
        term = f"%{search}%"
        query = query.filter(Product.nombre.ilike(term) | Product.marca.ilike(term))
    if categoria:
        query = query.filter(Product.categoria.ilike(categoria))
    if ubicacion:
        query = query.filter(Product.ubicacion.ilike(ubicacion))
    return query


@router.get("/stock-total", response_model=StockTotalResponse)
async def stock_total(
    search: Optional[str] = Query(None),
    categoria: Optional[str] = Query(None),
    ubicacion: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """La suma del stock y la cantidad de productos del usuario que cumplen los filtros del inventario.

    Son todos los que coinciden, no solo los de la página que se ve en la app.
    """
    query = _filter_products(
        db.query(func.coalesce(func.sum(Product.stock), 0), func.count(Product.id)).filter(Product.user_id == current_user["sub"]),
        search, categoria, ubicacion,
    )
    total, count = query.one()
    return StockTotalResponse(stock_total=int(total), products=int(count))


@router.get("/", response_model=list[ProductResponse])
async def list_products(
    search: Optional[str] = Query(None),
    categoria: Optional[str] = Query(None),
    ubicacion: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None, pattern="^(nombre|stock|vencimiento|categoria)$"),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    limit: Optional[int] = Query(None, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Productos del usuario, con filtros y orden. Sin `limit` trae todos; con `limit` y `offset` trae una página."""
    user_id = current_user["sub"]
    query = _filter_products(db.query(Product).filter(Product.user_id == user_id), search, categoria, ubicacion)
    page_end = offset + limit if limit is not None else None
    if sort_by == "nombre":
        # Orden alfabético real, sin distinguir mayúsculas ni tildes (la base ordenaría las mayúsculas primero)
        ordered = sorted(
            query.all(),
            key=lambda product: (alphabetical_key(product.nombre), product.nombre, product.id),
            reverse=sort_dir == "desc",
        )
        return ordered[offset:page_end]
    if sort_by == "vencimiento":
        # Los productos sin fecha de vencimiento no entran en este orden, ni creciente ni decreciente
        query = query.filter(Product.vencimiento.isnot(None))
    if sort_by:
        column = SORTABLE_FIELDS[sort_by]
        # El id desempata: así una página siguiente nunca repite ni se saltea productos con el mismo valor
        query = query.order_by(column.desc() if sort_dir == "desc" else column.asc(), Product.id.asc())
    else:
        query = query.order_by(Product.created_at.desc(), Product.id.desc())
    if offset:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
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


def _naive_utc(value: datetime) -> datetime:
    """Los instantes se comparan sin zona (en UTC): la base devuelve unos con zona y otros sin ella."""
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


# Las notas automáticas de las correcciones dicen cuándo se hizo el registro que corrigen (hora argentina), no su número
AR_TZ = timezone(timedelta(hours=-3))
_LEGACY_NOTE = re.compile(r"^(Corrección: revierte|Deshecho: revierte|Corrige) el registro #(\d+)(?: \(antes:.*\))?$")


def _event_stamp(moment: datetime) -> str:
    """«28/10/2026 15:29», en hora argentina."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(AR_TZ).strftime("%d/%m/%Y %H:%M")


def _clean_note(note, by_id: dict):
    """Las notas viejas mencionaban «el registro #43» y «(antes: ...)»: se muestran con la fecha del registro."""
    match = _LEGACY_NOTE.match(note or "")
    if not match:
        return note
    verb = "Deshace" if match.group(1).startswith("Deshecho") else "Corrige"
    target = by_id.get(int(match.group(2)))
    return f"{verb} el registro del {_event_stamp(target.consumed_at)}" if target else f"{verb} un registro anterior"


def _check_same_direction(event, new_event_type: str) -> None:
    """Una entrada sigue siendo entrada y una salida sigue siendo salida: solo cambian las unidades (y el motivo de la salida)."""
    if (event.event_type == "restocked") != (new_event_type == "restocked"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Una entrada no puede pasar a ser una salida, ni una salida una entrada",
        )


def _correction_companion(reversal, by_id: dict):
    """Al corregir un registro se guardan, juntos, la reversión y el movimiento nuevo (el que sigue y es del mismo instante).
    Al deshacer no hay movimiento nuevo."""
    following = by_id.get(reversal.id + 1)
    if (
        following is not None
        and following.reverses_event_id is None
        and following.product_id == reversal.product_id
        and _naive_utc(following.consumed_at) == _naive_utc(reversal.consumed_at)
    ):
        return following
    return None


def _is_correction_companion(event, by_id: dict) -> bool:
    previous = by_id.get(event.id - 1)
    return previous is not None and previous.reverses_event_id is not None and _correction_companion(previous, by_id) is event


@router.get("/changes", response_model=list[StockChange])
async def recent_stock_changes(
    limit: int = Query(5, ge=1, le=50),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Los últimos cambios de stock del usuario, del más nuevo al más viejo.

    Incluye las entradas (ingreso de un producto existente o nuevo), las salidas y las modificaciones hechas al
    editar un producto. Cada cambio trae el stock antes y después, que se reconstruye hacia atrás desde el stock
    actual con los movimientos del producto. Las correcciones no aparecen: queda el movimiento corregido.

    `offset` salta esa cantidad de cambios (los más nuevos) para pedir las páginas siguientes.
    """
    user_id = current_user["sub"]
    products = {p.id: p for p in db.query(Product).filter(Product.user_id == user_id).all()}
    events = (
        db.query(ConsumptionEvent)
        .filter(ConsumptionEvent.user_id == user_id)
        .order_by(ConsumptionEvent.consumed_at.desc(), ConsumptionEvent.id.desc())
        .all()
    )
    by_id = {e.id: e for e in events}
    after_of: dict[int, int] = {}

    running = {product_id: product.stock for product_id, product in products.items()}
    changes: list[tuple[tuple[datetime, int], StockChange]] = []
    for event in events:
        product = products.get(event.product_id)
        if product is None:
            continue
        after = running[product.id]
        before = after - _stock_effect(event.event_type, event.quantity)
        running[product.id] = before
        after_of[event.id] = after
        producto = ProductResponse.model_validate(product, from_attributes=True)
        if event.reverses_event_id is not None:
            # Una corrección o un deshacer deja UNA entrada de «modificación» con el efecto neto (35 → 33), y el movimiento
            # corregido sigue apareciendo con su stock de entonces (20 → 35)
            companion = _correction_companion(event, by_id)
            final_after = after_of[companion.id] if companion is not None else after
            changes.append((
                (_naive_utc(event.consumed_at), 1 + (companion.id if companion is not None else event.id)),
                StockChange(
                    id=f"event-{event.id}", kind="modificacion", stock_before=before, stock_after=final_after,
                    quantity=abs(final_after - before), occurred_at=event.consumed_at, producto=producto,
                ),
            ))
            continue
        if _is_correction_companion(event, by_id):
            continue
        if (event.note or "").startswith(STOCK_EDIT_NOTE):
            kind = "modificacion"
        else:
            kind = "entrada" if event.event_type == "restocked" else "salida"
        changes.append((
            (_naive_utc(event.consumed_at), 1 + event.id),
            StockChange(
                id=f"event-{event.id}", kind=kind, stock_before=before, stock_after=after, quantity=event.quantity,
                occurred_at=event.consumed_at, producto=producto,
            ),
        ))

    # Lo que queda después de deshacer todos los movimientos es el stock con el que se cargó el producto
    for product_id, product in products.items():
        initial = running[product_id]
        if product.created_at is None or initial <= 0:
            continue
        changes.append((
            (_naive_utc(product.created_at), 0),
            StockChange(
                id=f"created-{product_id}",
                kind="entrada",
                stock_before=0,
                stock_after=initial,
                quantity=initial,
                occurred_at=product.created_at,
                producto=ProductResponse.model_validate(product, from_attributes=True),
            ),
        ))

    changes.sort(key=lambda item: item[0], reverse=True)
    return [change for _, change in changes[offset:offset + limit]]


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


@router.get("/match", response_model=list[ProductSuggestion])
async def match_products(
    q: str = Query(..., min_length=1, max_length=1000),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Los productos del usuario que se parecen a un texto leído de una etiqueta, de mejor a peor.

    A diferencia de `/suggest` (que busca dentro del nombre), compara el texto con el nombre, la marca y la
    descripción de cada producto, y tolera abreviaturas y palabras de más.
    """
    rows = db.query(Product).filter(Product.user_id == current_user["sub"]).all()
    return [_to_suggestion(p) for p, _ in matching.buscar_texto(q, rows)]


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
                await _notificate_overstock(user.firebase_token, existing, days_until_stockout, user.email, limit_days=coverage_threshold, daily_rate=result.get("daily_rate"))
            elif days_until_stockout is not None and days_until_stockout < coverage_threshold:
                await _notificate_understock(user.firebase_token, existing, days_until_stockout, user.email, limit_days=coverage_threshold, daily_rate=result.get("daily_rate"))
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

    # Las lecturas de DB son sincrónicas y baratas; lo lento es el ML, así que se
    # arman todas las entradas primero y las predicciones corren en paralelo.
    inputs = []
    for product in products:
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
        inputs.append((product, events, product_data))

    semaphore = asyncio.Semaphore(_ML_CONCURRENCY)

    async def _predict(events, product_data):
        async with semaphore:
            return await ml_client.predict(events, product_data, segment=segment)

    predictions = await asyncio.gather(*(_predict(events, data) for _, events, data in inputs))

    suggestions: list[ReposicionSuggestion] = []
    for (product, _, _), result in zip(inputs, predictions):
        coverage_threshold = product.stock_minimo or profile.stock_minimo or DEFAULT_COVERAGE_DAYS
        if not result:
            continue

        daily_rate = result.get("daily_rate") or 0.0
        days_until_stockout = result.get("days_until_stockout")
        if daily_rate <= 0 or days_until_stockout is None:
            continue
        if days_until_stockout >= coverage_threshold:
            continue

        suggested_qty = suggested_restock(daily_rate, coverage_threshold, product.stock)
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
            note=STOCK_EDIT_NOTE,
        ))
    elif stock_increased:
        db.add(ConsumptionEvent(
            product_id=product.id,
            user_id=product.user_id,
            quantity=new_stock_value - old_stock,
            event_type="restocked",
            actor_email=actor_email,
            note=STOCK_EDIT_NOTE,
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
            await _notificate_overstock(user.firebase_token, product, days_until_stockout, user.email, limit_days=coverage_threshold, daily_rate=result.get("daily_rate"))
        elif days_until_stockout is not None and days_until_stockout < coverage_threshold:
            await _notificate_understock(user.firebase_token, product, days_until_stockout, user.email, limit_days=coverage_threshold, daily_rate=result.get("daily_rate"))

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
    by_id = {e.id: e for e in events}
    return [
        {
            "id": e.id,
            "quantity": e.quantity,
            "event_type": e.event_type,
            "consumed_at": e.consumed_at,
            "note": _clean_note(e.note, by_id),
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


@router.post("/{product_id}/restock", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def restock_product(
    product_id: int,
    data: RestockRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Entrada de stock de un producto que el usuario ya tiene cargado (sin volver a cargar sus datos)."""
    user_id = current_user["sub"]
    actor_email = current_user.get("email")
    product = _get_user_product(product_id, user_id, db)
    if product.stock + data.quantity > 999999:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cantidad inválida",
        )
    product.stock += data.quantity
    db.add(ConsumptionEvent(
        product_id=product.id,
        user_id=user_id,
        quantity=data.quantity,
        event_type="restocked",
        actor_email=actor_email,
    ))
    db.commit()
    db.refresh(product)
    _log_activity(
        db, "product_updated", actor_email, user_id, actor_email,
        f"{actor_email or user_id} sumó {data.quantity} unidades a \"{product.nombre}\" (stock: {product.stock})",
    )
    user = _get_user(user_id, db)
    profile = _get_or_create_profile(user_id, db)
    result = await _check_product_state(product, user, profile, db, stock_increased=True)
    if result:
        days_until_stockout = result.get("days_until_stockout")
        coverage_threshold = product.stock_minimo or profile.stock_minimo or DEFAULT_COVERAGE_DAYS
        overstock_threshold = max(DEFAULT_OVERSTOCK_DAYS, 4 * coverage_threshold)
        if days_until_stockout is not None and days_until_stockout > overstock_threshold:
            await _notificate_overstock(user.firebase_token, product, days_until_stockout, user.email, limit_days=coverage_threshold, daily_rate=result.get("daily_rate"))
        elif days_until_stockout is not None and days_until_stockout < coverage_threshold:
            await _notificate_understock(user.firebase_token, product, days_until_stockout, user.email, limit_days=coverage_threshold, daily_rate=result.get("daily_rate"))
    return ProductResponse.model_validate(product, from_attributes=True).model_copy(update={"merged": True})


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
    _check_same_direction(event, data.event_type)

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
        note=f"Corrige el registro del {_event_stamp(event.consumed_at)}",
        reverses_event_id=event.id,
    ))
    new_event = ConsumptionEvent(
        product_id=product.id,
        user_id=product.user_id,
        quantity=data.quantity,
        event_type=data.event_type,
        actor_email=actor_email,
        note=data.note or f"Corrige el registro del {_event_stamp(event.consumed_at)}",
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
        note=f"Deshace el registro del {_event_stamp(event.consumed_at)}",
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
