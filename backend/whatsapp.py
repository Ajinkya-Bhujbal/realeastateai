"""
WhatsApp integration - send messages and receive webhooks.
Supports WhatsApp Business API (Cloud API via Meta).
"""
import requests
import os
from typing import Optional

# Configuration - set via environment variables or config
WA_API_URL = os.getenv("WA_API_URL", "https://graph.facebook.com/v18.0")
WA_PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID", "")
WA_ACCESS_TOKEN = os.getenv("WA_ACCESS_TOKEN", "")
WA_VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN", "leadbot_verify_2024")


def send_whatsapp_message(to_phone: str, message: str = "", media_id: str = None, media_type: str = "image") -> dict:
    """
    Send a WhatsApp text or media message via Cloud API.
    to_phone: recipient phone with country code (e.g., 919876543210)
    media_id: Optional WhatsApp media ID
    media_type: 'image', 'video', 'document', or 'audio'
    """
    if not WA_PHONE_NUMBER_ID or not WA_ACCESS_TOKEN:
        return {
            "success": False,
            "error": "WhatsApp not configured. Set WA_PHONE_NUMBER_ID and WA_ACCESS_TOKEN env vars.",
            "mock": True,
            "message": message,
            "to": to_phone,
        }

    # Ensure phone has country code
    phone = to_phone.strip().replace("+", "").replace(" ", "").replace("-", "")
    if len(phone) == 10:
        phone = "91" + phone  # Default to India

    url = f"{WA_API_URL}/{WA_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WA_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
    }
    if media_id:
        payload["type"] = media_type
        payload[media_type] = {"id": media_id}
        if message and media_type in ["image", "video", "document"]:
            payload[media_type]["caption"] = message
    else:
        payload["type"] = "text"
        payload["text"] = {"body": message}

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30)
        data = r.json()
        if r.status_code == 200:
            msg_id = data.get("messages", [{}])[0].get("id", "")
            return {"success": True, "message_id": msg_id, "to": phone}
        else:
            return {"success": False, "error": data, "status_code": r.status_code}
    except Exception as e:
        return {"success": False, "error": str(e)}


def upload_whatsapp_media(file_bytes: bytes, mime_type: str, filename: str) -> Optional[str]:
    """Upload media to WhatsApp API and return the media ID."""
    if not WA_PHONE_NUMBER_ID or not WA_ACCESS_TOKEN:
        return "mock_media_id_123"

    url = f"{WA_API_URL}/{WA_PHONE_NUMBER_ID}/media"
    headers = {
        "Authorization": f"Bearer {WA_ACCESS_TOKEN}"
    }
    files = {
        "file": (filename, file_bytes, mime_type)
    }
    data = {
        "messaging_product": "whatsapp"
    }

    try:
        r = requests.post(url, headers=headers, files=files, data=data, timeout=60)
        if r.status_code == 200:
            return r.json().get("id")
        else:
            print(f"WA Media upload failed: {r.json()}")
            return None
    except Exception as e:
        print(f"WA Media upload error: {e}")
        return None


def send_whatsapp_template(to_phone: str, template_name: str, language: str = "en") -> dict:
    """Send a WhatsApp template message (for first-time contacts)."""
    if not WA_PHONE_NUMBER_ID or not WA_ACCESS_TOKEN:
        return {"success": False, "error": "WhatsApp not configured", "mock": True}

    phone = to_phone.strip().replace("+", "").replace(" ", "").replace("-", "")
    if len(phone) == 10:
        phone = "91" + phone

    url = f"{WA_API_URL}/{WA_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WA_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
        },
    }

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30)
        data = r.json()
        return {"success": r.status_code == 200, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}


def verify_webhook(mode: str, token: str, challenge: str) -> Optional[str]:
    """Verify WhatsApp webhook subscription."""
    if mode == "subscribe" and token == WA_VERIFY_TOKEN:
        return challenge
    return None


def parse_webhook_message(payload: dict) -> Optional[dict]:
    """
    Parse incoming WhatsApp webhook payload.
    Returns dict with: from_phone, message_text, message_id, timestamp
    """
    try:
        entry = payload.get("entry", [])
        if not entry:
            return None

        changes = entry[0].get("changes", [])
        if not changes:
            return None

        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return None

        msg = messages[0]
        contacts = value.get("contacts", [{}])
        sender_name = contacts[0].get("profile", {}).get("name", "") if contacts else ""

        result = {
            "from_phone": msg.get("from", ""),
            "message_text": "",
            "message_id": msg.get("id", ""),
            "timestamp": msg.get("timestamp", ""),
            "sender_name": sender_name,
            "type": msg.get("type", "text"),
        }

        if msg.get("type") == "text":
            result["message_text"] = msg.get("text", {}).get("body", "")
        elif msg.get("type") == "interactive":
            interactive = msg.get("interactive", {})
            if interactive.get("type") == "button_reply":
                result["message_text"] = interactive.get("button_reply", {}).get("title", "")
            elif interactive.get("type") == "list_reply":
                result["message_text"] = interactive.get("list_reply", {}).get("title", "")
        else:
            result["message_text"] = f"[{msg.get('type', 'unknown')} message]"

        return result
    except Exception as e:
        print(f"Webhook parse error: {e}")
        return None
