"""
Follow-up automation + Unread message auto-reply processor.
APScheduler based.
"""
import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session
from db import SessionLocal
from models import Lead, Message, FollowUpSchedule
from whatsapp import send_whatsapp_message
from ai import generate_followup_message, generate_rag_reply
from rag import search_kb, search_properties

# Global scheduler
scheduler = BackgroundScheduler(
    job_defaults={"coalesce": True, "max_instances": 1},
    timezone="Asia/Kolkata",
)


def start_scheduler():
    """Start the follow-up scheduler + unread message processor."""
    if not scheduler.running:
        # Follow-up processor: every 5 minutes
        scheduler.add_job(
            process_followups,
            trigger=IntervalTrigger(minutes=5),
            id="followup_processor",
            replace_existing=True,
        )
        # Unread message auto-reply: every 10 seconds
        scheduler.add_job(
            process_unread_messages,
            trigger=IntervalTrigger(seconds=10),
            id="unread_processor",
            replace_existing=True,
        )
        scheduler.start()
        print("Follow-up scheduler started (5 min)")
        print("Unread auto-reply processor started (10 sec)")


def stop_scheduler():
    """Stop the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("Schedulers stopped")


def process_unread_messages():
    """
    Process unread incoming messages:
    1. Find all unread, un-replied incoming messages
    2. For each, generate AI reply using RAG (knowledge base + properties)
    3. Send reply via WhatsApp
    4. Store in DB
    """
    db = SessionLocal()
    try:
        # Find unread incoming messages that haven't been auto-replied
        unread = (
            db.query(Message)
            .filter(
                Message.direction == "in",
                Message.is_auto_replied == False,
            )
            .order_by(Message.created_at.asc())
            .limit(5)  # Process max 5 at a time
            .all()
        )

        for msg in unread:
            lead = db.query(Lead).filter(Lead.id == msg.lead_id).first()
            if not lead:
                msg.is_auto_replied = True
                continue

            # Skip if auto-reply disabled for this lead
            if not lead.auto_reply_enabled:
                msg.is_auto_replied = True
                continue

            if not lead.phone:
                msg.is_auto_replied = True
                continue

            # Build lead context
            lead_context = f"Budget: {lead.budget_min or '?'}-{lead.budget_max or '?'}L, Location: {lead.preferred_location or '?'}, Type: {lead.property_type or '?'}"

            # Search knowledge base for relevant info
            kb_results = []
            try:
                kb_results = search_kb(msg.content, n_results=3)
            except Exception as e:
                print(f"KB search error: {e}")

            # Search properties for relevant matches
            property_results = []
            try:
                property_results = search_properties(msg.content, n_results=2)
            except Exception as e:
                print(f"Property search error: {e}")

            # Generate AI reply with RAG context
            reply_text = generate_rag_reply(
                incoming_message=msg.content,
                lead_name=lead.name,
                lead_context=lead_context,
                kb_results=kb_results,
                property_results=property_results,
            )

            if reply_text and not reply_text.startswith("["):
                # Send via WhatsApp
                result = send_whatsapp_message(lead.phone, reply_text)

                # Store outgoing message
                outgoing = Message(
                    lead_id=lead.id,
                    direction="out",
                    channel="whatsapp",
                    content=reply_text,
                    status="sent" if result.get("success") or result.get("mock") else "failed",
                    wa_message_id=result.get("message_id", ""),
                    is_read=True,
                    is_auto_replied=False,
                )
                db.add(outgoing)

                # Update lead
                lead.last_message_at = datetime.datetime.utcnow()
                if lead.status == "new":
                    lead.status = "contacted"

                print(f"Auto-replied to {lead.name}: {reply_text[:60]}...")

            # Mark incoming message as auto-replied
            msg.is_auto_replied = True

        db.commit()
    except Exception as e:
        print(f"Unread processing error: {e}")
        db.rollback()
    finally:
        db.close()


def process_followups():
    """Process all due follow-ups."""
    db = SessionLocal()
    try:
        now = datetime.datetime.utcnow()
        due_followups = (
            db.query(FollowUpSchedule)
            .filter(
                FollowUpSchedule.is_active == True,
                FollowUpSchedule.next_followup_at <= now,
                FollowUpSchedule.followups_sent < FollowUpSchedule.max_followups,
            )
            .all()
        )

        for fup in due_followups:
            lead = db.query(Lead).filter(Lead.id == fup.lead_id).first()
            if not lead or not lead.phone:
                fup.is_active = False
                continue

            last_msg = (
                db.query(Message)
                .filter(Message.lead_id == lead.id)
                .order_by(Message.created_at.desc())
                .first()
            )

            if fup.message_template:
                message = fup.message_template.replace("{name}", lead.name)
            else:
                message = generate_followup_message(
                    lead_name=lead.name,
                    interaction_count=fup.followups_sent + 1,
                    last_message=last_msg.content if last_msg else "",
                )

            result = send_whatsapp_message(lead.phone, message)

            msg = Message(
                lead_id=lead.id,
                direction="out",
                channel="whatsapp",
                content=message,
                status="sent" if result.get("success") else "failed",
                wa_message_id=result.get("message_id", ""),
                is_read=True,
            )
            db.add(msg)

            fup.followups_sent += 1
            fup.next_followup_at = now + datetime.timedelta(hours=fup.frequency_hours)

            if fup.followups_sent >= fup.max_followups:
                fup.is_active = False

            # Update lead last_message_at
            lead.last_message_at = datetime.datetime.utcnow()

            print(f"Follow-up sent to {lead.name} ({lead.phone}) - #{fup.followups_sent}")

        db.commit()
    except Exception as e:
        print(f"Follow-up processing error: {e}")
        db.rollback()
    finally:
        db.close()


def create_followup_schedule(
    db: Session,
    lead_id: int,
    frequency_hours: int = 24,
    max_followups: int = 5,
    message_template: str = None,
) -> FollowUpSchedule:
    """Create a new follow-up schedule for a lead."""
    existing = (
        db.query(FollowUpSchedule)
        .filter(FollowUpSchedule.lead_id == lead_id, FollowUpSchedule.is_active == True)
        .all()
    )
    for ex in existing:
        ex.is_active = False

    schedule = FollowUpSchedule(
        lead_id=lead_id,
        frequency_hours=frequency_hours,
        next_followup_at=datetime.datetime.utcnow() + datetime.timedelta(hours=frequency_hours),
        message_template=message_template,
        max_followups=max_followups,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule
