"""
Email parser - extracts lead info from Housing.com, 99acres, MagicBricks emails.
Also supports Gmail API ingestion.
"""
import re
import imaplib
import email
from email.header import decode_header
from typing import Optional


def parse_lead_from_email(subject: str, body: str, sender: str = "") -> dict:
    """
    Parse lead information from a real estate portal email.
    Returns dict with: name, phone, email, source, budget, location, property_type, notes
    """
    result = {
        "name": "",
        "phone": "",
        "email": "",
        "source": detect_source(sender, subject, body),
        "budget_min": None,
        "budget_max": None,
        "preferred_location": "",
        "property_type": "",
        "notes": "",
    }

    # Extract name
    result["name"] = extract_name(body, subject)

    # Extract phone
    result["phone"] = extract_phone(body)

    # Extract email
    result["email"] = extract_email(body, sender)

    # Extract budget
    result["budget_min"], result["budget_max"] = extract_budget(body)

    # Extract location
    result["preferred_location"] = extract_location(body, subject)

    # Extract property type
    result["property_type"] = extract_property_type(body, subject)

    # Notes = trimmed raw body
    result["notes"] = body[:500] if body else ""

    return result


def detect_source(sender: str, subject: str, body: str) -> str:
    """Detect which portal the lead came from."""
    combined = f"{sender} {subject} {body}".lower()
    if "housing.com" in combined:
        return "housing"
    elif "99acres" in combined:
        return "99acres"
    elif "magicbricks" in combined or "magic bricks" in combined:
        return "magicbricks"
    return "email"


