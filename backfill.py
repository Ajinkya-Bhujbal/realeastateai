import os, imaplib, email, email.utils, datetime
import sys
sys.path.insert(0, './backend')
from parser import _get_email_bodies, parse_lead_from_email
from db import SessionLocal
from models import Lead
from dotenv import load_dotenv

load_dotenv()

gmail_user = os.getenv("GMAIL_USER")
gmail_pass = os.getenv("GMAIL_APP_PASSWORD")

db = SessionLocal()

mail = imaplib.IMAP4_SSL("imap.gmail.com")
mail.login(gmail_user, gmail_pass)
mail.select("INBOX")

# Search all emails (not just unseen) since yesterday
search_queries = [
    '(SINCE "03-May-2026" FROM "housing-mailer.com")',
    '(SINCE "03-May-2026" FROM "housing.com")',
    '(SINCE "03-May-2026" FROM "magicbricks.com")',
    '(SINCE "03-May-2026" FROM "99acres.com")',
]

all_email_ids = set()
for q in search_queries:
    status, messages = mail.search(None, q)
    if status == "OK" and messages[0]:
        for eid in messages[0].split():
            all_email_ids.add(eid)

print(f"Found {len(all_email_ids)} total emails to check for backfill.")

added = 0
for eid in sorted(all_email_ids, key=lambda x: int(x), reverse=True):
    # Fetch without marking as seen
    status, msg_data = mail.fetch(eid, "(BODY.PEEK[])")
    if status != "OK": continue
    
    raw = msg_data[0][1]
    msg = email.message_from_bytes(raw)
    subject = msg.get("Subject", "")
    sender = msg.get("From", "")
    
    body, html_body = _get_email_bodies(msg)
    parsed = parse_lead_from_email(subject, body, sender, html_body)
    
    # Needs to be a valid lead
    phone = parsed.get("phone", "").strip()
    if not phone: continue
    
    email_date = msg.get("Date", "")
    received_at = None
    if email_date:
        try:
            received_at = email.utils.parsedate_to_datetime(email_date)
            # Convert to naive datetime in local timezone (which DB uses)
            if received_at.tzinfo is not None:
                received_at = received_at.astimezone().replace(tzinfo=None)
        except Exception:
            pass
    if not received_at:
        received_at = datetime.datetime.now()
        
    # Check if this exact lead (same phone + same timestamp) is already in DB
    # We allow a small 1-minute margin in case of timestamp truncation
    margin = datetime.timedelta(minutes=1)
    min_time = received_at - margin
    max_time = received_at + margin
    
    existing = db.query(Lead).filter(
        Lead.phone == phone,
        Lead.created_at >= min_time,
        Lead.created_at <= max_time
    ).first()
    
    if not existing:
        lead = Lead(
            name=parsed.get("name", "Unknown").strip(),
            phone=phone,
            email=parsed.get("email", "").strip(),
            source=parsed.get("source", "email"),
            status="new",
            budget_min=parsed.get("budget_min"),
            budget_max=parsed.get("budget_max"),
            preferred_location=parsed.get("preferred_location", ""),
            property_type=parsed.get("property_type", ""),
            configuration=parsed.get("configuration", ""),
            price=parsed.get("price", ""),
            notes=parsed.get("notes", "")[:500],
        )
        lead.created_at = received_at
        db.add(lead)
        db.commit()
        added += 1
        print(f"Backfilled missed lead: {lead.name} ({lead.phone}) from {lead.source}")

print(f"Backfill complete. Added {added} missing leads.")
db.close()
