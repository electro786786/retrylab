import asyncio
from fastapi import FastAPI, Depends, Header, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.dialects.postgresql import insert
import json
from app.database import get_db, engine, Base
from app.models import IdempotencyKey, Customer, Payment, Refund, Transfer
from app.schemas import (CustomerCreate, CustomerResponse, PaymentCreate, PaymentResponse,
                         RefundCreate, RefundResponse, TransferCreate, TransferResponse)
from app.config import settings
from sqlalchemy.exc import IntegrityError

app = FastAPI(title="Bug Zoo Payments API")

@app.on_event("startup")
async def startup_event():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def check_idempotency(request: Request, db: AsyncSession, idempotency_key: str, user_id: str):
    if settings.bug_2_no_idempotency:
        return None # Do nothing, proceed to business logic

    endpoint = request.url.path

    if settings.bug_1_race_condition:
        # Bug 1: Check-then-act race on the idempotency key (SELECT then INSERT)
        stmt = select(IdempotencyKey).where(IdempotencyKey.key == idempotency_key)
        if not settings.bug_4_unscoped_key:
            stmt = stmt.where(IdempotencyKey.user_id == user_id, IdempotencyKey.endpoint == endpoint)
        
        result = await db.execute(stmt)
        existing_key = result.scalar_one_or_none()
        
        if existing_key:
            if existing_key.status_code is None:
                raise HTTPException(status_code=409, detail="Request in progress")
            return JSONResponse(status_code=existing_key.status_code, content=existing_key.response_body)
        
        # INSERT
        new_key = IdempotencyKey(key=idempotency_key, user_id=user_id, endpoint=endpoint)
        db.add(new_key)
        try:
            await db.flush() # Could raise IntegrityError if unique constraint is hit by another concurrent request
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=409, detail="Concurrent request detected")
        
        return None
    else:
        if settings.bug_3_missing_unique_constraint:
            conflict_index = []
        elif settings.bug_4_unscoped_key:
            conflict_index = ['key']
        else:
            conflict_index = ['key', 'user_id', 'endpoint']
            
        stmt = insert(IdempotencyKey).values(
            key=idempotency_key,
            user_id=user_id,
            endpoint=endpoint
        ).on_conflict_do_nothing(index_elements=conflict_index if conflict_index else None)
        
        # Wait, if bug_3 is on (missing unique constraint), on_conflict_do_nothing without an index will fail in Postgres
        # But if bug 3 is on, it's a bug! So maybe we just do a regular insert if bug 3 is on, causing duplication.
        if settings.bug_3_missing_unique_constraint:
            new_key = IdempotencyKey(key=idempotency_key, user_id=user_id, endpoint=endpoint)
            db.add(new_key)
            await db.flush()
        else:
            result = await db.execute(stmt.returning(IdempotencyKey.id))
            inserted_id = result.scalar()
            if not inserted_id:
                # It means it conflicted and was not inserted! Wait, we need to return the cached response.
                fetch_stmt = select(IdempotencyKey).where(IdempotencyKey.key == idempotency_key)
                if not settings.bug_4_unscoped_key:
                    fetch_stmt = fetch_stmt.where(IdempotencyKey.user_id == user_id, IdempotencyKey.endpoint == endpoint)
                
                res = await db.execute(fetch_stmt)
                existing_key = res.scalar_one_or_none()
                if not existing_key:
                    # Bug 4 logic might hide the key!
                    if settings.bug_4_unscoped_key:
                        fetch_stmt_unscoped = select(IdempotencyKey).where(IdempotencyKey.key == idempotency_key)
                        res = await db.execute(fetch_stmt_unscoped)
                        existing_key = res.scalar_one_or_none()
                        
                if existing_key and existing_key.status_code is None:
                    raise HTTPException(status_code=409, detail="Request in progress")
                elif existing_key:
                    return JSONResponse(status_code=existing_key.status_code, content=existing_key.response_body)
                else:
                    raise HTTPException(status_code=500, detail="Key conflict but not found")
                    
        return None

