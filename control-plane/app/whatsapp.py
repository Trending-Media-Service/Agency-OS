import os
import logging
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import OpRow
from app.kernel import loop

logger = logging.getLogger(__name__)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_APPROVER_PHONE = os.getenv("WHATSAPP_APPROVER_PHONE")
WHATSAPP_TEMPLATE_NAME = os.getenv("WHATSAPP_TEMPLATE_NAME", "agency_os_approval")


async def send_approval_card(op: OpRow) -> bool:
    """Sends an approval card to the configured WhatsApp phone number."""
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID or not WHATSAPP_APPROVER_PHONE:
        logger.warning("WhatsApp config missing. Skipping send.")
        return False

    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    # Format parameters for template body variables
    # {{1}} = Summary (action)
    # {{2}} = Preview Summary
    # {{3}} = Cost Estimate
    # {{4}} = Severity/Reversibility
    cost_str = (f"{op.cost_amount_minor/100:.2f} {op.cost_currency}/mo"
                if op.cost_amount_minor else "0.00 INR/mo")
    severity_str = f"Impact: {op.impact}, Reversibility: {op.reversibility}"

    payload = {
        "messaging_product": "whatsapp",
        "to": WHATSAPP_APPROVER_PHONE,
        "type": "template",
        "template": {
            "name": WHATSAPP_TEMPLATE_NAME,
            "language": {"code": "en_US"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": op.action},
                        {"type": "text", "text": op.preview_summary or "No preview available"},
                        {"type": "text", "text": cost_str},
                        {"type": "text", "text": severity_str},
                    ]
                },
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": "0",
                    "parameters": [
                        {"type": "payload", "payload": f"approve_{op.id}"}
                    ]
                },
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": "1",
                    "parameters": [
                        {"type": "payload", "payload": f"reject_{op.id}"}
                    ]
                }
            ]
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                logger.info(f"WhatsApp approval card sent for Op {op.id}")
                return True
            else:
                logger.error(f"Failed to send WhatsApp card: {resp.status_code} - {resp.text}")
                return False
    except Exception as e:
        logger.error(f"Error calling WhatsApp API: {e}")
        return False


async def send_whatsapp_card_task(op_id: str, session_maker):
    """Background task to fetch OpRow and send WhatsApp card."""
    async with session_maker() as s:
        row = await s.get(OpRow, op_id)
        if row:
            await send_approval_card(row)
        else:
            logger.error(f"Op {op_id} not found in background task")


async def execute_decision(op_id: str, decision: str, session_maker, reason: str | None = None):
    """Executes decision (approve/reject/modify) in a transaction and triggers drain if approved."""
    async with session_maker() as s:
        async with s.begin():
            row = await s.get(OpRow, op_id)
            if not row:
                logger.error(f"Op {op_id} not found for WhatsApp decision")
                return
            await loop.decide(
                s, row,
                decision=decision,
                actor="chandan",
                role="AGENCY_OWNER",
                surface="whatsapp",
                reason=reason
            )
            # Transaction commits on exit
    if decision == "approve":
        # Run local drain worker directly since we are already in background task
        from app.tasks import _drain_local_task
        await _drain_local_task(session_maker)


async def handle_whatsapp_button_payload(payload: str, session_maker):
    """Handles quick reply button click payload."""
    if payload.startswith("approve_"):
        op_id = payload.replace("approve_", "")
        await execute_decision(op_id, "approve", session_maker)
    elif payload.startswith("reject_"):
        op_id = payload.replace("reject_", "")
        await execute_decision(op_id, "reject", session_maker)


async def handle_whatsapp_text_reply(text_body: str, session_maker):
    """Handles text reply (e.g. modify command)."""
    # Expected format: "modify <reason>" or "modify: <reason>" (case-insensitive)
    normalized = text_body.strip().lower()
    if normalized.startswith("modify"):
        # Extract the reason/modification text
        reason = text_body[len("modify"):].strip(" :")

        # Query for the latest Op in AWAITING_APPROVAL state to apply the modification to
        async with session_maker() as s:
            result = await s.execute(
                select(OpRow)
                .where(OpRow.state == "AWAITING_APPROVAL")
                .order_by(OpRow.created_at.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            if not row:
                logger.warning("Received modify command but no Op is AWAITING_APPROVAL")
                return
            op_id = row.id

        await execute_decision(op_id, "modify", session_maker, reason=reason)
    else:
        logger.info(f"Ignored non-command WhatsApp text reply: {text_body}")


async def process_whatsapp_webhook_payload(body: dict, session_maker):
    """Parses and processes Meta webhook POST payload."""
    try:
        entries = body.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                for msg in messages:
                    sender = msg.get("from")
                    if WHATSAPP_APPROVER_PHONE and sender != WHATSAPP_APPROVER_PHONE:
                        logger.warning(f"Received message from unauthorized sender: {sender}")
                        continue

                    msg_type = msg.get("type")
                    if msg_type == "button":
                        button = msg.get("button", {})
                        payload = button.get("payload", "")
                        await handle_whatsapp_button_payload(payload, session_maker)
                    elif msg_type == "text":
                        text_body = msg.get("text", {}).get("body", "")
                        await handle_whatsapp_text_reply(text_body, session_maker)
    except Exception as e:
        logger.error(f"Error processing WhatsApp webhook payload: {e}", exc_info=True)
