"""
Follow-up automation + Unread message auto-reply processor + Email polling.
APScheduler based.
"""
import os
import re
import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session
from db import SessionLocal
from models import Lead, Message, FollowUpSchedule, RawEmail
from wa_guard import can_send_to
from whatsapp import send_whatsapp_message
from ai import generate_followup_message, generate_rag_reply
from rag import search_kb, search_properties
from parser import fetch_gmail_leads, mark_email_seen

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

                if not lead.phone:
                    for m in msgs:
                        m.is_auto_replied = True
                        m.processing_lock_at = None
                    db.commit()
                    continue

                # ── WA Safety Guard: skip if not allowed to send ──
                if not can_send_to(lead.phone):
                    print(f"[WA Guard] Blocked send to {lead.phone} (live mode OFF, not in whitelist)")
                    for m in msgs:
                        m.is_auto_replied = True
                        m.processing_lock_at = None
                    db.commit()
                    continue

                # ── Defer AI if welcome sequence is currently running ──
                if lead.status == "welcoming":
                    for m in msgs:
                        m.processing_lock_at = None
                    db.commit()
                    continue



                # ── Combine ALL pending messages for intent detection + AI context ──
                combined_msg_text = "\n".join(m.content for m in msgs if m.content)
                
                # Strip system tags (like [IMAGE:...]) so we don't false-trigger wants_media when they send a photo
                import re
                clean_text = re.sub(r'\[(?:image|video|audio|document|IMAGE|VIDEO)[^\]]*\]', '', combined_msg_text, flags=re.IGNORECASE)
                combined_lower = clean_text.lower()

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

                # Fetch recent conversation history for this lead (last 30 messages)
                recent_messages = (
                    db.query(Message)
                    .filter(Message.lead_id == lead.id)
                    .order_by(Message.created_at.desc())
                    .limit(30)
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
                    # Only mark messages that contain location keywords as replied
                    # Leave other messages (e.g. "what is the rent?") for the AI
                    location_kws = ['location', 'address', 'kaha', 'kahan', 'where', 'kidhar',
                                    'pune me kaha', 'location kya', 'jagah', 'route', 'direction',
                                    'kaise aaye', 'kaise aana', 'how to reach', 'come']
                    has_non_location = False
                    for m in msgs:
                        m_lower = (m.content or '').lower()
                        if any(kw in m_lower for kw in location_kws):
                            m.is_auto_replied = True
                        else:
                            has_non_location = True
                        m.processing_lock_at = None
                    db.commit()
                    if not has_non_location:
                        continue  # All messages were location — skip AI
                    # else: fall through to AI reply for remaining messages

                # ── MEDIA SEQUENCE (user explicitly asked for photos/videos) ──
                if wants_media:
                    import threading

                    def _run_media_sequence(phone_num, lead_id_inner, lead_name_inner):
                        """Send photos + videos in the exact sequence, then check for new messages."""
                        import time as _time
                        from welcome_sequence import get_amenity_photos, get_flat_videos
                        from whatsapp import upload_whatsapp_media as _upload, send_whatsapp_message
                        wdb = SessionLocal()
                        try:
                            # ── Step 1: Photo intro message ──
                            photo_intro = (
                                "Please find below the photos of Free to use, Lavish Amenities in the society.\n"
                                "(Note: All photos are real. \U0001f60a)\n"
                                "\U0001f447\U0001f447\U0001f447\U0001f447\U0001f447\U0001f447\U0001f447\U0001f447"
                            )
                            send_whatsapp_message(phone_num, photo_intro)
                            wdb.add(Message(lead_id=lead_id_inner, direction="out", channel="whatsapp",
                                           content=photo_intro, status="sent", is_read=True))
                            wdb.commit()

                            # ── Step 2: Send ALL amenity photos (2s between each) ──
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
                                    wdb.add(Message(lead_id=lead_id_inner, direction="out", channel="whatsapp",
                                                   content=f"[IMAGE:{fname}]", status="sent", is_read=True))
                                    wdb.commit()
                                    _time.sleep(2)
                                except Exception as pe:
                                    try:
                                        print(f"Photo send error: {str(pe).encode('ascii','replace').decode()}")
                                    except Exception:
                                        pass

                            # ── Step 3: Wait 30 seconds after photos ──
                            _time.sleep(30)

                            # ── Step 4: Video intro message ──
                            video_intro = (
                                "Please find below the Videos of available flats for Sell and Rent both.\n"
                                "( 1 / 2 / 2.5 / 3 / 4 BHK available )\n"
                                "\U0001f447\U0001f447\U0001f447\U0001f447\U0001f447\U0001f447\U0001f447\U0001f447"
                            )
                            send_whatsapp_message(phone_num, video_intro)
                            wdb.add(Message(lead_id=lead_id_inner, direction="out", channel="whatsapp",
                                           content=video_intro, status="sent", is_read=True))
                            wdb.commit()

                            # ── Step 5: Send ALL flat videos (5s between each) ──
                            videos = get_flat_videos()
                            for video_path in videos:
                                try:
                                    fname = os.path.basename(video_path)
                                    with open(video_path, "rb") as f:
                                        file_bytes = f.read()
                                    media_id = _upload(file_bytes, "video/mp4", fname)
                                    if media_id:
                                        send_whatsapp_message(phone_num, message=fname, media_id=media_id, media_type="video")
                                    wdb.add(Message(lead_id=lead_id_inner, direction="out", channel="whatsapp",
                                                   content=f"[VIDEO:{fname}]", status="sent", is_read=True))
                                    wdb.commit()
                                    _time.sleep(5)
                                except Exception as ve:
                                    try:
                                        print(f"Video send error: {str(ve).encode('ascii','replace').decode()}")
                                    except Exception:
                                        pass

                            # ── Step 6: Wait 30 seconds after videos ──
                            _time.sleep(30)

                            try:
                                print(f"[MediaRequest] Sent to {phone_num}: {len(photos)} photos, {len(videos)} videos")
                            except Exception:
                                pass

                            # ── Step 7: Check for unread messages that arrived during media sending ──
                            _time.sleep(5)
                            new_msgs = (
                                wdb.query(Message)
                                .filter(
                                    Message.lead_id == lead_id_inner,
                                    Message.direction == "in",
                                    Message.is_auto_replied == False,
                                )
                                .order_by(Message.created_at)
                                .all()
                            )
                            if new_msgs:
                                combined = "\n".join(m.content for m in new_msgs if m.content)
                                if combined.strip():
                                    # Get conversation history
                                    recent = (
                                        wdb.query(Message)
                                        .filter(Message.lead_id == lead_id_inner)
                                        .order_by(Message.created_at.desc())
                                        .limit(15)
                                        .all()
                                    )
                                    conv_history = [
                                        {"direction": m.direction, "content": m.content}
                                        for m in reversed(recent)
                                        if m.content and not m.content.startswith("[IMAGE:") and not m.content.startswith("[VIDEO:")
                                    ]
                                    kb_ctx = search_kb(combined, n_results=4)
                                    reply = generate_rag_reply(
                                        incoming_message=combined,
                                        lead_name=lead_name_inner,
                                        kb_results=kb_ctx,
                                        conversation_history=conv_history,
                                    )
                                    if reply and not reply.startswith("["):
                                        send_whatsapp_message(phone_num, reply)
                                        wdb.add(Message(lead_id=lead_id_inner, direction="out", channel="whatsapp",
                                                       content=reply, status="sent", is_read=True))
                                    for m in new_msgs:
                                        m.is_auto_replied = True
                                    wdb.commit()
                                    try:
                                        print(f"[MediaRequest] Post-media AI reply to {lead_name_inner}: {reply[:60].encode('ascii','replace').decode()}...")
                                    except Exception:
                                        pass

                        except Exception as me:
                            try:
                                print(f"Media sending error: {str(me).encode('ascii','replace').decode()}")
                            except Exception:
                                pass
                        finally:
                            wdb.close()

                    thread = threading.Thread(
                        target=_run_media_sequence,
                        args=(lead.phone, lead.id, lead.name)
                    )
                    thread.daemon = True
                    thread.start()
                    # Do NOT continue here. Let the AI generate a reply for the text part of the message.

                # ── Generate AI reply addressing ALL pending messages ──
                # If multiple messages, tell AI about all of them
                if len(msgs) == 1:
                    ai_input = msgs[0].content
                else:
                    ai_input = "Customer sent multiple messages:\n" + "\n".join(
                        f"- {m.content}" for m in msgs if m.content
                    ) + "\n\nRespond to ALL of the above messages in one reply. Address every point — whether it is a question, request, or statement."

                # 1. Search KB for relevant context (actual RAG)
                kb_context = search_kb(ai_input, n_results=4)
                
                # 2. Generate reply
                reply_text = generate_rag_reply(
                    incoming_message=ai_input,
                    lead_name=lead.name,
                    lead_context=lead_context,
                    kb_results=kb_context,
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

                    # Update lead
                    lead.last_message_at = datetime.datetime.now(datetime.timezone.utc)
                    if lead.status == "new":
                        lead.status = "contacted"

                    print(f"Auto-replied to {lead.name} ({len(msgs)} msgs): {reply_text[:60].encode('ascii','replace').decode()}...")

                # Mark ALL incoming messages as auto-replied and release locks
                for m in msgs:
                    m.is_auto_replied = True
                    m.processing_lock_at = None
                db.commit()

            except Exception as msg_err:
                # Per-lead error handling — release locks so messages can be retried
                print(f"Error processing lead {lead_id} messages: {str(msg_err).encode('ascii','replace').decode()}")
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
        "🚗 Please park your Vehicles *outside* the society main gate to avoid fines and Jammers.\n\n"
        "Come to Tower 1 , Oak , A wing, Flat No 1802.. on the 18th floor.\n"
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


def _generate_media_caption(filename: str, media_type: str = "photo") -> str:
    """Generate a short, friendly caption for a media file based on its filename."""
    from ai import generate
    # Extract a human-readable name from the filename
    name = filename.rsplit(".", 1)[0]  # Remove extension
    # Remove leading numbers and underscores (e.g. "05_swimming_pool" -> "swimming pool")
    import re
    name = re.sub(r'^\d+[_\-\s]*', '', name).replace('_', ' ').replace('-', ' ').strip()
    if not name:
        name = media_type

    prompt = f"""Write a SINGLE short WhatsApp caption (max 10 words) for a {media_type} of "{name}" at a premium residential township called Vanaha in Bavdhan, Pune. 
Use 1-2 relevant emojis. Be enthusiastic but brief. No hashtags. Just the caption, nothing else.
Caption:"""
    try:
        caption = generate(prompt, max_tokens=30, temperature=0.6).strip()
        # Clean up - remove quotes if LLM wraps it
        caption = caption.strip('"\'')
        if caption and not caption.startswith("["):
            return caption
    except Exception as e:
        print(f"Caption generation error for {filename}: {e}")
    # Fallback: readable name with emoji
    return f"📸 {name.title()}" if media_type == "photo" else f"🎬 {name.title()}"


def _send_media_on_request(lead, db):
    """Send ALL photos and videos when user explicitly asks — runs in background thread with LLM captions."""
    import threading

    def _run_media_request(phone_num, lead_id_inner):
        import time as _time
        from welcome_sequence import get_amenity_photos, get_flat_videos
        from whatsapp import upload_whatsapp_media as _upload, send_whatsapp_message
        wdb = SessionLocal()
        try:
            # Intro message for photos
            photo_intro = "Here are the photos of amenities at Vanaha Township 📸👇"
            send_whatsapp_message(phone_num, photo_intro)
            wdb.add(Message(lead_id=lead_id_inner, direction="out", channel="whatsapp",
                           content=photo_intro, status="sent", is_read=True))
            wdb.commit()
            _time.sleep(1)

            # Send ALL amenity photos with LLM captions
            photos = get_amenity_photos()
            for photo_path in photos:
                try:
                    fname = os.path.basename(photo_path)
                    caption = _generate_media_caption(fname, "photo")
                    with open(photo_path, "rb") as f:
                        file_bytes = f.read()
                    ext = fname.rsplit(".", 1)[-1].lower()
                    mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext}"
                    media_id = _upload(file_bytes, mime, fname)
                    if media_id:
                        send_whatsapp_message(phone_num, message=caption, media_id=media_id, media_type="image")
                    wdb.add(Message(lead_id=lead_id_inner, direction="out", channel="whatsapp",
                                   content=f"[IMAGE:{fname}] {caption}", status="sent", is_read=True))
                    wdb.commit()
                    _time.sleep(2)
                except Exception as pe:
                    print(f"Photo send error: {pe}")

            _time.sleep(5)

            # Intro message for videos
            video_intro = "Here are the flat walkthrough videos 🎬👇"
            send_whatsapp_message(phone_num, video_intro)
            wdb.add(Message(lead_id=lead_id_inner, direction="out", channel="whatsapp",
                           content=video_intro, status="sent", is_read=True))
            wdb.commit()
            _time.sleep(1)

            # Send ALL flat videos with LLM captions
            videos = get_flat_videos()
            for video_path in videos:
                try:
                    fname = os.path.basename(video_path)
                    caption = _generate_media_caption(fname, "video")
                    with open(video_path, "rb") as f:
                        file_bytes = f.read()
                    media_id = _upload(file_bytes, "video/mp4", fname)
                    if media_id:
                        send_whatsapp_message(phone_num, message=caption, media_id=media_id, media_type="video")
                    wdb.add(Message(lead_id=lead_id_inner, direction="out", channel="whatsapp",
                                   content=f"[VIDEO:{fname}] {caption}", status="sent", is_read=True))
                    wdb.commit()
                    _time.sleep(5)
                except Exception as ve:
                    print(f"Video send error: {ve}")
            print(f"[MediaRequest] Sent to {phone_num}: {len(photos)} photos, {len(videos)} videos with captions")
        except Exception as me:
            print(f"Media sending error: {me}")
        finally:
            wdb.close()

    thread = threading.Thread(target=_run_media_request, args=(lead.phone, lead.id))
    thread.daemon = True
    thread.start()


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
    Two-phase email processing for 100% lead capture.
    
    PHASE 1 — FETCH & STORE: Get UNSEEN emails from Gmail, store raw data
    in raw_emails table. Deduplicates by Message-ID. Only marks as SEEN
    in Gmail AFTER safe storage. Crash-safe: if server dies mid-fetch,
    unstored emails stay UNSEEN and are re-fetched next cycle.
    
    PHASE 2 — PARSE & CREATE: Process all 'pending' raw_emails through
    the parser. Leads with phone → created. Leads without phone →
    quarantined (not silently skipped). Parse errors → quarantined with
    error details for debugging.
    """
    import json
    gmail_user = os.getenv("GMAIL_USER", "")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "")
    if not gmail_user or not gmail_pass:
        return

    db = SessionLocal()
    try:
        # ── PHASE 1: FETCH & STORE RAW EMAILS ──
        fetched = 0
        deduped = 0
        lead_generator = fetch_gmail_leads(gmail_user, gmail_pass, max_emails=None)

        for parsed in lead_generator:
            raw_data = parsed.get("_raw", {})
            imap_info = parsed.get("_imap")
            gmail_message_id = raw_data.get("gmail_message_id", "")

            if not gmail_message_id:
                continue

            # Dedup: skip if this Message-ID is already in raw_emails
            existing = db.query(RawEmail).filter(
                RawEmail.gmail_message_id == gmail_message_id
            ).first()
            if existing:
                deduped += 1
                # Still mark as SEEN so it doesn't appear again
                if imap_info:
                    mark_email_seen(imap_info)
                continue

            # Store raw email — this is the crash-safe point
            raw_email = RawEmail(
                gmail_message_id=gmail_message_id,
                subject=raw_data.get("subject", ""),
                sender=raw_data.get("sender", ""),
                body=raw_data.get("body", ""),
                html_body=raw_data.get("html_body", ""),
                status="pending",
                received_at=raw_data.get("received_at"),
                parse_result_json=json.dumps({
                    k: v for k, v in parsed.items()
                    if k not in ("_raw", "_imap") and not callable(v)
                }, default=str),
            )
            db.add(raw_email)
            db.commit()
            fetched += 1

            # Only mark as SEEN after safe storage
            if imap_info:
                mark_email_seen(imap_info)

        if fetched > 0 or deduped > 0:
            print(f"[Email Fetch] {fetched} new emails stored, {deduped} duplicates skipped")

        # ── PHASE 2: PARSE PENDING RAW EMAILS → CREATE LEADS ──
        _process_pending_raw_emails(db)

    except Exception as e:
        print(f"Email polling error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


def _process_pending_raw_emails(db):
    """
    Process all raw_emails with status='pending'.
    Creates leads or quarantines entries that can't be parsed.
    Can be called independently to re-process after parser fixes.
    """
    import json

    pending = db.query(RawEmail).filter(RawEmail.status == "pending").all()
    if not pending:
        return

    created = 0
    quarantined = 0

    for raw_email in pending:
        try:
            # Parse the stored result (was parsed during fetch)
            parsed = json.loads(raw_email.parse_result_json) if raw_email.parse_result_json else {}

            name = parsed.get("name", "").strip() or "Unknown"
            phone = parsed.get("phone", "").strip()
            lead_email = parsed.get("email", "").strip()

            # Detect tag from parsed data (DEALER, BROKER, OWNER)
            parsed_tag = parsed.get("tag", "").strip().upper()

            # Dedup by phone: check if lead with same phone already exists
            if phone:
                existing_lead = db.query(Lead).filter(Lead.phone == phone).first()
                if existing_lead:
                    # Bump to top: set updated_at to NOW so it sorts first on dashboard
                    existing_lead.updated_at = datetime.datetime.now(datetime.timezone.utc)
                    # Update created_at to latest email time so "Arrived" reflects latest inquiry
                    if raw_email.received_at:
                        existing_lead.created_at = raw_email.received_at
                    # Mark as DUPLICATE so user can see it's a repeat inquiry
                    existing_lead.tag = "DUPLICATE"
                    # Count email touches in notes
                    touch_count = db.query(RawEmail).filter(
                        RawEmail.lead_id == existing_lead.id
                    ).count() + 1  # +1 for this one
                    if touch_count > 1:
                        existing_lead.notes = (existing_lead.notes or "").rstrip()
                        if "\n📧 Email touches:" not in (existing_lead.notes or ""):
                            existing_lead.notes = (existing_lead.notes or "") + f"\n📧 Email touches: {touch_count}"
                        else:
                            existing_lead.notes = re.sub(
                                r"📧 Email touches: \d+",
                                f"📧 Email touches: {touch_count}",
                                existing_lead.notes
                            )
                    raw_email.status = "parsed"
                    raw_email.lead_id = existing_lead.id
                    raw_email.parsed_at = datetime.datetime.now(datetime.timezone.utc)
                    raw_email.quarantine_reason = f"Duplicate phone - linked to lead #{existing_lead.id}"
                    db.commit()
                    continue

            # QUARANTINE if no phone (most important contact info)
            if not phone:
                raw_email.status = "quarantined"
                raw_email.quarantine_reason = "no_phone"
                raw_email.parsed_at = datetime.datetime.now(datetime.timezone.utc)
                db.commit()
                quarantined += 1
                continue

            # Create the lead
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
                tag=parsed_tag if parsed_tag else "NEW",
                notes=parsed.get("notes", "")[:500],
            )
            # Use email received time instead of current time
            if raw_email.received_at:
                lead.created_at = raw_email.received_at
            db.add(lead)
            db.flush()  # Get the lead ID

            # Automatically trigger welcome template for new parsed leads
            # ONLY when Live Mode toggle is ON on the dashboard
            from wa_guard import can_send_to, is_live_mode
            if is_live_mode() and not lead.welcome_sent and can_send_to(lead.phone):
                import threading
                from welcome_sequence import send_welcome_sequence
                import os
                
                def _run_welcome_auto(phone_num, lid, lname):
                    try:
                        from db import SessionLocal
                        from models import Lead, Message
                        res = send_welcome_sequence(phone_num, lead_name=lname)
                        wdb = SessionLocal()
                        try:
                            wlead = wdb.query(Lead).filter(Lead.id == lid).first()
                            if wlead:
                                wlead.welcome_sent = True
                                template_name = os.getenv("WA_TEMPLATE_NAME", "hello_world")
                                wdb.add(Message(lead_id=lid, direction="out", channel="whatsapp",
                                                content=f"[Template Sent: {template_name}]", status="sent", is_read=True))
                            wdb.commit()
                            try:
                                print(f"[Welcome] Email lead template sent to {lname} ({phone_num})")
                            except Exception:
                                pass
                        finally:
                            wdb.close()
                    except Exception as e:
                        try:
                            print(f"Auto-welcome error: {str(e).encode('ascii','replace').decode()}")
                        except Exception:
                            pass

                thread = threading.Thread(target=_run_welcome_auto, args=(lead.phone, lead.id, lead.name))
                thread.daemon = True
                thread.start()

            raw_email.status = "parsed"
            raw_email.lead_id = lead.id
            raw_email.parsed_at = datetime.datetime.now(datetime.timezone.utc)
            db.commit()
            created += 1

        except Exception as e:
            # Parse error — quarantine with error details
            raw_email.status = "error"
            raw_email.quarantine_reason = f"parse_error: {str(e)[:250]}"
            raw_email.parsed_at = datetime.datetime.now(datetime.timezone.utc)
            db.commit()
            quarantined += 1
            print(f"[Email Parse Error] {raw_email.gmail_message_id}: {e}")

    if created > 0 or quarantined > 0:
        print(f"[Email Parse] {created} leads created, {quarantined} quarantined")