async def save_idempotency_result(db: AsyncSession, idempotency_key: str, user_id: str, endpoint: str, status_code: int, response_body: dict):
    if settings.bug_2_no_idempotency:
        return

    # Update the key record
    stmt = select(IdempotencyKey).where(IdempotencyKey.key == idempotency_key)
    if not settings.bug_4_unscoped_key:
        stmt = stmt.where(IdempotencyKey.user_id == user_id, IdempotencyKey.endpoint == endpoint)
        
    result = await db.execute(stmt)
    key_record = result.scalars().first()
    
    if key_record:
        key_record.status_code = status_code
        key_record.response_body = response_body
        await db.flush()

@app.post("/customers", response_model=CustomerResponse)
async def create_customer(
    customer: CustomerCreate, 
    request: Request,
    idempotency_key: str = Header(...),
    user_id: str = Header(default="test-user"),
    db: AsyncSession = Depends(get_db)
):
    cached_response = await check_idempotency(request, db, idempotency_key, user_id)
    if cached_response:
        return cached_response

    new_customer = Customer(name=customer.name, email=customer.email)
    db.add(new_customer)
    await db.flush()
    
    response_data = {"id": new_customer.id, "name": new_customer.name, "email": new_customer.email}
    await save_idempotency_result(db, idempotency_key, user_id, request.url.path, 200, response_data)
    await db.commit()
    
    return response_data

@app.post("/payments", response_model=PaymentResponse)
async def create_payment(
    payment: PaymentCreate, 
    request: Request,
    idempotency_key: str = Header(...),
    user_id: str = Header(default="test-user"),
    db: AsyncSession = Depends(get_db)
):
    cached_response = await check_idempotency(request, db, idempotency_key, user_id)
    if cached_response:
        return cached_response

    new_payment = Payment(customer_id=payment.customer_id, amount=payment.amount, currency=payment.currency)
    db.add(new_payment)
    await db.flush()
    
    response_data = {"id": new_payment.id, "customer_id": new_payment.customer_id, "amount": new_payment.amount, "currency": new_payment.currency, "status": new_payment.status}
    await save_idempotency_result(db, idempotency_key, user_id, request.url.path, 200, response_data)
    await db.commit()
    
    return response_data

@app.post("/refunds", response_model=RefundResponse)
async def create_refund(
    refund: RefundCreate, 
    request: Request,
    idempotency_key: str = Header(...),
    user_id: str = Header(default="test-user"),
    db: AsyncSession = Depends(get_db)
):
    cached_response = await check_idempotency(request, db, idempotency_key, user_id)
    if cached_response:
        return cached_response

    new_refund = Refund(payment_id=refund.payment_id, amount=refund.amount)
    db.add(new_refund)
    await db.flush()
    
    response_data = {"id": new_refund.id, "payment_id": new_refund.payment_id, "amount": new_refund.amount}
    await save_idempotency_result(db, idempotency_key, user_id, request.url.path, 200, response_data)
    await db.commit()
    
    return response_data

@app.post("/transfers", response_model=TransferResponse)
async def create_transfer(
    transfer: TransferCreate, 
    request: Request,
    idempotency_key: str = Header(...),
    user_id: str = Header(default="test-user"),
    db: AsyncSession = Depends(get_db)
):
    cached_response = await check_idempotency(request, db, idempotency_key, user_id)
    if cached_response:
        return cached_response

    new_transfer = Transfer(destination_id=transfer.destination_id, amount=transfer.amount)
    db.add(new_transfer)
    await db.flush()
    
    response_data = {"id": new_transfer.id, "destination_id": new_transfer.destination_id, "amount": new_transfer.amount}
    await save_idempotency_result(db, idempotency_key, user_id, request.url.path, 200, response_data)
    await db.commit()
    
    return response_data
