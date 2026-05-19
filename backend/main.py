"""
Real Estate Lead Management System - Main API
FastAPI single app with all endpoints.
"""
import sys
import os

# Load .env BEFORE any other imports so all modules see the env vars
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

import datetime
from contextlib import asynccontextmanager
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

# Add backend dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_db, init_db, SessionLocal, engine
from models import Lead, Message, Property, FollowUpSchedule, RawEmail
from parser import parse_lead_from_email, fetch_gmail_leads
from whatsapp import send_whatsapp_message, verify_webhook, parse_webhook_message, upload_whatsapp_media
from ai import (
    check_ollama, list_models, generate_lead_reply,
    generate_followup_message, generate_property_recommendation,
    generate_auto_reply, generate_rag_reply, summarize_lead,
)
from rag import (
    search_properties, index_property, load_sample_properties, index_properties_bulk,
    search_kb, index_kb_folder, get_kb_status,
)
from followup import start_scheduler, stop_scheduler, create_followup_schedule, _process_pending_raw_emails
from wa_guard import is_live_mode, set_live_mode, can_send_to, get_whitelist


# ─── Pydantic Schemas ────────────────────────────────────────────────

class LeadCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    source: str = "manual"
    status: str = "new"
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    preferred_location: Optional[str] = None
    property_type: Optional[str] = None
    configuration: Optional[str] = None
    price: Optional[str] = None
    notes: Optional[str] = None

class LeadUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    preferred_location: Optional[str] = None
    property_type: Optional[str] = None
    configuration: Optional[str] = None
    price: Optional[str] = None
    tag: Optional[str] = None
    notes: Optional[str] = None

class EmailParseRequest(BaseModel):
    subject: str
    body: str
    sender: str = ""

class GmailFetchRequest(BaseModel):
    gmail_user: Optional[str] = None
    gmail_app_password: Optional[str] = None
    max_emails: int = 20

class SendMessageRequest(BaseModel):
    lead_id: int
    message: str
    channel: str = "whatsapp"

class AIReplyRequest(BaseModel):
    lead_id: int
    message: Optional[str] = None  # if replying to incoming

class PropertyCreate(BaseModel):
    title: str
    location: str
    price: float
    property_type: str = "apartment"
    bedrooms: Optional[int] = None
    area_sqft: Optional[float] = None
    description: Optional[str] = None
    amenities: Optional[str] = None
    builder: Optional[str] = None
    status: str = "available"

class PropertySearchRequest(BaseModel):
    query: str
    n_results: int = 5
    property_type: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    bedrooms: Optional[int] = None

class FollowUpCreate(BaseModel):
    lead_id: int
    frequency_hours: int = 24
    max_followups: int = 5
    message_template: Optional[str] = None


# ─── App Setup ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    print("="*50)
    print("  Real Estate Lead Management System")
    print("="*50)
    init_db()
    # Auto-migrate: add processing_lock_at column if missing (for existing DBs)
    try:
        from sqlalchemy import text, inspect
        with engine.connect() as conn:
            inspector = inspect(engine)
            columns = [c["name"] for c in inspector.get_columns("messages")]
            if "processing_lock_at" not in columns:
                conn.execute(text("ALTER TABLE messages ADD COLUMN processing_lock_at DATETIME"))
                conn.commit()
                print("[OK] Database migrated: added processing_lock_at column")
    except Exception as e:
        print(f"[WARN] Migration check: {e}")
    print("[OK] Database initialized")

    # Start follow-up scheduler
    start_scheduler()
    print("[OK] Follow-up scheduler started")

    # Check Ollama
    if check_ollama():
        models = list_models()
        print(f"[OK] Ollama connected. Models: {', '.join(models) if models else 'none loaded'}")
    else:
        print("[WARN] Ollama not running. AI features will be limited.")

    # Auto-index knowledge base on startup
    try:
        kb_status = get_kb_status()
        if kb_status["files"] > 0:
            result = index_kb_folder()
            print(f"[OK] Knowledge base indexed: {result['total_chunks']} chunks from {result['files']} files")
        else:
            print("[WARN] No knowledge base files found in data/knowledge_base/")
    except Exception as e:
        print(f"[WARN] KB indexing failed: {e}")

    print(f"[OK] Server ready at http://localhost:8000")
    print("="*50)

    yield

    # Shutdown
    stop_scheduler()
    print("Server shut down.")


app = FastAPI(
    title="Real Estate Lead Manager",
    description="AI-powered local lead management system",
    version="1.0.0",
    lifespan=lifespan,
)

# Serve frontend static files
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# Serve media files (amenity photos, flat videos)
MEDIA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "media")
if os.path.exists(MEDIA_DIR):
    app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")


# No-cache middleware for JS/CSS during development
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.endswith(('.js', '.css')):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.add_middleware(NoCacheStaticMiddleware)


# ─── Frontend Route ──────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    """Serve the dashboard HTML."""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>Real Estate Lead Manager API</h1><p>Frontend not found. API docs at <a href='/docs'>/docs</a></p>")


# ─── Health Check ─────────────────────────────────────────────────────

