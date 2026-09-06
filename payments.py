import aiosqlite
import sqlite3
import logging
import asyncio
import json
from typing import Optional, Dict, Any

from telethon import events
from telethon.tl.types import MessageActionPaymentSentMe

from notifications import NotificationService

logger = logging.getLogger("payments")

# Product Security Catalog
# In production, this should ideally be loaded from a database.
PRODUCT_CATALOG = {
    "premium_subscription": 50,
    "extra_storage": 20,
    "exclusive_content_1": 100
}

logger = logging.getLogger("payments")

class PaymentData:
    def __init__(self, charge_id: str, amount: int, currency: str, payload: str):
        self.charge_id = charge_id
        self.amount = amount
        self.currency = currency
        self.payload = payload


class OrderRepository:
    """
    Data Access Layer (Repository) for handling Orders and Payments.
    Uses aiosqlite to ensure ACID properties without blocking the async event loop.
    Includes Multi-Tenancy support and a Dead Letter Queue for resilience.
    """
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as conn:
            # Payments Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    charge_id TEXT PRIMARY KEY,
                    amount INTEGER,
                    currency TEXT,
                    payload TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Orders Table (Multi-Tenant)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT, 
                    user_id INTEGER,
                    product_id TEXT,
                    charge_id TEXT,
                    status TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(charge_id) REFERENCES payments(charge_id)
                )
            """)
            # Dead Letter Queue (DLQ) for compensating transactions
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS dead_letter_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT,
                    payload TEXT,
                    error_reason TEXT,
                    resolved BOOLEAN DEFAULT 0,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.commit()

    async def log_to_dlq(self, event_type: str, payload_dict: Dict[str, Any], error_reason: str):
        """Logs failed DB transactions to a Dead Letter Queue for later processing."""
        async with aiosqlite.connect(self.db_path) as conn:
            payload_str = json.dumps(payload_dict)
            await conn.execute("""
                INSERT INTO dead_letter_queue (event_type, payload, error_reason)
                VALUES (?, ?, ?)
            """, (event_type, payload_str, error_reason))
            await conn.commit()
            logger.critical(f"DLQ Entry Added: {event_type} - {error_reason}")

    async def is_charge_processed(self, charge_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute("SELECT charge_id FROM payments WHERE charge_id = ?", (charge_id,))
            row = await cursor.fetchone()
            return row is not None

    async def get_order_by_charge(self, charge_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM orders WHERE charge_id = ?", (charge_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_user_completed_order(self, tenant_id: str, user_id: int, product_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT * FROM orders WHERE tenant_id = ? AND user_id = ? AND product_id = ? AND status = 'COMPLETED'", 
                (tenant_id, user_id, product_id)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def update_order(self, tenant_id: str, user_id: int, product_id: str, payment_data: PaymentData) -> Dict[str, Any]:
        """
        Idempotent operation to record payment and update order status within a single transaction.
        If it fails, the event is routed to the Dead Letter Queue.
        """
        if await self.is_charge_processed(payment_data.charge_id):
            logger.info(f"Charge {payment_data.charge_id} already processed. Returning existing order.")
            order = await self.get_order_by_charge(payment_data.charge_id)
            if order:
                return order

        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            try:
                # 1. Save the Payment
                await conn.execute("""
                    INSERT INTO payments (charge_id, amount, currency, payload)
                    VALUES (?, ?, ?, ?)
                """, (payment_data.charge_id, payment_data.amount, payment_data.currency, payment_data.payload))

                # 2. Save/Update the Order with tenant_id
                cursor = await conn.execute("""
                    INSERT INTO orders (tenant_id, user_id, product_id, charge_id, status)
                    VALUES (?, ?, ?, ?, 'COMPLETED')
                """, (tenant_id, user_id, product_id, payment_data.charge_id))
                
                order_id = cursor.lastrowid
                await conn.commit()

                cursor = await conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
                row = await cursor.fetchone()
                return dict(row) if row else {}

            except sqlite3.Error as e:
                await conn.rollback()
                logger.error(f"Database error during order update: {e}")
                
                # Compensating Transaction: Log to DLQ
                dlq_payload = {
                    "tenant_id": tenant_id, "user_id": user_id, "product_id": product_id,
                    "charge_id": payment_data.charge_id, "amount": payment_data.amount
                }
                # We do not await this on the same connection object since it just rolled back.
                asyncio.create_task(self.log_to_dlq("payment_success_db_fail", dlq_payload, str(e)))
                raise

    async def refund_order(self, charge_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as conn:
            try:
                cursor = await conn.execute("UPDATE orders SET status = 'REFUNDED' WHERE charge_id = ?", (charge_id,))
                await conn.commit()
                return cursor.rowcount > 0
            except sqlite3.Error as e:
                await conn.rollback()
                logger.error(f"Database error during refund process: {e}")
                raise


class PaymentService:
    """
    Payment Service Layer (Facade) for orchestrating the payment flow.
    Integrates Notification Service and handles Tenant scoping.
    """
    def __init__(self, client, repo: OrderRepository, notification_service: Optional[NotificationService] = None):
        self.client = client
        self.repo = repo
        self.notifier = notification_service

    async def initialize(self):
        await self.repo.init_db()

    async def process_purchase(self, tenant_id: str, user_id: int, product_id: str, required_stars: int) -> Dict[str, Any]:
        # 1. Product Security Check
        actual_price = PRODUCT_CATALOG.get(product_id)
        if not actual_price:
            return {"status": "Invalid Product", "error": f"Product '{product_id}' not found in catalog."}
            
        if required_stars < actual_price:
            logger.warning(f"Price mismatch: user {user_id} tried to pay {required_stars} for {product_id} (requires {actual_price})")
            return {"status": "Security Error", "error": "Amount specified is less than the product price."}

        # 2. Status Check
        existing_order = await self.repo.get_user_completed_order(tenant_id, user_id, product_id)
        if existing_order:
            logger.info(f"User {user_id} (Tenant: {tenant_id}) already paid for {product_id}. Bypassing.")
            return {"status": "Already Paid", "order": existing_order}

        # 3. API Call
        try:
            logger.info(f"Generating invoice for user {user_id}, product {product_id}")
            # Ensure the client is a Bot to send invoices
            invoice_payload = await self.client.send_invoice(user_id=user_id, product_id=product_id, amount=actual_price)
        except Exception as e:
            logger.error(f"Failed to generate invoice: {e}")
            if self.notifier:
                await self.notifier.send_failure_alert(user_id, "We couldn't generate your invoice at this time.")
            return {"status": "Invoice Generation Failed", "error": str(e)}

        # 4. Wait for Successful Payment using Telethon Event Listener
        timeout = 300 
        payment_future = asyncio.Future()

        async def payment_handler(event):
            # Check if the message action is a payment confirmation
            if getattr(event.message, 'action', None) and isinstance(event.message.action, MessageActionPaymentSentMe):
                # We can extract payload from the action if needed
                charge_id = event.message.action.charge.id
                amount = event.message.action.total_amount
                currency = event.message.action.currency
                payload = getattr(event.message.action, 'payload', 'N/A')
                
                payment_data = PaymentData(
                    charge_id=charge_id, 
                    amount=amount, 
                    currency=currency, 
                    payload=payload
                )
                if not payment_future.done():
                    payment_future.set_result(payment_data)

        # Register the temporary event handler
        self.client.add_event_handler(payment_handler, events.NewMessage(chats=user_id))
        payment_data = None

        try:
            logger.info("Waiting for payment callback...")
            payment_data = await asyncio.wait_for(payment_future, timeout=timeout)
        except asyncio.TimeoutError:
            if self.notifier:
                await self.notifier.send_failure_alert(user_id, "Your payment session timed out.")
            return {"status": "Payment Timed Out"}
        except Exception as e:
            logger.error(f"Error waiting for payment: {e}")
            if self.notifier:
                await self.notifier.send_failure_alert(user_id, "We encountered an error while verifying your payment.")
            return {"status": "Payment Failed", "error": str(e)}
        finally:
            # Always remove the handler to prevent memory leaks
            self.client.remove_event_handler(payment_handler)

        if not payment_data:
            return {"status": "Payment Failed", "error": "Unknown error."}

        # 4. State Update (Repository Call with DLQ Resilience)
        try:
            order = await self.repo.update_order(tenant_id, user_id, product_id, payment_data)
            logger.info(f"Order successfully processed and persisted for user {user_id}.")
            
            # 5. Success Notification
            if self.notifier:
                await self.notifier.send_confirmation(user_id, order)
                
            return {"status": "Success", "order": order}
            
        except Exception as e:
            logger.error(f"Failed to persist order: {e}")
            # The payment succeeded but DB failed. It's in the DLQ. We notify support and the user.
            if self.notifier:
                await self.notifier.send_failure_alert(user_id, "Your payment was received, but there was an error updating your order. Support has been notified and will resolve this shortly.")
            return {"status": "Persistence Failed, Added to DLQ", "error": str(e)}
            
    async def process_refund(self, user_id: int, charge_id: str) -> Dict[str, Any]:
        """
        Process a refund and notify the user.
        """
        try:
            success = await self.repo.refund_order(charge_id)
            if success:
                if self.notifier:
                    await self.notifier.send_refund_notice(user_id, charge_id)
                return {"status": "Refunded", "charge_id": charge_id}
            else:
                return {"status": "Refund Failed", "error": "Order not found or already refunded."}
        except Exception as e:
            logger.error(f"Failed to process refund for {charge_id}: {e}")
            return {"status": "Refund Error", "error": str(e)}
