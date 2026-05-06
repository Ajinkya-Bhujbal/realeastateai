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
from models import Lead, Message, Property, FollowUpSchedule
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
from followup import start_scheduler, stop_scheduler, create_followup_schedule


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
    """Create a new lead."""
    db_lead = Lead(**lead.model_dump())
    db.add(db_lead)
    db.commit()
    db.refresh(db_lead)
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
    """List all leads with optional filters."""
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
    leads = q.order_by(Lead.created_at.desc()).offset(skip).limit(limit).all()

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
                "created_at": l.created_at.isoformat() if l.created_at else None,
                "updated_at": l.updated_at.isoformat() if l.updated_at else None,
            }
            for l in leads
        ],
    }


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
    }


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

    messages = (
        db.query(Message)
        .filter(Message.lead_id == lead_id)
        .order_by(Message.created_at.asc())
        .limit(limit)
        .all()
    )
    return {
        "lead_id": lead.id,
        "name": lead.name,
        "phone": lead.phone,
        "status": lead.status,
        "auto_reply_enabled": lead.auto_reply_enabled if lead.auto_reply_enabled is not None else True,
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

    # Trigger welcome sequence for first-time leads
    if not lead.welcome_sent:
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
        # Send full welcome sequence in background
        import threading
        from welcome_sequence import send_welcome_sequence

        def _run(phone_num, lid):
            try:
                result = send_welcome_sequence(phone_num)
                print(f"Force welcome sent to {phone_num}: {result}")
                wdb = SessionLocal()
                try:
                    wlead = wdb.query(Lead).filter(Lead.id == lid).first()
                    if wlead:
                        wlead.welcome_sent = True
                        from welcome_sequence import get_welcome_db_messages
                        for m in get_welcome_db_messages():
                            wdb.add(Message(lead_id=lid, direction="out", channel="whatsapp",
                                            content=m["content"], status="sent", is_read=True))
                    wdb.commit()
                finally:
                    wdb.close()
            except Exception as e:
                print(f"Force welcome error: {e}")

        thread = threading.Thread(target=_run, args=(phone, lead.id))
        thread.daemon = True
        thread.start()
        return {"status": "ok", "message": "Welcome sequence started"}


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
        incoming = Message(
            lead_id=lead.id,
            direction="in",
            channel="whatsapp",
            content=parsed["message_text"],
            status="received",
            wa_message_id=parsed["message_id"],
            is_read=False,
            is_auto_replied=False,
        )
        db.add(incoming)
        lead.last_message_at = datetime.datetime.now(datetime.timezone.utc)
        lead.unread_count = (lead.unread_count or 0) + 1
        db.commit()

        # Send welcome sequence if this is the first reply (template reply)
        if not lead.welcome_sent:
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

    return {"status": "ok"}

# ─── Run Server ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")
