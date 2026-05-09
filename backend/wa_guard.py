"""
WhatsApp Safety Guard — controls whether messages are sent to real leads.

Live Mode OFF (default): Only whitelisted phones in WA_WHITELIST_PHONES receive messages.
Live Mode ON:            All leads receive messages.
"""
import os
import threading

_lock = threading.Lock()
_live_mode = False  # Default OFF — safe for testing


def is_live_mode() -> bool:
    """Check if live messaging is enabled."""
    with _lock:
        return _live_mode


def set_live_mode(enabled: bool):
    """Enable or disable live messaging."""
    global _live_mode
    with _lock:
        _live_mode = enabled
    print(f"[WA Guard] Live mode {'ON ⚡' if enabled else 'OFF 🔒'}")


def get_whitelist() -> set:
    """Get the set of whitelisted phone numbers (last 10 digits)."""
    import dotenv
    dotenv.load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)
    raw = os.getenv("WA_WHITELIST_PHONES", "")
    phones = set()
    for p in raw.split(","):
        p = p.strip().replace("+", "").replace(" ", "").replace("-", "")
        if p:
            phones.add(p[-10:])  # Normalize to last 10 digits
    return phones


def can_send_to(phone: str) -> bool:
    """
    Check if we are allowed to send a message to this phone number.
    Returns True if:
      - Live mode is ON, OR
      - The phone is in the whitelist
    """
    if is_live_mode():
        return True
    # Normalize phone to last 10 digits
    normalized = phone.strip().replace("+", "").replace(" ", "").replace("-", "")
    if len(normalized) > 10:
        normalized = normalized[-10:]
    return normalized in get_whitelist()
