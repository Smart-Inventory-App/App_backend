from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import Transaction
from app.schemas.user import TransactionResponse, TransactionBase

router = APIRouter(
    prefix="/transactions",
    tags=["transactions"],
)


@router.get("/", response_model=list[TransactionResponse])
async def list_transactions(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all transactions for current user"""
    transactions = db.query(Transaction).filter(
        Transaction.user_id == int(current_user["user_id"])
    ).all()
    return transactions


@router.post("/", response_model=TransactionResponse)
async def create_transaction(
    transaction: TransactionBase,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new transaction"""
    new_transaction = Transaction(
        user_id=int(current_user["user_id"]),
        amount=transaction.amount,
        description=transaction.description,
    )
    db.add(new_transaction)
    db.commit()
    db.refresh(new_transaction)
    return new_transaction


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a specific transaction"""
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id,
        Transaction.user_id == int(current_user["user_id"]),
    ).first()
    
    if not transaction:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found",
        )
    
    return transaction
