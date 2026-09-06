import logging
import asyncio
from typing import Dict, Any

logger = logging.getLogger("notifications")

class NotificationService:
    """
    Service responsible for sending transactional notifications to users.
    Can be extended to support Email, SMS, Push Notifications, etc.
    """
    def __init__(self, telegram_client):
        self.client = telegram_client

    async def send_confirmation(self, user_id: int, order_details: Dict[str, Any]) -> bool:
        """Sends a success notification for a completed order."""
        message = (
            f"🎉 <b>Payment Successful!</b>\n\n"
            f"Thank you for your purchase.\n"
            f"Product: {order_details.get('product_id', 'Unknown')}\n"
            f"Order ID: {order_details.get('id', 'N/A')}\n"
            f"Status: {order_details.get('status', 'COMPLETED')}"
        )
        return await self._send_telegram_message(user_id, message)

    async def send_refund_notice(self, user_id: int, charge_id: str) -> bool:
        """Sends a notification for a refunded order."""
        message = (
            f"💸 <b>Refund Processed</b>\n\n"
            f"Your payment with charge ID {charge_id} has been fully refunded. "
            f"The funds should be returned to your account shortly."
        )
        return await self._send_telegram_message(user_id, message)

    async def send_failure_alert(self, user_id: int, reason: str) -> bool:
        """Sends a notification if something went wrong during the transaction."""
        message = (
            f"⚠️ <b>Transaction Alert</b>\n\n"
            f"We encountered an issue processing your request: {reason}\n"
            f"Please contact support if you need assistance."
        )
        return await self._send_telegram_message(user_id, message)

    async def _send_telegram_message(self, user_id: int, text: str) -> bool:
        """Helper to send the actual message via Telegram Client."""
        try:
            logger.info(f"Sending notification to {user_id}")
            # Placeholder: In a real bot, use client.send_message(user_id, text, parse_mode='html')
            # Since telegrab is primarily a user client, we assume it can send messages to the user (e.g. Saved Messages or directly)
            if hasattr(self.client, 'send_message'):
                await self.client.send_message(user_id, text, parse_mode='html')
            return True
        except Exception as e:
            logger.error(f"Failed to send notification to {user_id}: {e}")
            return False
