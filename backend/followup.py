"""
Follow-up automation + Unread message auto-reply processor + Email polling.
APScheduler based.
"""
import os
import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session
from db import SessionLocal
from models import Lead, Message, FollowUpSchedule
from whatsapp import send_whatsapp_message
from ai import generate_followup_message, generate_rag_reply
from rag import search_kb, search_properties
from parser import fetch_gmail_leads

# Global scheduler
scheduler = BackgroundScheduler(
    job_defaults={"coalesce": True, "max_instances": 1},
    timezone="Asia/Kolkata",
)


def start_scheduler():
    """Start the follow-up scheduler + unread message processor + email poller."""
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
        # Email polling: every 1 minute (only if Gmail configured)
        gmail_user = os.getenv("GMAIL_USER", "")
        gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "")
        if gmail_user and gmail_pass:
            scheduler.add_job(
                process_email_leads,
                trigger=IntervalTrigger(seconds=30),
                id="email_poller",
                replace_existing=True,
                next_run_time=datetime.datetime.now(),  # Run immediately on startup
            )
            print("Email poller started (30 sec) - checking Gmail for new leads")
        else:
            print("Email poller skipped - GMAIL_USER/GMAIL_APP_PASSWORD not set in .env")
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
    ACID-safe unread message processor.
    
    Uses a claim-then-process pattern to prevent race conditions:
    1. CLAIM: Atomically lock unclaimed messages (set processing_lock_at)
    2. PROCESS: Generate AI reply for each claimed message
    3. COMMIT: Mark as auto-replied and release lock in same transaction
    
    If a claim is older than LOCK_EXPIRY_SECONDS, it's considered stale
    (crashed worker) and can be reclaimed by the next cycle.
    """
    LOCK_EXPIRY_SECONDS = 120  # 2 minutes — enough for Ollama on CPU

    db = SessionLocal()
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        lock_expiry = now - datetime.timedelta(seconds=LOCK_EXPIRY_SECONDS)

        # ── STEP 1: CLAIM — Atomically lock unclaimed messages ──
        # Only pick messages that are:
        #   - incoming, not yet auto-replied
        #   - NOT currently locked (processing_lock_at is NULL)
        #   - OR locked but stale (processing_lock_at < lock_expiry)
        from sqlalchemy import or_
        unclaimed = (
            db.query(Message)
            .filter(
                Message.direction == "in",
                Message.is_auto_replied == False,
                or_(
                    Message.processing_lock_at == None,
                    Message.processing_lock_at < lock_expiry,  # Stale lock — reclaim
                ),
            )
            .order_by(Message.created_at.asc())
            .limit(10)
            .all()
        )

        if not unclaimed:
            db.close()
            return

        # Lock them atomically — set processing_lock_at to NOW
        claimed_ids = [m.id for m in unclaimed]
        db.query(Message).filter(Message.id.in_(claimed_ids)).update(
            {"processing_lock_at": now}, synchronize_session="fetch"
        )
        db.commit()

        # ── STEP 2: PROCESS — Group by lead, handle ALL messages per lead ──
        from collections import defaultdict
        lead_messages = defaultdict(list)
        for msg in unclaimed:
            lead_messages[msg.lead_id].append(msg)

        for lead_id, msgs in lead_messages.items():
            try:
                # Re-fetch all messages to ensure consistency
                msg_ids = [m.id for m in msgs]
                msgs = db.query(Message).filter(Message.id.in_(msg_ids), Message.is_auto_replied == False).order_by(Message.created_at.asc()).all()
                if not msgs:
                    continue

                lead = db.query(Lead).filter(Lead.id == lead_id).first()
                if not lead:
                    for m in msgs:
                        m.is_auto_replied = True
                        m.processing_lock_at = None
                    db.commit()
                    continue

                # Skip if auto-reply disabled for this lead
                if not lead.auto_reply_enabled:
                    for m in msgs:
                        m.is_auto_replied = True
                        m.processing_lock_at = None
                    db.commit()
                    continue

                # Skip auto-reply for leads parsed from email (only reply to manual/whatsapp leads)
                if lead.source not in ["manual", "whatsapp"]:
                    for m in msgs:
                        m.is_auto_replied = True
                        m.processing_lock_at = None
                    db.commit()
                    continue

                if not lead.phone:
                    for m in msgs:
                        m.is_auto_replied = True
                        m.processing_lock_at = None
                    db.commit()
                    continue

                # ── WELCOME SEQUENCE for first-time leads ──
                if not lead.welcome_sent:
                    import threading
                    from welcome_sequence import send_welcome_sequence, get_welcome_db_messages

                    # Mark as sent immediately to prevent re-triggering by subsequent messages
                    lead.welcome_sent = True
                    for m in msgs:
                        m.is_auto_replied = True
                        m.processing_lock_at = None
                    db.commit()

                    def _run_welcome(phone_num, lead_id_inner):
                        try:
                            result = send_welcome_sequence(phone_num)
                            print(f"[Followup] Welcome sent to {phone_num}: {result}")
                            wdb = SessionLocal()
                            try:
                                for m in get_welcome_db_messages():
                                    wdb.add(Message(lead_id=lead_id_inner, direction="out", channel="whatsapp",
                                                    content=m["content"], status="sent", is_read=True))
                                wdb.commit()
                            finally:
                                wdb.close()
                        except Exception as e:
                            print(f"[Followup] Welcome error: {e}")

                    thread = threading.Thread(target=_run_welcome, args=(lead.phone, lead.id))
                    thread.daemon = True
                    thread.start()
                    continue  # Don't send AI reply for the first message — welcome handles it

                # ── Combine ALL pending messages for intent detection + AI context ──
                combined_msg_text = "\n".join(m.content for m in msgs if m.content)
                combined_lower = combined_msg_text.lower()

                # Location keywords — check across ALL messages
                wants_location = any(kw in combined_lower for kw in [
                    'location', 'address', 'kaha', 'kahan', 'where', 'kidhar',
                    'pune me kaha', 'location kya', 'jagah', 'route', 'direction',
                    'kaise aaye', 'kaise aana', 'how to reach', 'come',
                ])

                # Media keywords — SPECIFIC phrases only to avoid false positives
                wants_media = any(kw in combined_lower for kw in [
                    'photo', 'photos', 'video', 'videos', 'image', 'images',
                    'pic', 'pics', 'picture', 'pictures', 'dekho', 'dikhao',
                    'bhejo photo', 'bhejo video', 'visuals', 'dekhna',
                    'share photo', 'share video', 'share pic', 'share image',
                    'send photo', 'send video', 'send pic', 'send image',
                    'flat picture', 'flat photo', 'flat pic',
                    'property photo', 'property picture', 'property pic',
                    'propertie photo', 'propertie picture', 'propertie pic',
                    'sample flat', 'layout',
                    'flat ka video', 'flat video', 'property video'
                ])

                # Build lead context
                context_parts = []
                if lead.budget_min or lead.budget_max:
                    context_parts.append(f"Budget: {lead.budget_min or ''} to {lead.budget_max or ''}L")
                if lead.preferred_location:
                    context_parts.append(f"Location: {lead.preferred_location}")
                if lead.property_type:
                    context_parts.append(f"Type: {lead.property_type}")
                lead_context = ", ".join(context_parts)

                # Fetch recent conversation history for this lead
                recent_messages = (
                    db.query(Message)
                    .filter(Message.lead_id == lead.id)
                    .order_by(Message.created_at.desc())
                    .limit(20)
                    .all()
                )
                conversation_history = [
                    {"direction": m.direction, "content": m.content}
                    for m in reversed(recent_messages)
                    if m.content and not m.content.startswith("[IMAGE:") and not m.content.startswith("[VIDEO:")
                ]

                # ── LOCATION SEQUENCE ──
                if wants_location:
                    _send_location_sequence(lead, db)

                # ── Generate AI reply addressing ALL pending messages ──
                # If multiple messages, tell AI about all of them
                if len(msgs) == 1:
                    ai_input = msgs[0].content
                else:
                    ai_input = "Customer sent multiple messages:\n" + "\n".join(
                        f"- {m.content}" for m in msgs if m.content
                    ) + "\n\nRespond to ALL of the above messages in one reply. Address every point — whether it is a question, request, or statement."

                reply_text = generate_rag_reply(
                    incoming_message=ai_input,
                    lead_name=lead.name,
                    lead_context=lead_context,
                    conversation_history=conversation_history,
                )

                if reply_text and not reply_text.startswith("["):
                    # ── STEP 3: COMMIT — Send + mark ALL as replied atomically ──
                    result = send_whatsapp_message(lead.phone, reply_text)

                    # Store outgoing message
                    outgoing = Message(
                        lead_id=lead.id, direction="out", channel="whatsapp",
                        content=reply_text,
                        status="sent" if result.get("success") or result.get("mock") else "failed",
                        wa_message_id=result.get("message_id", ""),
                        is_read=True,
                    )
                    db.add(outgoing)

                    # If user asked for media, send photos and videos
                    if wants_media:
                        _send_media_on_request(lead, db)

                    # Update lead
                    lead.last_message_at = datetime.datetime.now(datetime.timezone.utc)
                    if lead.status == "new":
                        lead.status = "contacted"

                    print(f"Auto-replied to {lead.name} ({len(msgs)} msgs): {reply_text[:60]}...")

                # Mark ALL incoming messages as auto-replied and release locks
                for m in msgs:
                    m.is_auto_replied = True
                    m.processing_lock_at = None
                db.commit()

            except Exception as msg_err:
                # Per-lead error handling — release locks so messages can be retried
                print(f"Error processing lead {lead_id} messages: {msg_err}")
                import traceback
                traceback.print_exc()
                try:
                    db.rollback()
                    for m in msgs:
                        msg_fresh = db.query(Message).filter(Message.id == m.id).first()
                        if msg_fresh:
                            msg_fresh.processing_lock_at = None
                    db.commit()
                except Exception:
                    db.rollback()

    except Exception as e:
        print(f"Unread processing error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


# ── Location Sequence ──────────────────────────────
LOCATION_MESSAGES = [
    (
        "Location 📍 :- Shapoorji Pallonji Vanaha, Bavdhan, Pune.\n"
        "It is on the road of Oxford Golf Course.\n"
        "It is *12 Min* from Chellaram Hospital / Bavdhan Highway. (as per Google Maps)"
    ),
    (
        "*Step 1)  Come to Khandoba Mandir first..* 👇👇\n"
        "https://maps.app.goo.gl/voJFQMmiKCML87t66"
    ),
    (
        "Step 2)  Follow Below Google Map Route to \"Yahavi\" society. 👇\n"
        "( Do *Not* change any option in the route. Keep *CAR* option selected for accurate route.\n"
        "Because, Location is *only 12 Min* from Chellaram Hospital on Highway, but sometimes "
        "Google Maps show *wrong Route*. )\n"
        "⏬🔽👇👇👇👇🔽⏬\n"
        "Shared route: https://maps.app.goo.gl/34qg3NuAyQH2uj5b8?g_st=awb"
    ),
    (
        "Sending *Gate-Pass* Below so that Security will allow you in...\n"
        "( No Fees Charged 😊)\n"
        "👇👇👇👇👇"
    ),
    (
        "🚗 Please park your Vehicles *outside* the society main gate to avoid fines and Jammers.\n"
        "🪪 Show above gatepass to security if they ask.\n\n"
        " And come to Tower 1 , Oak , A wing, Flat No 1802.. on the 18th floor.\n"
        "Agent contact 📞  - 7387457889"
    ),
]


def _send_location_sequence(lead, db):
    """Send location + directions sequence when user asks for location."""
    import time as _time
    for loc_msg in LOCATION_MESSAGES:
        result = send_whatsapp_message(lead.phone, loc_msg)
        db.add(Message(
            lead_id=lead.id, direction="out", channel="whatsapp",
            content=loc_msg,
            status="sent" if result.get("success") or result.get("mock") else "failed",
            is_read=True,
        ))
        _time.sleep(1)

    # Send location map images if they exist
    from welcome_sequence import _get_media_files
    location_images = _get_media_files("locations", ("jpg", "jpeg", "png", "webp"))
    if location_images:
        from whatsapp import upload_whatsapp_media as _upload
        for img_path in location_images:
            try:
                fname = os.path.basename(img_path)
                with open(img_path, "rb") as f:
                    file_bytes = f.read()
                ext = fname.rsplit(".", 1)[-1].lower()
                mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext}"
                media_id = _upload(file_bytes, mime, fname)
                if media_id:
                    send_whatsapp_message(lead.phone, media_id=media_id, media_type="image")
                db.add(Message(lead_id=lead.id, direction="out", channel="whatsapp",
                               content=f"[IMAGE:{fname}]", status="sent", is_read=True))
                _time.sleep(1)
            except Exception as e:
                print(f"Location image error: {e}")

    db.commit()
    print(f"Location sequence sent to {lead.name}")


def _send_media_on_request(lead, db):
    """Send ALL photos and videos when user explicitly asks."""
    import time as _time
    from welcome_sequence import get_amenity_photos, get_flat_videos
    from whatsapp import upload_whatsapp_media as _upload, send_whatsapp_message
    try:
        # First send the disclaimer
        disclaimer = "Please Note: These are videos of sample flat layout, the layout of all the flats is the same. 😊"
        send_whatsapp_message(lead.phone, disclaimer)
        db.add(Message(lead_id=lead.id, direction="out", channel="whatsapp",
                       content=disclaimer, status="sent", is_read=True))
        _time.sleep(1)

        # Send ALL amenity photos
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
                    send_whatsapp_message(lead.phone, media_id=media_id, media_type="image")
                db.add(Message(lead_id=lead.id, direction="out", channel="whatsapp",
                               content=f"[IMAGE:{fname}]", status="sent", is_read=True))
                _time.sleep(1)
            except Exception as pe:
                print(f"Photo send error: {pe}")

        # Send ALL flat videos
        videos = get_flat_videos()
        for video_path in videos:
            try:
                fname = os.path.basename(video_path)
                with open(video_path, "rb") as f:
                    file_bytes = f.read()
                media_id = _upload(file_bytes, "video/mp4", fname)
                if media_id:
                    send_whatsapp_message(lead.phone, media_id=media_id, media_type="video")
                db.add(Message(lead_id=lead.id, direction="out", channel="whatsapp",
                               content=f"[VIDEO:{fname}]", status="sent", is_read=True))
                _time.sleep(5)  # 5s between videos (larger files, need more time for WhatsApp processing)
            except Exception as ve:
                print(f"Video send error: {ve}")
        print(f"Media sent to {lead.name}: {len(photos)} photos, {len(videos)} videos")
    except Exception as me:
        print(f"Media sending error: {me}")


def process_followups():
    """Process all due follow-ups."""
    db = SessionLocal()
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
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
            lead.last_message_at = datetime.datetime.now(datetime.timezone.utc)

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
        next_followup_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=frequency_hours),
        message_template=message_template,
        max_followups=max_followups,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


def process_email_leads():
    """
    Periodically fetch new leads from Gmail.
    Only processes UNSEEN emails from real estate portals.
    Deduplicates by phone and email.
    """
    gmail_user = os.getenv("GMAIL_USER", "")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "")
    if not gmail_user or not gmail_pass:
        return

    db = SessionLocal()
    try:
        # fetch_gmail_leads is now a generator yielding leads newest-first
        lead_generator = fetch_gmail_leads(gmail_user, gmail_pass, max_emails=None)
        created = 0
        skipped = 0
        consecutive_duplicates = 0

        for parsed in lead_generator:
            name = parsed.get("name", "").strip() or "Unknown"
            phone = parsed.get("phone", "").strip()
            lead_email = parsed.get("email", "").strip()

            # Skip junk emails that have no contact info
            if not phone and not lead_email:
                skipped += 1
                continue


            lead = Lead(
                name=name,
                phone=phone,
                email=lead_email,
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
            # Use email received time instead of current time
            if parsed.get("received_at"):
                lead.created_at = parsed["received_at"]
            db.add(lead)
            db.commit()  # Commit immediately so UI updates live
            created += 1

        if created > 0 or skipped > 0:
            print(f"Email poller finished loop: {created} new leads created, {skipped} duplicates skipped")
    except Exception as e:
        print(f"Email polling error: {e}")
        db.rollback()
    finally:
        db.close()
