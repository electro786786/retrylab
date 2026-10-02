from pydantic import BaseModel

class CustomerCreate(BaseModel):
    name: str
    email: str

class CustomerResponse(BaseModel):
    id: str
    name: str
    email: str

class PaymentCreate(BaseModel):
    customer_id: str
    amount: int
    currency: str = "USD"

class PaymentResponse(BaseModel):
    id: str
    customer_id: str
    amount: int
    currency: str
    status: str

class RefundCreate(BaseModel):
    payment_id: str
    amount: int

class RefundResponse(BaseModel):
    id: str
    payment_id: str
    amount: int

class TransferCreate(BaseModel):
    destination_id: str
    amount: int

class TransferResponse(BaseModel):
    id: str
    destination_id: str
    amount: int
