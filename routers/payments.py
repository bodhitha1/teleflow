import logging
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Depends
import aiosqlite

from core.state import AppState, get_current_state
from payments import OrderRepository, PaymentService
from notifications import NotificationService

logger = logging.getLogger("web_app")
router = APIRouter(prefix="/api", tags=["Payments"])

order_repo = OrderRepository("payments.db")

class PurchaseRequest(BaseModel):
    product_id: str
    required_stars: int
    tenant_id: str = "default"

class RefundRequest(BaseModel):
    charge_id: str

@router.post("/purchase")
async def api_purchase(req: PurchaseRequest, state: AppState = Depends(get_current_state)):
    if not state.client or not await state.client.is_user_authorized():
        raise HTTPException(status_code=401, detail="Telegram client is not authorized. Log in first.")

    notifier = NotificationService(state.client)
    payment_service = PaymentService(state.client, order_repo, notifier)
    me = await state.client.get_me()

    result = await payment_service.process_purchase(
        tenant_id=req.tenant_id,
        user_id=me.id,
        product_id=req.product_id,
        required_stars=req.required_stars
    )

    if "Error" in result.get("status", "") or "Failed" in result.get("status", "") or "Timed Out" in result.get("status", ""):
        raise HTTPException(status_code=400, detail=result)

    return result

@router.post("/refund")
async def api_refund(req: RefundRequest, state: AppState = Depends(get_current_state)):
    if not state.client or not await state.client.is_user_authorized():
        raise HTTPException(status_code=401, detail="Telegram client is not authorized. Log in first.")

    notifier = NotificationService(state.client)
    payment_service = PaymentService(state.client, order_repo, notifier)
    me = await state.client.get_me()

    result = await payment_service.process_refund(
        user_id=me.id,
        charge_id=req.charge_id
    )

    if "Error" in result.get("status", "") or "Failed" in result.get("status", ""):
        raise HTTPException(status_code=400, detail=result)

    return result

@router.get("/revenue")
async def api_revenue():
    try:
        async with aiosqlite.connect(order_repo.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT 
                    COUNT(DISTINCT o.id) as total_orders, 
                    SUM(p.amount) as total_revenue
                FROM orders o
                JOIN payments p ON o.charge_id = p.charge_id
                WHERE o.status = 'COMPLETED'
            """)
            row = await cursor.fetchone()
            return {
                "status": "success",
                "total_orders": row['total_orders'] or 0,
                "total_revenue": row['total_revenue'] or 0
            }
    except Exception as e:
        logger.error(f"Failed to fetch revenue metrics: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