def extract_name(body: str, subject: str) -> str:
    """Extract name from email body."""
    # Split body into lines for line-by-line matching
    for line in body.split('\n'):
        line = line.strip()
        match = re.match(r"(?:name|buyer|client|enquiry by|contact person)\s*[:\-–]\s*(.+)", line, re.IGNORECASE)
        if match:
            name = match.group(1).strip().rstrip('.,')
            # Only take alphabetic words
            name = ' '.join(w for w in name.split() if re.match(r'^[A-Za-z]+$', w))
            if name:
                return name[:60]

    # Try "Mr./Mrs." pattern
    match = re.search(r"(?:Mr\.|Mrs\.|Ms\.)\s+([A-Za-z]+(?:\s+[A-Za-z]+){0,3})", body)
    if match:
        return match.group(1).strip()

    # Try subject line
    match = re.search(r"(?:enquiry|inquiry|lead)\s+(?:from|by)\s+([A-Za-z]+(?:\s+[A-Za-z]+){0,2})", subject, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    return "Unknown"


def extract_phone(body: str) -> str:
    """Extract Indian phone number from email body."""
    patterns = [
        r"(?:phone|mobile|contact|cell|tel|mob)\s*[:\-–]\s*\+?(\d[\d\s\-]{8,14})",
        r"\+91[\s\-]?(\d{10})",
        r"(?<!\d)(\d{10})(?!\d)",
        r"(?<!\d)(\d{5}[\s\-]\d{5})(?!\d)",
    ]
    for pattern in patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            phone = re.sub(r"[\s\-]", "", match.group(1))
            if len(phone) >= 10:
                return phone[-10:]  # last 10 digits
    return ""


def extract_email(body: str, sender: str) -> str:
    """Extract email address from body or sender."""
    match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", body)
    if match:
        found = match.group(0).lower()
        # Skip portal emails
        if not any(portal in found for portal in ["housing.com", "99acres", "magicbricks"]):
            return found

    # Fallback to sender
    if sender:
        match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", sender)
        if match:
            return match.group(0).lower()
    return ""


def extract_budget(body: str) -> tuple:
    """Extract budget range from email body. Returns (min, max) in lakhs."""
    # Common patterns in Indian real estate emails
    patterns = [
        # "50-80 Lakhs" or "50 - 80 Lakhs"
        r"(\d+(?:\.\d+)?)\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)\s*(?:lac|lakh|lacs|lakhs)",
        # "50 Lakhs to 1 Crore"
        r"(\d+(?:\.\d+)?)\s*(?:lac|lakh|lacs|lakhs)\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)\s*(?:lac|lakh|lacs|lakhs|cr|crore|crores)",
        # "1 Cr - 2 Cr"
        r"(\d+(?:\.\d+)?)\s*(?:cr|crore|crores)\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)\s*(?:cr|crore|crores)",
        # "Budget: 50-80 Lakhs" or "Budget: 50 Lakhs"
        r"budget\s*[:\-–]\s*(?:Rs\.?\s*)?(\d+(?:\.\d+)?)\s*(?:to|-|–)?\s*(\d+(?:\.\d+)?)?\s*(?:lac|lakh|lacs|lakhs|cr|crore|crores)",
    ]

    for pattern in patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            groups = match.groups()
            vals = []
            for g in groups:
                if g:
                    try:
                        vals.append(float(g))
                    except ValueError:
                        pass
            if len(vals) >= 2:
                return (vals[0], vals[1])
            elif len(vals) == 1:
                return (vals[0], vals[0])
    return (None, None)


def extract_location(body: str, subject: str) -> str:
    """Extract location from email body or subject."""
    # Line-by-line matching first
    for line in body.split('\n'):
        line = line.strip()
        match = re.match(r"(?:location|area|locality|sector)\s*[:\-–]\s*(.+)", line, re.IGNORECASE)
        if match:
            loc = match.group(1).strip().rstrip('.,')
            if 3 < len(loc) < 100:
                return loc

    # Try subject patterns
    combined = f"{subject}\n{body}"
    patterns = [
        r"(?:property in|flat in|house in|apartment in|villa in)\s+([A-Za-z\s,]+?)(?:\.|,\s*(?:budget|phone|name)|\n|$)",
        r"(?:in)\s+([A-Z][a-z]+(?:\s*,\s*[A-Z][a-z]+)?)\s*(?:for|under|\.|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, combined, re.IGNORECASE)
        if match:
            loc = match.group(1).strip()
            if 3 < len(loc) < 100:
                return loc
    return ""


def extract_property_type(body: str, subject: str) -> str:
    """Extract property type from email content."""
    combined = f"{subject} {body}".lower()
    types = {
        "apartment": ["apartment", "flat", "1bhk", "2bhk", "3bhk", "4bhk", "1 bhk", "2 bhk", "3 bhk", "4 bhk"],
        "villa": ["villa", "bungalow", "independent house", "duplex", "row house"],
        "plot": ["plot", "land", "site"],
        "office": ["office", "commercial", "shop", "showroom"],
    }
    for ptype, keywords in types.items():
        if any(kw in combined for kw in keywords):
            return ptype
    return ""


def fetch_gmail_leads(
    gmail_user: str,
    gmail_app_password: str,
    max_emails: int = 20,
    folder: str = "INBOX",
) -> list:
    """
    Fetch leads from Gmail using IMAP.
    Requires an App Password (not regular password).
    Searches for emails from real estate portals.
    """
    leads = []
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail_user, gmail_app_password)
        mail.select(folder)

        # Search for UNSEEN emails from real estate portals
        search_queries = [
            '(UNSEEN FROM "housing.com")',
            '(UNSEEN FROM "99acres.com")',
            '(UNSEEN FROM "magicbricks.com")',
        ]

        seen_ids = set()
        for query in search_queries:
            status, data = mail.search(None, query)
            if status != "OK":
                continue

            email_ids = data[0].split()
            # Take latest N
            for eid in email_ids[-max_emails:]:
                if eid in seen_ids:
                    continue
                seen_ids.add(eid)

                status, msg_data = mail.fetch(eid, "(RFC822)")
                if status != "OK":
                    continue

                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                subject = ""
                raw_subject = msg.get("Subject", "")
                decoded = decode_header(raw_subject)
                for part, enc in decoded:
                    if isinstance(part, bytes):
                        subject += part.decode(enc or "utf-8", errors="replace")
                    else:
                        subject += part

                sender = msg.get("From", "")
                body = _get_email_body(msg)
                lead = parse_lead_from_email(subject, body, sender)
                lead["raw_subject"] = subject
                leads.append(lead)

        mail.logout()
    except Exception as e:
        print(f"Gmail fetch error: {e}")

    return leads


def _get_email_body(msg) -> str:
    """Extract plain text body from email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                    break
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode("utf-8", errors="replace")
        except Exception:
            pass
    return body
