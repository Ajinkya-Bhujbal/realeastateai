"""
Real Estate Lead Management System - Main API
FastAPI single app with all endpoints.
"""
import sys
import os
import datetime
from contextlib import asynccontextmanager
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

# Add backend dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_db, init_db
from models import Lead, Message, Property, FollowUpSchedule
from parser import parse_lead_from_email, fetch_gmail_leads
from whatsapp import send_whatsapp_message, verify_webhook, parse_webhook_message
from ai import (
    check_ollama, list_models, generate_lead_reply,
    generate_followup_message, generate_property_recommendation,
    generate_auto_reply, summarize_lead,
)
from rag import search_properties, index_property, load_sample_properties, index_properties_bulk
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
    notes: Optional[str] = None

class EmailParseRequest(BaseModel):
    subject: str
    body: str
    sender: str = ""

class GmailFetchRequest(BaseModel):
    gmail_user: str
    gmail_app_password: str
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
        "timestamp": datetime.datetime.utcnow().isoformat(),
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
                "notes": l.notes,
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
    lead.updated_at = datetime.datetime.utcnow()
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
    """Fetch leads from Gmail inbox."""
    leads = fetch_gmail_leads(req.gmail_user, req.gmail_app_password, req.max_emails)
    created = 0
    skipped = 0
    for parsed in leads:
        # Check duplicate
        if parsed.get("phone"):
            existing = db.query(Lead).filter(Lead.phone == parsed["phone"]).first()
            if existing:
                skipped += 1
                continue
        if parsed.get("email"):
            existing = db.query(Lead).filter(Lead.email == parsed["email"]).first()
            if existing:
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
            notes=parsed.get("notes", ""),
        )
        db.add(lead)
        created += 1

    db.commit()
    return {"created": created, "skipped": skipped, "total_found": len(leads)}


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
        lead.updated_at = datetime.datetime.utcnow()

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
    """Receive incoming WhatsApp messages."""
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
    # Strip country code for matching
    phone_clean = phone[-10:] if len(phone) > 10 else phone
    lead = db.query(Lead).filter(
        (Lead.phone == phone) | (Lead.phone == phone_clean) | (Lead.phone.endswith(phone_clean))
    ).first()

    if not lead:
        # Auto-create lead from incoming message
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

    # Save incoming message
    incoming = Message(
        lead_id=lead.id,
        direction="in",
        channel="whatsapp",
        content=text,
        status="received",
        wa_message_id=parsed.get("message_id", ""),
    )
    db.add(incoming)

    # Generate and send auto-reply
    context = f"Budget: {lead.budget_min}-{lead.budget_max}L, Location: {lead.preferred_location}, Type: {lead.property_type}"
    reply_text = generate_auto_reply(text, lead.name, context)

    if reply_text and not reply_text.startswith("["):
        result = send_whatsapp_message(phone, reply_text)
        outgoing = Message(
            lead_id=lead.id,
            direction="out",
            channel="whatsapp",
            content=reply_text,
            status="sent" if result.get("success") or result.get("mock") else "failed",
            wa_message_id=result.get("message_id", ""),
        )
        db.add(outgoing)

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
            {"id": l.id, "name": l.name, "source": l.source, "status": l.status, "created_at": l.created_at.isoformat() if l.created_at else None}
            for l in recent
        ],
    }


# ─── Run Server ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