@app.get("/api/health")
def health_check():
    ollama_ok = check_ollama()
    return {
        "status": "ok",
        "ollama": ollama_ok,
        "models": list_models() if ollama_ok else [],
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


# ─── Lead CRUD ────────────────────────────────────────────────────────

@app.post("/api/leads")
def create_lead(lead: LeadCreate, db: Session = Depends(get_db)):
    """Create a new lead. If phone is provided, send welcome template immediately."""
    db_lead = Lead(**lead.model_dump())
    db.add(db_lead)
    db.commit()
    db.refresh(db_lead)

    # ── Send WhatsApp welcome template in background if phone exists ──
    if db_lead.phone:
        import threading
        from wa_guard import can_send_to

        def _send_template_bg(lead_id, phone, name):
            from db import SessionLocal
            from welcome_sequence import send_welcome_sequence
            from models import Lead, Message
            wdb = SessionLocal()
            try:
                if not can_send_to(phone):
                    try:
                        print(f"[WA Guard] Blocked template to {phone} (live mode OFF, not in whitelist)")
                    except Exception:
                        pass
                    return

                template_result = send_welcome_sequence(phone, name)
                template_name = os.getenv("WA_TEMPLATE_NAME", "hello_world")
                wdb.add(Message(
                    lead_id=lead_id, direction="out", channel="whatsapp",
                    content=f"[Template Sent: {template_name}]",
                    status="sent" if template_result.get("success") or template_result.get("mock") else "failed",
                    wa_message_id=template_result.get("message_id", ""),
                    is_read=True,
                ))
                lead_obj = wdb.query(Lead).filter(Lead.id == lead_id).first()
                if lead_obj:
                    lead_obj.welcome_sent = True
                    from datetime import datetime
                    lead_obj.last_message_at = datetime.utcnow()
                wdb.commit()
                try:
                    print(f"[Welcome] Template '{template_name}' sent to {name} ({phone})")
                except Exception:
                    pass
            except Exception as e:
                try:
                    print(f"[Welcome] Template error: {str(e).encode('ascii','replace').decode()}")
                except Exception:
                    pass
            finally:
                wdb.close()

        t = threading.Thread(target=_send_template_bg, args=(db_lead.id, db_lead.phone, db_lead.name))
        t.daemon = True
        t.start()

    return {"id": db_lead.id, "name": db_lead.name, "status": "created"}


@app.get("/api/leads")
def list_leads(
    status: Optional[str] = None,
    source: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List all leads with optional filters. Sorted by most recent activity (latest email arrival)."""
    from sqlalchemy import func

    q = db.query(Lead)
    if status:
        q = q.filter(Lead.status == status)
    if source:
        q = q.filter(Lead.source == source)
    if search:
        q = q.filter(
            (Lead.name.ilike(f"%{search}%"))
            | (Lead.phone.ilike(f"%{search}%"))
            | (Lead.email.ilike(f"%{search}%"))
        )
    total = q.count()
    # Sort by created_at DESC (reflects latest email arrival)
    leads = q.order_by(Lead.created_at.desc()).offset(skip).limit(limit).all()

    # Get email counts per lead from raw_emails table
    lead_ids = [l.id for l in leads]
    email_counts = {}
    if lead_ids:
        counts = (
            db.query(RawEmail.lead_id, func.count(RawEmail.id))
            .filter(RawEmail.lead_id.in_(lead_ids))
            .group_by(RawEmail.lead_id)
            .all()
        )
        email_counts = {lid: cnt for lid, cnt in counts}

    return {
        "total": total,
        "leads": [
            {
                "id": l.id,
                "name": l.name,
                "phone": l.phone,
                "email": l.email,
                "source": l.source,
                "status": l.status,
                "budget_min": l.budget_min,
                "budget_max": l.budget_max,
                "preferred_location": l.preferred_location,
                "property_type": l.property_type,
                "configuration": l.configuration,
                "price": l.price,
                "tag": l.tag,
                "notes": l.notes,
                "welcome_sent": l.welcome_sent if hasattr(l, 'welcome_sent') else False,
                "email_count": email_counts.get(l.id, 0),
                "created_at": l.created_at.isoformat() if l.created_at else None,
                "updated_at": l.updated_at.isoformat() if l.updated_at else None,
            }
            for l in leads
        ],
    }


@app.get("/api/leads/{lead_id}/emails")
def get_lead_emails(lead_id: int, db: Session = Depends(get_db)):
    """Get all raw emails linked to a lead (for viewing duplicate email details)."""
    import json
    raw_emails = (
        db.query(RawEmail)
        .filter(RawEmail.lead_id == lead_id)
        .order_by(RawEmail.received_at.desc())
        .all()
    )
    result = []
    for re_obj in raw_emails:
        parsed = {}
        if re_obj.parse_result_json:
            try:
                parsed = json.loads(re_obj.parse_result_json)
            except Exception:
                pass
        result.append({
            "id": re_obj.id,
            "subject": re_obj.subject,
            "sender": re_obj.sender,
            "status": re_obj.status,
            "received_at": re_obj.received_at.isoformat() if re_obj.received_at else None,
            "name": parsed.get("name", ""),
            "phone": parsed.get("phone", ""),
            "email": parsed.get("email", ""),
            "source": parsed.get("source", ""),
            "configuration": parsed.get("configuration", ""),
            "price": parsed.get("price", ""),
            "preferred_location": parsed.get("preferred_location", ""),
            "property_type": parsed.get("property_type", ""),
            "tag": parsed.get("tag", ""),
            "notes": (parsed.get("notes", "") or "")[:200],
        })
    return {"lead_id": lead_id, "emails": result}


@app.get("/api/leads/{lead_id}")
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    """Get a single lead with messages."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    messages = (
        db.query(Message)
        .filter(Message.lead_id == lead_id)
        .order_by(Message.created_at.desc())
        .limit(50)
        .all()
    )

    followups = (
        db.query(FollowUpSchedule)
        .filter(FollowUpSchedule.lead_id == lead_id)
        .all()
    )

    return {
        "id": lead.id,
        "name": lead.name,
        "phone": lead.phone,
        "email": lead.email,
        "source": lead.source,
        "status": lead.status,
        "budget_min": lead.budget_min,
        "budget_max": lead.budget_max,
        "preferred_location": lead.preferred_location,
        "property_type": lead.property_type,
        "configuration": lead.configuration,
        "price": lead.price,
        "tag": lead.tag,
        "notes": lead.notes,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
        "messages": [
            {
                "id": m.id,
                "direction": m.direction,
                "channel": m.channel,
                "content": m.content,
                "status": m.status,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
        "followups": [
            {
                "id": f.id,
                "frequency_hours": f.frequency_hours,
                "next_followup_at": f.next_followup_at.isoformat() if f.next_followup_at else None,
                "is_active": f.is_active,
                "followups_sent": f.followups_sent,
                "max_followups": f.max_followups,
            }
            for f in followups
        ],
    }


@app.put("/api/leads/{lead_id}")
def update_lead(lead_id: int, update: LeadUpdate, db: Session = Depends(get_db)):
    """Update a lead."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    update_data = update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(lead, key, value)
    lead.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    return {"id": lead.id, "status": "updated"}


@app.delete("/api/leads/{lead_id}")
def delete_lead(lead_id: int, db: Session = Depends(get_db)):
    """Delete a lead and all related data."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    db.delete(lead)
    db.commit()
    return {"id": lead_id, "status": "deleted"}


# ─── Email Parsing ────────────────────────────────────────────────────

@app.post("/api/parse-email")
def parse_email(req: EmailParseRequest):
    """Parse a real estate email and extract lead information."""
    result = parse_lead_from_email(req.subject, req.body, req.sender)
    return result


@app.post("/api/parse-email/save")
def parse_and_save_email(req: EmailParseRequest, db: Session = Depends(get_db)):
    """Parse an email and save as a new lead."""
    parsed = parse_lead_from_email(req.subject, req.body, req.sender)

    # Check for duplicate by phone or email
    if parsed["phone"]:
        existing = db.query(Lead).filter(Lead.phone == parsed["phone"]).first()
        if existing:
            return {"id": existing.id, "status": "duplicate", "message": f"Lead already exists: {existing.name}"}
    if parsed["email"]:
        existing = db.query(Lead).filter(Lead.email == parsed["email"]).first()
        if existing:
            return {"id": existing.id, "status": "duplicate", "message": f"Lead already exists: {existing.name}"}

    lead = Lead(
        name=parsed["name"],
        phone=parsed["phone"],
        email=parsed["email"],
        source=parsed["source"],
        budget_min=parsed["budget_min"],
        budget_max=parsed["budget_max"],
        preferred_location=parsed["preferred_location"],
        property_type=parsed["property_type"],
        notes=parsed["notes"],
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return {"id": lead.id, "name": lead.name, "status": "created", "parsed": parsed}


@app.post("/api/gmail/fetch")
def fetch_from_gmail(req: GmailFetchRequest, db: Session = Depends(get_db)):
    """Fetch leads from Gmail inbox. Credentials fall back to .env if not provided."""
    gmail_user = req.gmail_user or os.getenv("GMAIL_USER", "")
    gmail_pass = req.gmail_app_password or os.getenv("GMAIL_APP_PASSWORD", "")
    if not gmail_user or not gmail_pass:
        raise HTTPException(status_code=400, detail="Gmail credentials not configured. Set GMAIL_USER and GMAIL_APP_PASSWORD in .env or provide in request.")
    leads = fetch_gmail_leads(gmail_user, gmail_pass, req.max_emails)
    created = 0
    skipped = 0
    for parsed in leads:
        # Skip junk
        if not parsed.get("phone") and not parsed.get("email"):
            print("Skipping as junk because no phone/email")
            skipped += 1
            continue

        lead = Lead(
            name=parsed.get("name", "Unknown"),
            phone=parsed.get("phone", ""),
            email=parsed.get("email", ""),
            source=parsed.get("source", "email"),
            budget_min=parsed.get("budget_min"),
            budget_max=parsed.get("budget_max"),
            preferred_location=parsed.get("preferred_location", ""),
            property_type=parsed.get("property_type", ""),
            configuration=parsed.get("configuration", ""),
            price=parsed.get("price", ""),
            notes=parsed.get("notes", ""),
        )
        db.add(lead)
        created += 1

    db.commit()
    return {"created": created, "skipped": skipped, "total_found": created + skipped}


# ─── Messaging ────────────────────────────────────────────────────────

@app.post("/api/messages/send")
def send_message(req: SendMessageRequest, db: Session = Depends(get_db)):
    """Send a message to a lead via WhatsApp."""
    lead = db.query(Lead).filter(Lead.id == req.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not lead.phone:
        raise HTTPException(status_code=400, detail="Lead has no phone number")

    result = send_whatsapp_message(lead.phone, req.message)

    msg = Message(
        lead_id=lead.id,
        direction="out",
        channel=req.channel,
        content=req.message,
        status="sent" if result.get("success") or result.get("mock") else "failed",
        wa_message_id=result.get("message_id", ""),
    )
    db.add(msg)

    # Update lead status
    if lead.status == "new":
        lead.status = "contacted"
        lead.updated_at = datetime.datetime.now(datetime.timezone.utc)

    db.commit()
    return {"message_id": msg.id, "wa_result": result}


@app.get("/api/messages/{lead_id}")
def get_messages(lead_id: int, db: Session = Depends(get_db)):
    """Get all messages for a lead."""
    messages = (
        db.query(Message)
        .filter(Message.lead_id == lead_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    return {
        "lead_id": lead_id,
        "messages": [
            {
                "id": m.id,
                "direction": m.direction,
                "channel": m.channel,
                "content": m.content,
                "status": m.status,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


# ─── WhatsApp Webhook ────────────────────────────────────────────────

@app.get("/api/webhook/whatsapp")
def whatsapp_webhook_verify(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """WhatsApp webhook verification (GET)."""
    if hub_mode and hub_token:
        result = verify_webhook(hub_mode, hub_token, hub_challenge)
        if result:
            return int(result)
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/api/webhook/whatsapp")
async def whatsapp_webhook_receive(request: Request, db: Session = Depends(get_db)):
    """Receive incoming WhatsApp messages. Stores as unread; auto-reply handled by scheduler."""
    try:
        payload = await request.json()
        import json
        
        # Log statuses to see delivery errors from Meta
        if "entry" in payload and payload["entry"]:
            changes = payload["entry"][0].get("changes", [])
            if changes:
                value = changes[0].get("value", {})
                if "statuses" in value:
                    status_obj = value["statuses"][0]
                    status_type = status_obj.get("status")
                    recipient = status_obj.get("recipient_id")
                    print(f"\\n[WA Delivery Status] Status: {status_type} | To: {recipient}")
                    if "errors" in status_obj:
                        print(f"[WA Delivery Error Detail]: {json.dumps(status_obj['errors'], indent=2)}")
                        with open("wa_webhook_errors.log", "a") as f:
                            f.write(f"\\n{json.dumps(status_obj, indent=2)}")
    except Exception:
        return JSONResponse({"status": "ok"})

    parsed = parse_webhook_message(payload)
    if not parsed or not parsed.get("message_text"):
        return JSONResponse({"status": "ok"})

    phone = parsed["from_phone"]
    text = parsed["message_text"]

    # Find lead by phone
    phone_clean = phone[-10:] if len(phone) > 10 else phone
    lead = db.query(Lead).filter(
        (Lead.phone == phone) | (Lead.phone == phone_clean) | (Lead.phone.endswith(phone_clean))
    ).first()

    if not lead:
        lead = Lead(
            name=parsed.get("sender_name", "Unknown"),
            phone=phone_clean,
            source="whatsapp",
            status="new",
            notes=f"Auto-created from incoming WhatsApp message: {text[:200]}",
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)

    # Save incoming message as UNREAD
    incoming = Message(
        lead_id=lead.id,
        direction="in",
        channel="whatsapp",
        content=text,
        status="received",
        wa_message_id=parsed.get("message_id", ""),
        is_read=False,
        is_auto_replied=False,
    )
    db.add(incoming)

    # Update lead tracking
    lead.last_message_at = datetime.datetime.now(datetime.timezone.utc)
    lead.unread_count = (lead.unread_count or 0) + 1

    db.commit()
    return JSONResponse({"status": "ok"})


# ─── AI Endpoints ─────────────────────────────────────────────────────

@app.post("/api/ai/reply")
def ai_generate_reply(req: AIReplyRequest, db: Session = Depends(get_db)):
    """Generate an AI reply for a lead."""
    lead = db.query(Lead).filter(Lead.id == req.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    interest = f"{lead.property_type or 'property'} in {lead.preferred_location or 'unspecified area'}"
    context = f"Budget: {lead.budget_min or '?'}-{lead.budget_max or '?'} Lakhs"

    if req.message:
        reply = generate_auto_reply(req.message, lead.name, context)
    else:
        reply = generate_lead_reply(lead.name, interest, context)

    return {"lead_id": lead.id, "reply": reply}


@app.post("/api/ai/recommend")
def ai_recommend_properties(req: AIReplyRequest, db: Session = Depends(get_db)):
    """Get AI property recommendations for a lead using RAG."""
    lead = db.query(Lead).filter(Lead.id == req.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Build search query from lead preferences
    query_parts = []
    if lead.property_type:
        query_parts.append(lead.property_type)
    if lead.preferred_location:
        query_parts.append(lead.preferred_location)
    if lead.budget_max:
        query_parts.append(f"under {lead.budget_max} lakhs")
    query = " ".join(query_parts) if query_parts else "apartment Bangalore"

    # Search properties via RAG
    filters = {}
    if lead.property_type:
        filters["property_type"] = lead.property_type
    if lead.budget_min:
        filters["min_price"] = lead.budget_min
    if lead.budget_max:
        filters["max_price"] = lead.budget_max

    properties = search_properties(query, n_results=5, filters=filters if filters else None)

    # Generate recommendation message
    preferences = f"{lead.property_type or 'any type'} in {lead.preferred_location or 'any location'}, budget {lead.budget_min or '?'}-{lead.budget_max or '?'} Lakhs"
    recommendation = generate_property_recommendation(lead.name, preferences, properties)

    return {
        "lead_id": lead.id,
        "properties": properties,
        "recommendation": recommendation,
    }


@app.get("/api/ai/status")
def ai_status():
    """Check AI/Ollama status."""
    ollama_ok = check_ollama()
    return {
        "ollama_running": ollama_ok,
        "models": list_models() if ollama_ok else [],
    }


# ─── Property CRUD ────────────────────────────────────────────────────

@app.post("/api/properties")
def create_property(prop: PropertyCreate, db: Session = Depends(get_db)):
    """Create a new property and index it for RAG."""
    db_prop = Property(**prop.model_dump())
    db.add(db_prop)
    db.commit()
    db.refresh(db_prop)

    # Index in ChromaDB
    try:
        index_property(prop.model_dump() | {"id": db_prop.id})
    except Exception as e:
        print(f"RAG index error: {e}")

    return {"id": db_prop.id, "status": "created"}


@app.get("/api/properties")
def list_properties(
    property_type: Optional[str] = None,
    location: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List properties from database."""
    q = db.query(Property)
    if property_type:
        q = q.filter(Property.property_type == property_type)
    if location:
        q = q.filter(Property.location.ilike(f"%{location}%"))
    total = q.count()
    props = q.offset(skip).limit(limit).all()

    return {
        "total": total,
        "properties": [
            {
                "id": p.id,
                "title": p.title,
                "location": p.location,
                "price": p.price,
                "property_type": p.property_type,
                "bedrooms": p.bedrooms,
                "area_sqft": p.area_sqft,
                "description": p.description,
                "amenities": p.amenities,
                "builder": p.builder,
                "status": p.status,
            }
            for p in props
        ],
    }


@app.post("/api/properties/search")
def search_properties_api(req: PropertySearchRequest):
    """Search properties using RAG semantic search."""
    filters = {}
    if req.property_type:
        filters["property_type"] = req.property_type
    if req.min_price:
        filters["min_price"] = req.min_price
    if req.max_price:
        filters["max_price"] = req.max_price
    if req.bedrooms:
        filters["bedrooms"] = req.bedrooms

    results = search_properties(req.query, req.n_results, filters if filters else None)
    return {"query": req.query, "results": results}


@app.post("/api/properties/index-samples")
def index_sample_properties():
    """Load and index sample properties from JSON file."""
    count = load_sample_properties()
    return {"indexed": count}


# ─── Follow-Up Management ─────────────────────────────────────────────

@app.post("/api/followups")
def create_followup(req: FollowUpCreate, db: Session = Depends(get_db)):
    """Create a follow-up schedule for a lead."""
    lead = db.query(Lead).filter(Lead.id == req.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    schedule = create_followup_schedule(
        db=db,
        lead_id=req.lead_id,
        frequency_hours=req.frequency_hours,
        max_followups=req.max_followups,
        message_template=req.message_template,
    )
    return {
        "id": schedule.id,
        "lead_id": schedule.lead_id,
        "frequency_hours": schedule.frequency_hours,
        "next_followup_at": schedule.next_followup_at.isoformat(),
        "status": "created",
    }


@app.get("/api/followups")
def list_followups(active_only: bool = True, db: Session = Depends(get_db)):
    """List all follow-up schedules."""
    q = db.query(FollowUpSchedule)
    if active_only:
        q = q.filter(FollowUpSchedule.is_active == True)
    followups = q.all()

    return {
        "followups": [
            {
                "id": f.id,
                "lead_id": f.lead_id,
                "lead_name": db.query(Lead).filter(Lead.id == f.lead_id).first().name if db.query(Lead).filter(Lead.id == f.lead_id).first() else "Unknown",
                "frequency_hours": f.frequency_hours,
                "next_followup_at": f.next_followup_at.isoformat() if f.next_followup_at else None,
                "is_active": f.is_active,
                "followups_sent": f.followups_sent,
                "max_followups": f.max_followups,
            }
            for f in followups
        ],
    }


@app.delete("/api/followups/{followup_id}")
def cancel_followup(followup_id: int, db: Session = Depends(get_db)):
    """Cancel a follow-up schedule."""
    fup = db.query(FollowUpSchedule).filter(FollowUpSchedule.id == followup_id).first()
    if not fup:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    fup.is_active = False
    db.commit()
    return {"id": followup_id, "status": "cancelled"}


# ─── Dashboard Stats ──────────────────────────────────────────────────

@app.get("/api/dashboard/stats")
def dashboard_stats(db: Session = Depends(get_db)):
    """Get dashboard statistics."""
    total_leads = db.query(Lead).count()
    new_leads = db.query(Lead).filter(Lead.status == "new").count()
    contacted = db.query(Lead).filter(Lead.status == "contacted").count()
    interested = db.query(Lead).filter(Lead.status == "interested").count()
    converted = db.query(Lead).filter(Lead.status == "converted").count()
    total_messages = db.query(Message).count()
    active_followups = db.query(FollowUpSchedule).filter(FollowUpSchedule.is_active == True).count()
    total_properties = db.query(Property).count()

    # Leads by source
    from sqlalchemy import func
    sources = db.query(Lead.source, func.count(Lead.id)).group_by(Lead.source).all()
    source_counts = {s: c for s, c in sources}

    # Recent leads
    recent = db.query(Lead).order_by(Lead.created_at.desc()).limit(5).all()

    return {
        "total_leads": total_leads,
        "new_leads": new_leads,
        "contacted": contacted,
        "interested": interested,
        "converted": converted,
        "total_messages": total_messages,
        "active_followups": active_followups,
        "total_properties": total_properties,
        "leads_by_source": source_counts,
        "recent_leads": [
            {"id": l.id, "name": l.name, "source": l.source, "status": l.status, "price": l.price, "preferred_location": l.preferred_location, "property_type": l.property_type, "created_at": l.created_at.isoformat() if l.created_at else None}
            for l in recent
        ],
        "quarantined_emails": db.query(RawEmail).filter(RawEmail.status.in_(["quarantined", "error"])).count(),
    }


# ─── WhatsApp Live Mode Toggle ────────────────────────────────────────

@app.get("/api/wa/live-mode")
def get_wa_live_mode():
    """Get WhatsApp live mode status and whitelist."""
    return {
        "live_mode": is_live_mode(),
        "whitelist": sorted(get_whitelist()),
    }


@app.post("/api/wa/live-mode")
def set_wa_live_mode(req: dict):
    """Toggle WhatsApp live mode on/off."""
    enabled = req.get("enabled", False)
    set_live_mode(bool(enabled))
    return {
        "live_mode": is_live_mode(),
        "whitelist": sorted(get_whitelist()),
        "message": f"Live mode {'ENABLED — messages will be sent to ALL leads' if enabled else 'DISABLED — only whitelisted numbers will receive messages'}",
    }


# ─── Quarantine API (Email Audit) ─────────────────────────────────────

@app.get("/api/quarantine")
def list_quarantined(status: Optional[str] = None, db: Session = Depends(get_db)):
    """List quarantined/error emails that need review."""
    q = db.query(RawEmail)
    if status:
        q = q.filter(RawEmail.status == status)
    else:
        q = q.filter(RawEmail.status.in_(["quarantined", "error"]))
    raw_emails = q.order_by(RawEmail.fetched_at.desc()).limit(100).all()

    import json
    return {
        "total": len(raw_emails),
        "emails": [
            {
                "id": r.id,
                "subject": r.subject,
                "sender": r.sender,
                "status": r.status,
                "quarantine_reason": r.quarantine_reason,
                "parsed_data": json.loads(r.parse_result_json) if r.parse_result_json else {},
                "lead_id": r.lead_id,
                "received_at": r.received_at.isoformat() if r.received_at else None,
                "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
            }
            for r in raw_emails
        ],
    }


@app.get("/api/quarantine/stats")
def quarantine_stats(db: Session = Depends(get_db)):
    """Get quarantine statistics."""
    from sqlalchemy import func
    total = db.query(RawEmail).count()
    by_status = dict(db.query(RawEmail.status, func.count(RawEmail.id)).group_by(RawEmail.status).all())
    return {
        "total_raw_emails": total,
        "by_status": by_status,
    }


@app.post("/api/quarantine/{raw_email_id}/reparse")
def reparse_quarantined(raw_email_id: int, db: Session = Depends(get_db)):
    """Re-parse a quarantined email through the updated parser."""
    import json
    raw = db.query(RawEmail).filter(RawEmail.id == raw_email_id).first()
    if not raw:
        raise HTTPException(status_code=404, detail="Raw email not found")

    # Re-run the parser on the stored raw email
    parsed = parse_lead_from_email(raw.subject or "", raw.body or "", raw.sender or "", raw.html_body or "")
    raw.parse_result_json = json.dumps(parsed, default=str)

    phone = parsed.get("phone", "").strip()
    if not phone:
        raw.quarantine_reason = "no_phone (re-parsed)"
        db.commit()
        return {"status": "still_quarantined", "reason": "no_phone", "parsed": parsed}

    # Phone found — create the lead
    name = parsed.get("name", "").strip() or "Unknown"
    lead = Lead(
        name=name, phone=phone,
        email=parsed.get("email", ""),
        source=parsed.get("source", "email"), status="new",
        budget_min=parsed.get("budget_min"),
        budget_max=parsed.get("budget_max"),
        preferred_location=parsed.get("preferred_location", ""),
        property_type=parsed.get("property_type", ""),
        configuration=parsed.get("configuration", ""),
        price=parsed.get("price", ""),
        notes=parsed.get("notes", "")[:500],
    )
    if raw.received_at:
        lead.created_at = raw.received_at
    db.add(lead)
    db.flush()
    raw.status = "parsed"
    raw.lead_id = lead.id
    raw.parsed_at = datetime.datetime.now(datetime.timezone.utc)
    raw.quarantine_reason = None
    db.commit()
    return {"status": "created", "lead_id": lead.id, "name": name, "phone": phone}


@app.post("/api/quarantine/reparse-all")
def reparse_all_quarantined(db: Session = Depends(get_db)):
    """Re-parse ALL quarantined/error emails through the updated parser."""
    import json
    # Reset quarantined entries to pending so the processor picks them up
    count = db.query(RawEmail).filter(
        RawEmail.status.in_(["quarantined", "error"])
    ).update({"status": "pending"}, synchronize_session="fetch")
    db.commit()

    # Re-run parser on each pending email to update parse_result_json
    pending = db.query(RawEmail).filter(RawEmail.status == "pending").all()
    for raw in pending:
        try:
            parsed = parse_lead_from_email(raw.subject or "", raw.body or "", raw.sender or "", raw.html_body or "")
            raw.parse_result_json = json.dumps(parsed, default=str)
        except Exception as e:
            print(f"Re-parse error for {raw.id}: {e}")
    db.commit()

    # Now process them
    _process_pending_raw_emails(db)
    return {"reset_count": count, "status": "reprocessed"}


@app.post("/api/quarantine/{raw_email_id}/manual")
def manual_create_from_quarantine(raw_email_id: int, lead_data: LeadCreate, db: Session = Depends(get_db)):
    """Manually create a lead from a quarantined email with user-supplied data."""
    raw = db.query(RawEmail).filter(RawEmail.id == raw_email_id).first()
    if not raw:
        raise HTTPException(status_code=404, detail="Raw email not found")

    lead = Lead(**lead_data.model_dump())
    if raw.received_at:
        lead.created_at = raw.received_at
    db.add(lead)
    db.flush()
    raw.status = "parsed"
    raw.lead_id = lead.id
    raw.parsed_at = datetime.datetime.now(datetime.timezone.utc)
    raw.quarantine_reason = "manually_resolved"
    db.commit()
    return {"status": "created", "lead_id": lead.id}


# ─── Chat API (WhatsApp Web-style) ────────────────────────────────────

@app.get("/api/chats")
def list_chats(db: Session = Depends(get_db)):
    """List all conversations sorted by last message time. For WhatsApp Web sidebar."""
    leads = (
        db.query(Lead)
        .filter(Lead.phone != None, Lead.phone != "")
        .order_by(Lead.last_message_at.desc().nullslast(), Lead.created_at.desc())
        .limit(100)
        .all()
    )
    chats = []
    for l in leads:
        last_msg = (
            db.query(Message)
            .filter(Message.lead_id == l.id)
            .order_by(Message.created_at.desc())
            .first()
        )
        chats.append({
            "lead_id": l.id,
            "name": l.name,
            "phone": l.phone,
            "status": l.status,
            "source": l.source,
            "unread_count": l.unread_count or 0,
            "auto_reply_enabled": l.auto_reply_enabled if l.auto_reply_enabled is not None else True,
            "last_message": last_msg.content[:80] if last_msg else "",
            "last_message_direction": last_msg.direction if last_msg else "",
            "last_message_at": (last_msg.created_at.isoformat() if last_msg and last_msg.created_at else
                                l.last_message_at.isoformat() if l.last_message_at else
                                l.created_at.isoformat() if l.created_at else None),
        })
    return {"chats": chats}


@app.get("/api/chats/{lead_id}")
def get_chat_messages(lead_id: int, limit: int = 100, db: Session = Depends(get_db)):
    """Get full chat history for a lead."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Get the NEWEST messages (desc), then reverse to chronological for display
    messages = list(reversed(
        db.query(Message)
        .filter(Message.lead_id == lead_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
        .all()
    ))
    return {
        "lead_id": lead.id,
        "name": lead.name,
        "phone": lead.phone,
        "status": lead.status,
        "auto_reply_enabled": lead.auto_reply_enabled if lead.auto_reply_enabled is not None else True,
        "media_sent": lead.media_sent if lead.media_sent is not None else False,
        "messages": [
            {
                "id": m.id,
                "direction": m.direction,
                "content": m.content,
                "status": m.status,
                "is_read": m.is_read,
                "is_auto_replied": m.is_auto_replied,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@app.post("/api/chats/{lead_id}/read")
def mark_chat_read(lead_id: int, db: Session = Depends(get_db)):
    """Mark all messages for a lead as read, reset unread count."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    db.query(Message).filter(
        Message.lead_id == lead_id,
        Message.direction == "in",
        Message.is_read == False,
    ).update({"is_read": True})
    lead.unread_count = 0
    db.commit()
    return {"status": "ok", "lead_id": lead_id}


@app.post("/api/chats/{lead_id}/send")
def send_chat_message(lead_id: int, req: SendMessageRequest, db: Session = Depends(get_db)):
    """Send a message from the chat UI."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not lead.phone:
        raise HTTPException(status_code=400, detail="Lead has no phone number")

    result = send_whatsapp_message(lead.phone, req.message)

    msg = Message(
        lead_id=lead.id,
        direction="out",
        channel="whatsapp",
        content=req.message,
        status="sent" if result.get("success") or result.get("mock") else "failed",
        wa_message_id=result.get("message_id", ""),
        is_read=True,
    )
    db.add(msg)
    lead.last_message_at = datetime.datetime.now(datetime.timezone.utc)
    if lead.status == "new":
        lead.status = "contacted"
    db.commit()
    return {"message_id": msg.id, "wa_result": result}




@app.post("/api/chats/{lead_id}/send-media")
async def send_chat_media(
    lead_id: int, 
    file: UploadFile = File(...), 
    message: str = Form(""), 
    db: Session = Depends(get_db)
):
    """Send a media message from the chat UI."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not lead.phone:
        raise HTTPException(status_code=400, detail="Lead has no phone number")

    content_type = file.content_type
    if "image" in content_type:
        media_type = "image"
    elif "video" in content_type:
        media_type = "video"
    elif "audio" in content_type:
        media_type = "audio"
    else:
        media_type = "document"

    file_bytes = await file.read()
    media_id = upload_whatsapp_media(file_bytes, content_type, file.filename)
    
    if not media_id:
        raise HTTPException(status_code=500, detail="Failed to upload media to WhatsApp API")

    result = send_whatsapp_message(lead.phone, message, media_id=media_id, media_type=media_type)

    msg_content = f"[{media_type.upper()}] {message}".strip()
    msg = Message(
        lead_id=lead.id,
        direction="out",
        channel="whatsapp",
        content=msg_content,
        status="sent" if result.get("success") or result.get("mock") else "failed",
        wa_message_id=result.get("message_id", ""),
        is_read=True,
    )
    db.add(msg)
    lead.last_message_at = datetime.datetime.now(datetime.timezone.utc)
    if lead.status == "new":
        lead.status = "contacted"
    db.commit()
    return {"message_id": msg.id, "wa_result": result}


class SimulateMessageRequest(BaseModel):
    phone: str
    message: str
    sender_name: str = "Test User"


@app.post("/api/chats/simulate-incoming")
def simulate_incoming_message(req: SimulateMessageRequest, db: Session = Depends(get_db)):
    """Simulate an incoming WhatsApp message (for testing without webhook)."""
    phone_clean = req.phone.strip().replace("+", "").replace(" ", "").replace("-", "")
    if len(phone_clean) > 10:
        phone_clean = phone_clean[-10:]

    lead = db.query(Lead).filter(
        (Lead.phone == req.phone) | (Lead.phone == phone_clean) | (Lead.phone.endswith(phone_clean))
    ).first()

    if not lead:
        lead = Lead(
            name=req.sender_name,
            phone=phone_clean,
            source="whatsapp",
            status="new",
            auto_reply_enabled=True,
            welcome_sent=False,
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)

    incoming = Message(
        lead_id=lead.id,
        direction="in",
        channel="whatsapp",
        content=req.message,
        status="received",
        is_read=False,
        is_auto_replied=False,
    )
    db.add(incoming)
    lead.last_message_at = datetime.datetime.now(datetime.timezone.utc)
    lead.unread_count = (lead.unread_count or 0) + 1
    db.commit()

    # Trigger welcome sequence for first-time leads (respects WA Safety Guard)
    if not lead.welcome_sent and can_send_to(phone_clean):
        import threading
        from welcome_sequence import send_welcome_sequence

        def _run_welcome(phone_num, lead_id):
            try:
                result = send_welcome_sequence(phone_num)
                print(f"Welcome sequence sent to {phone_num}: {result}")
                wdb = SessionLocal()
                try:
                    wlead = wdb.query(Lead).filter(Lead.id == lead_id).first()
                    if wlead:
                        wlead.welcome_sent = True
                        from welcome_sequence import get_welcome_db_messages
                        for m in get_welcome_db_messages():
                            wdb.add(Message(lead_id=lead_id, direction="out", channel="whatsapp",
                                            content=m["content"], status="sent", is_read=True))
                    wdb.commit()
                finally:
                    wdb.close()
            except Exception as e:
                print(f"Welcome sequence error: {e}")

        incoming.is_auto_replied = True
        db.commit()
        thread = threading.Thread(target=_run_welcome, args=(phone_clean, lead.id))
        thread.daemon = True
        thread.start()

    return {"status": "ok", "lead_id": lead.id, "message": "Incoming message simulated"}


@app.post("/api/chats/{lead_id}/toggle-auto-reply")
def toggle_auto_reply(lead_id: int, db: Session = Depends(get_db)):
    """Toggle auto-reply on/off for a lead."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead.auto_reply_enabled = not (lead.auto_reply_enabled if lead.auto_reply_enabled is not None else True)
    db.commit()
    return {"lead_id": lead.id, "auto_reply_enabled": lead.auto_reply_enabled}


@app.post("/api/chats/{lead_id}/reset-welcome")
def reset_welcome_sequence(lead_id: int, db: Session = Depends(get_db)):
    """Reset welcome + media flags so the sequence can be re-sent on next reply."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead.welcome_sent = True  # Keep welcome_sent True (template was already sent)
    lead.media_sent = False   # Reset media flag so next reply triggers the full media sequence
    db.commit()
    return {"lead_id": lead.id, "media_sent": False, "message": "Welcome media sequence reset. It will re-send on the next reply."}


@app.get("/api/chats/unread-count")
def get_total_unread(db: Session = Depends(get_db)):
    """Get total unread message count across all leads."""
    from sqlalchemy import func
    total = db.query(func.sum(Lead.unread_count)).scalar() or 0
    return {"total_unread": int(total)}


class ForceWelcomeRequest(BaseModel):
    re_engage: bool = False


@app.post("/api/leads/{lead_id}/force-welcome")
def force_welcome(lead_id: int, req: ForceWelcomeRequest, db: Session = Depends(get_db)):
    """Force-send welcome sequence or re-engage a lead."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not lead.phone:
        return {"status": "error", "error": "Lead has no phone number"}

    phone = lead.phone.strip().replace("+", "").replace(" ", "").replace("-", "")
    if len(phone) > 10:
        phone = phone[-10:]

    # WA Safety Guard
    if not can_send_to(phone):
        return {"status": "error", "error": f"Blocked: Live mode is OFF and {phone} is not in whitelist. Enable live mode on the dashboard to send to all leads."}

    if req.re_engage:
        # Send a WhatsApp template to re-open the 24hr conversation window
        from whatsapp import send_whatsapp_template
        template_name = os.getenv("WA_TEMPLATE_NAME", "hello_world")
        result = send_whatsapp_template(phone, template_name)
        # Store in DB
        re_msg = Message(
            lead_id=lead.id, direction="out", channel="whatsapp",
            content=f"[Re-engagement template sent: {template_name}]",
            status="sent" if result.get("success") or result.get("mock") else "failed",
            is_read=True,
        )
        db.add(re_msg)
        lead.last_message_at = datetime.datetime.now(datetime.timezone.utc)
        db.commit()
        return {"status": "ok", "message": "Re-engagement template sent"}
    else:
        # Send welcome template + full media sequence in background
        import threading
        from welcome_sequence import send_welcome_sequence

        def _run(phone_num, lid, lname):
            import time as _time
            try:
                # Step 1: Send template
                result = send_welcome_sequence(phone_num, lead_name=lname)
                print(f"Force welcome sent to {phone_num}: {result}")
                wdb = SessionLocal()
                try:
                    wlead = wdb.query(Lead).filter(Lead.id == lid).first()
                    if wlead:
                        wlead.welcome_sent = True
                        wlead.media_sent = True  # Mark media as sent so followup.py doesn't re-trigger
                        wlead.status = "welcoming"
                        template_name = os.getenv("WA_TEMPLATE_NAME", "hello_world")
                        wdb.add(Message(lead_id=lid, direction="out", channel="whatsapp",
                                        content=f"[Template Sent: {template_name}]", status="sent", is_read=True))
                    wdb.commit()
                finally:
                    wdb.close()

                # Step 2: Wait a bit, then send full media sequence
                _time.sleep(5)

                from welcome_sequence import get_amenity_photos, get_flat_videos
                from whatsapp import upload_whatsapp_media as _upload

                wdb2 = SessionLocal()
                try:
                    # Photo intro
                    photo_intro = (
                        "Please find below the photos of Free to use, Lavish Amenities in the society.\n"
                        "(Note: All photos are real. \U0001f60a)\n"
                        "\U0001f447\U0001f447\U0001f447\U0001f447\U0001f447\U0001f447\U0001f447\U0001f447"
                    )
                    send_whatsapp_message(phone_num, photo_intro)
                    wdb2.add(Message(lead_id=lid, direction="out", channel="whatsapp",
                                    content=photo_intro, status="sent", is_read=True))
                    wdb2.commit()

                    # Send amenity photos
                    photos = get_amenity_photos()
                    for photo_path in photos:
                        try:
                            fname = os.path.basename(photo_path)
                            with open(photo_path, "rb") as f:
                                file_bytes = f.read()
                            ext = fname.rsplit(".", 1)[-1].lower()
                            mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext}"
                            media_id = _upload(file_bytes, mime, fname)
                            if media_id:
                                send_whatsapp_message(phone_num, message=fname, media_id=media_id, media_type="image")
                            wdb2.add(Message(lead_id=lid, direction="out", channel="whatsapp",
                                            content=f"[IMAGE:{fname}]", status="sent", is_read=True))
                            wdb2.commit()
                        except Exception:
                            pass

                    _time.sleep(30)

                    # Video intro
                    video_intro = (
                        "Please find below the Videos of available flats for Sell and Rent both.\n"
                        "( 1 / 2 / 2.5 / 3 / 4 BHK available )\n"
                        "\U0001f447\U0001f447\U0001f447\U0001f447\U0001f447\U0001f447\U0001f447\U0001f447"
                    )
                    send_whatsapp_message(phone_num, video_intro)
                    wdb2.add(Message(lead_id=lid, direction="out", channel="whatsapp",
                                    content=video_intro, status="sent", is_read=True))
                    wdb2.commit()

                    # Send flat videos
                    videos = get_flat_videos()
                    for video_path in videos:
                        try:
                            fname = os.path.basename(video_path)
                            with open(video_path, "rb") as f:
                                file_bytes = f.read()
                            media_id = _upload(file_bytes, "video/mp4", fname)
                            if media_id:
                                send_whatsapp_message(phone_num, message=fname, media_id=media_id, media_type="video")
                            wdb2.add(Message(lead_id=lid, direction="out", channel="whatsapp",
                                            content=f"[VIDEO:{fname}]", status="sent", is_read=True))
                            wdb2.commit()
                        except Exception:
                            pass

                    print(f"[ForceWelcome] Full sequence sent to {phone_num}: {len(photos)} photos, {len(videos)} videos")

                    # Reset status from "welcoming" back to "new"
                    wlead2 = wdb2.query(Lead).filter(Lead.id == lid).first()
                    if wlead2 and wlead2.status == "welcoming":
                        wlead2.status = "new"
                        wlead2.last_message_at = datetime.datetime.now(datetime.timezone.utc)
                    wdb2.commit()
                finally:
                    wdb2.close()

            except Exception as e:
                print(f"Force welcome error: {e}")

        thread = threading.Thread(target=_run, args=(phone, lead.id, lead.name))
        thread.daemon = True
        thread.start()
        return {"status": "ok", "message": "Welcome template + media sequence started"}


# ─── WhatsApp Test Endpoint (Safe — Whitelist Only) ──────────────────

@app.get("/api/wa/test")
def wa_test_send_template(
    phone: str = Query("7276720388", description="Phone number to test"),
    template: str = Query(None, description="Template name (defaults to WA_TEMPLATE_NAME from .env)"),
    name: str = Query("", description="Lead name for body parameter (optional)"),
):
    """
    Send a WhatsApp template message to a phone number for testing.
    Uploads an image for the header (required by vanaha_welcome_5).
    Only sends to whitelisted numbers (safety guard enforced).
    """
    phone_clean = phone.strip().replace("+", "").replace(" ", "").replace("-", "")
    if len(phone_clean) > 10:
        phone_clean = phone_clean[-10:]

    if not can_send_to(phone_clean):
        return {
            "success": False,
            "error": f"Phone {phone_clean} is NOT in the whitelist. Add it to WA_WHITELIST_PHONES in .env",
            "whitelist": sorted(get_whitelist()),
        }

    template_name = template or os.getenv("WA_TEMPLATE_NAME", "hello_world")

    # Upload an image for the template header (vanaha_welcome_5 requires IMAGE header)
    import glob
    header_image_id = None
    media_base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "media")

    # Try elevation image first, then fall back to first amenity photo
    for search_pattern in [
        os.path.join(media_base, "elevation*"),
        os.path.join(media_base, "*.jpg"),
        os.path.join(media_base, "*.jpeg"),
        os.path.join(media_base, "*.png"),
        os.path.join(media_base, "amenities", "*.jpeg"),
        os.path.join(media_base, "amenities", "*.jpg"),
        os.path.join(media_base, "amenities", "*.png"),
    ]:
        matches = sorted(glob.glob(search_pattern))
        if matches:
            img_path = matches[0]
            try:
                with open(img_path, "rb") as f:
                    file_bytes = f.read()
                fname = os.path.basename(img_path)
                ext = fname.rsplit(".", 1)[-1].lower()
                mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext}"
                header_image_id = upload_whatsapp_media(file_bytes, mime, fname)
                if header_image_id:
                    print(f"[WA Test] Uploaded header image: {fname} -> {header_image_id}")
                    break
            except Exception as e:
                print(f"[WA Test] Image upload error: {e}")
            break

    from whatsapp import send_whatsapp_template
    result = send_whatsapp_template(
        to_phone=phone_clean,
        template_name=template_name,
        header_image_id=header_image_id,
    )
    return {
        "phone": phone_clean,
        "template": template_name,
        "header_image_uploaded": header_image_id is not None,
        "header_image_id": header_image_id,
        "result": result,
        "live_mode": is_live_mode(),
        "whitelist": sorted(get_whitelist()),
    }


@app.get("/api/wa/test-text")
def wa_test_send_text(
    phone: str = Query("7276720388", description="Phone number to test"),
    message: str = Query("Hello from LeadPilot! 🏠 This is a test message.", description="Message text"),
):
    """
    Send a plain text WhatsApp message to a phone for testing.
    Only sends to whitelisted numbers (safety guard enforced).
    """
    phone_clean = phone.strip().replace("+", "").replace(" ", "").replace("-", "")
    if len(phone_clean) > 10:
        phone_clean = phone_clean[-10:]

    if not can_send_to(phone_clean):
        return {
            "success": False,
            "error": f"Phone {phone_clean} is NOT in the whitelist.",
            "whitelist": sorted(get_whitelist()),
        }

    result = send_whatsapp_message(phone_clean, message)
    return {
        "phone": phone_clean,
        "message": message,
        "result": result,
    }


# ─── Knowledge Base API ──────────────────────────────────────────────

@app.post("/api/kb/index")
def index_knowledge_base():
    """Index all .txt and .md files in data/knowledge_base/."""
    result = index_kb_folder()
    return result


@app.get("/api/kb/status")
def knowledge_base_status():
    """Get knowledge base status."""
    return get_kb_status()


class KBSearchRequest(BaseModel):
    query: str
    n_results: int = 3


@app.post("/api/kb/search")
def search_knowledge_base(req: KBSearchRequest):
    """Search the knowledge base."""
    results = search_kb(req.query, req.n_results)
    return {"query": req.query, "results": results}

# ─── WhatsApp Webhook API ──────────────────────────────────────────────

@app.get("/webhook")
def verify_whatsapp_webhook(
    request: Request,
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    """Verify WhatsApp webhook subscription."""
    challenge = verify_webhook(hub_mode, hub_verify_token, hub_challenge)
    if challenge:
        return int(challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook")
async def receive_whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    """Receive incoming messages from WhatsApp."""
    payload = await request.json()
    try:
        import json
        print(f"[Webhook Raw] {json.dumps(payload)}")
    except Exception:
        pass
        
    parsed = parse_webhook_message(payload)
    
    if parsed and parsed.get("message_text"):
        # Create or find lead
        phone = parsed["from_phone"]
        phone_clean = phone[-10:] if len(phone) > 10 else phone
        lead = db.query(Lead).filter(
            (Lead.phone == phone) | (Lead.phone == phone_clean) | (Lead.phone.endswith(phone_clean))
        ).first()

        is_new_lead = False
        if not lead:
            is_new_lead = True
            lead = Lead(
                name=parsed.get("sender_name") or phone,
                phone=phone_clean,
                source="whatsapp",
                status="new",
                auto_reply_enabled=True,
                welcome_sent=False,
            )
            db.add(lead)
            db.commit()
            db.refresh(lead)

        # Create incoming message
        message_content = parsed["message_text"]
        
        # If it's a media message with a caption, the text is the caption. 
        # If no caption, it's [type message]. We'll update it once downloaded.
        if parsed.get("media_id"):
            message_content = f"[MEDIA:{parsed['media_id']}] {message_content}"
            
        incoming = Message(
            lead_id=lead.id,
            direction="in",
            channel="whatsapp",
            content=message_content,
            status="received",
            wa_message_id=parsed["message_id"],
            is_read=False,
            is_auto_replied=False,
        )
        db.add(incoming)
        lead.last_message_at = datetime.datetime.now(datetime.timezone.utc)
        lead.unread_count = (lead.unread_count or 0) + 1
        db.commit()

        if parsed.get("media_id"):
            from whatsapp import download_whatsapp_media
            import threading
            import os
            
            def _download_media_bg(media_id, msg_id, media_type, caption):
                try:
                    result = download_whatsapp_media(media_id)
                    if result:
                        file_bytes, mime = result
                        ext = mime.split('/')[-1] if '/' in mime else 'bin'
                        if ext == 'jpeg': ext = 'jpg'
                        filename = f"incoming_{msg_id}.{ext}"
                        
                        media_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "media")
                        incoming_dir = os.path.join(media_dir, "incoming")
                        os.makedirs(incoming_dir, exist_ok=True)
                        filepath = os.path.join(incoming_dir, filename)
                        
                        with open(filepath, "wb") as f:
                            f.write(file_bytes)
                        
                        # Update the DB message
                        from db import SessionLocal
                        s_db = SessionLocal()
                        try:
                            msg = s_db.query(Message).filter(Message.wa_message_id == msg_id).first()
                            if msg:
                                tag = "IMAGE" if "image" in mime else "VIDEO" if "video" in mime else media_type.upper()
                                msg.content = f"[{tag}:incoming/{filename}] {caption}".strip()
                                s_db.commit()
                        finally:
                            s_db.close()
                    else:
                        print(f"Failed to download media: {media_id}")
                        from db import SessionLocal
                        s_db = SessionLocal()
                        try:
                            msg = s_db.query(Message).filter(Message.wa_message_id == msg_id).first()
                            if msg:
                                msg.content = f"⚠️ Failed to download attached {media_type}. {caption}".strip()
                                s_db.commit()
                        finally:
                            s_db.close()
                except Exception as e:
                    print(f"Error downloading media bg: {e}")
                    
            t = threading.Thread(target=_download_media_bg, args=(
                parsed["media_id"], 
                parsed["message_id"], 
                parsed.get("type", "media"),
                parsed["message_text"] if not parsed["message_text"].startswith("[") else ""
            ))
            t.daemon = True
            t.start()
        # Let the followup.py background poller handle the welcome media sequence 
        # and AI reply generation. This guarantees no race conditions.

    return {"status": "ok"}

# ─── Run Server ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")
