"""
Follow-up automation - APScheduler based.
Handles scheduled follow-ups with customizable frequency.
"""
import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session
from db import SessionLocal
from models import Lead, Message, FollowUpSchedule
from whatsapp import send_whatsapp_message
from ai import generate_followup_message

# Global scheduler
scheduler = BackgroundScheduler(
    job_defaults={"coalesce": True, "max_instances": 1},
    timezone="Asia/Kolkata",
)


def start_scheduler():
    """Start the follow-up scheduler. Checks every 5 minutes."""
    if not scheduler.running:
        scheduler.add_job(
            process_followups,
            trigger=IntervalTrigger(minutes=5),
            id="followup_processor",
            replace_existing=True,
        )
        scheduler.start()
        print("Follow-up scheduler started (checks every 5 minutes)")


def stop_scheduler():
    """Stop the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("Follow-up scheduler stopped")


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

            # Get last message for context
            last_msg = (
                db.query(Message)
                .filter(Message.lead_id == lead.id)
                .order_by(Message.created_at.desc())
                .first()
            )

            # Generate follow-up message
            if fup.message_template:
                message = fup.message_template.replace("{name}", lead.name)
            else:
                message = generate_followup_message(
                    lead_name=lead.name,
                    interaction_count=fup.followups_sent + 1,
                    last_message=last_msg.content if last_msg else "",
                )

            # Send via WhatsApp
            result = send_whatsapp_message(lead.phone, message)

            # Log message
            msg = Message(
                lead_id=lead.id,
                direction="out",
                channel="whatsapp",
                content=message,
                status="sent" if result.get("success") else "failed",
                wa_message_id=result.get("message_id", ""),
            )
            db.add(msg)

            # Update follow-up schedule
            fup.followups_sent += 1
            fup.next_followup_at = now + datetime.timedelta(hours=fup.frequency_hours)

            if fup.followups_sent >= fup.max_followups:
                fup.is_active = False

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
    # Deactivate existing schedules for this lead
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
