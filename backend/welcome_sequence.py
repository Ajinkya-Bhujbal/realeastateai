"""
Welcome Sequence — sends introductory messages, photos, and videos
when a new lead first replies to the WhatsApp template message.

Flow:
  1) Text messages (greeting → amenities → rent/buy prices)
  2) "Please find below the photos..." text
  3) Send ALL amenity photos (with 1s delay each)
  4) Wait 30 seconds
  5) "Please find below the Videos..." text
  6) Send ALL flat videos (with 2s delay each)
  7) Final contact message

Media folders:
  data/media/amenities/  → Put amenity photos here (jpg, png, jpeg)
  data/media/flats/      → Put flat videos here (mp4, 3gp) and photos (jpg, png)
"""
import os
import time
import glob
from whatsapp import send_whatsapp_message, upload_whatsapp_media

# Base path for media
MEDIA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "media")


# ── Text messages in sequence ───────────────────────────────────────

# Messages sent BEFORE photos
PRE_PHOTO_MESSAGES = [
    # Message 1: Greeting
    (
        "Hello, muje aapki request aayi thi. 🙏\n"
        "Do you need a Flat?\n\n"
        "Please wait and don't reply for 5 min, "
        "till I send you the photos and videos of available flats. "
        "As videos take time to upload. 🙏"
    ),
    # Message 2: Overview + Amenities + Facilities
    (
        "A society that is just like a *Five Star Hotel/Resort* "
        "with world class amenities like swimming pool, gym, cricket ground, "
        "badminton court, Basketball Court, Kids Play Area, Pool, Snooker, "
        "Squash, carrom board, Table Tennis, foosball, Golf, "
        "work lounge, reading lounge. 🎱🎾🏏🏀\n\n"
        "@@  *Super-Market, Mini-Market, Vegetable Market, Hotel, "
        "Laundry Shop, Medical Shop, Mess, Maid*  inside the society itself "
        "on walking distance...* @@ 🛒\n\n"
        "24 Hrs water.\n"
        "24 Hrs electricity and power backup and generator.\n"
        "24 Hr security.\n"
        "There will *NO Maintainance* or charges.\n"
        "# *Free Shuttle/Bus service* # to BAVDHAN City in 10 Minutes 🚐\n"
        "😊"
    ),
    # Message 3: Rent + Buy Prices
    (
        "*Rent Structure...* 💷\n"
        "1 bhk rent 16k to 18k\n"
        "2 bhk rent 21k - 22k\n"
        "3 bhk compact rent 23k - 25k\n"
        "3 bhk grande rent 26k to 28k\n\n"
        "*Deposit will be 2 months rent for unfurnished.*\n\n"
        "*Buying Prices* 💵\n"
        "1 bhk 51 Lacks (negotiable)\n"
        "2 bhk 81 Lacks (negotiable)\n"
        "3 bhk compact 90 Lacks (negotiable)\n"
        "3 bhk grande 1 Cr (negotiable)\n\n"
        "Alternate Number: 7387457889"
    ),
]

# Message sent right before amenity photos
PHOTO_INTRO_MESSAGE = (
    "Please find below the photos of *Free to use, Lavish Amenities* "
    "in the society.\n"
    "(Note: All photos are real. 😊)\n"
    "👇👇👇👇👇👇👇👇"
)

# Message sent right before flat videos (after 30s wait)
VIDEO_INTRO_MESSAGE = (
    "Please find below the *Videos* of available flats for *Sell and Rent* both.\n"
    "( 1 / 2 / 2.5 / 3 / 4 BHK available )\n"
    "👇👇👇👇👇👇👇👇"
)

# Final message after all media
FINAL_MESSAGE = (
    "Please visit at least once — It is a Lavish and High-class Society!!! ☺️\n\n"
    "📞 Contact: 7387457889 or 9359932740"
)

# Combined list for DB storage (all text messages in order)
ALL_TEXT_MESSAGES = PRE_PHOTO_MESSAGES + [PHOTO_INTRO_MESSAGE, VIDEO_INTRO_MESSAGE, FINAL_MESSAGE]


def get_welcome_db_messages() -> list:
    """
    Returns all welcome messages in the CORRECT order for DB storage.
    This ensures the dashboard chat shows messages in the same order
    as they appear on WhatsApp: texts → photo intro → photos → video intro → videos → final.
    Each item is a dict: {"content": str}
    """
    msgs = []
    # 1. Pre-photo text messages
    for t in PRE_PHOTO_MESSAGES:
        msgs.append({"content": t})
    # 2. Photo intro
    msgs.append({"content": PHOTO_INTRO_MESSAGE})
    # 3. All amenity photos
    for p in get_amenity_photos():
        msgs.append({"content": f"[IMAGE:{os.path.basename(p)}]"})
    # 4. Video intro
    msgs.append({"content": VIDEO_INTRO_MESSAGE})
    # 5. All flat videos
    for v in get_flat_videos():
        msgs.append({"content": f"[VIDEO:{os.path.basename(v)}]"})
    # 6. Final message
    msgs.append({"content": FINAL_MESSAGE})
    return msgs


def _get_media_files(folder: str, extensions: tuple) -> list:
    """Get sorted list of media files from a folder."""
    media_path = os.path.join(MEDIA_DIR, folder)
    if not os.path.isdir(media_path):
        return []
    files = []
    for ext in extensions:
        files.extend(glob.glob(os.path.join(media_path, f"*.{ext}")))
    files.sort()
    return files


def get_amenity_photos() -> list:
    """Get all amenity photos."""
    return _get_media_files("amenities", ("jpg", "jpeg", "png", "webp"))


def get_flat_videos() -> list:
    """Get all flat videos."""
    return _get_media_files("flats", ("mp4", "3gp", "avi", "mov"))


def get_flat_photos() -> list:
    """Get flat photos (not videos)."""
    return _get_media_files("flats", ("jpg", "jpeg", "png", "webp"))


def _send_photo(phone: str, photo_path: str) -> bool:
    """Upload and send a single photo. Returns True on success."""
    try:
        with open(photo_path, "rb") as f:
            file_bytes = f.read()
        filename = os.path.basename(photo_path)
        ext = filename.rsplit(".", 1)[-1].lower()
        mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext}"
        media_id = upload_whatsapp_media(file_bytes, mime, filename)
        if media_id:
            result = send_whatsapp_message(phone, media_id=media_id, media_type="image")
            return result.get("success") or result.get("mock", False)
    except Exception as e:
        print(f"Photo send error ({os.path.basename(photo_path)}): {e}")
    return False


def _send_video(phone: str, video_path: str) -> bool:
    """Upload and send a single video. Returns True on success."""
    try:
        with open(video_path, "rb") as f:
            file_bytes = f.read()
        filename = os.path.basename(video_path)
        media_id = upload_whatsapp_media(file_bytes, "video/mp4", filename)
        if media_id:
            result = send_whatsapp_message(phone, media_id=media_id, media_type="video")
            return result.get("success") or result.get("mock", False)
    except Exception as e:
        print(f"Video send error ({os.path.basename(video_path)}): {e}")
    return False


def send_welcome_sequence(phone: str) -> dict:
    """
    Send the full welcome sequence to a phone number.
    Follows the exact flow with proper timing:
      1) Text msgs → 2) Photo intro → 3) ALL photos →
      4) Wait 30s → 5) Video intro → 6) ALL videos →
      7) Wait 60s → 8) Final msg
    Returns summary of what was sent.
    """
    results = {"texts": 0, "photos": 0, "videos": 0, "errors": []}

    # ── Step 1: Send pre-photo text messages ──
    for msg_text in PRE_PHOTO_MESSAGES:
        result = send_whatsapp_message(phone, msg_text)
        if result.get("success") or result.get("mock"):
            results["texts"] += 1
        else:
            results["errors"].append(f"Text failed: {result.get('error', 'unknown')}")
        time.sleep(2)  # 2s gap between text messages

    # ── Step 2: Send photo intro message ──
    send_whatsapp_message(phone, PHOTO_INTRO_MESSAGE)
    results["texts"] += 1
    time.sleep(1)

    # ── Step 3: Send ALL amenity photos ──
    photos = get_amenity_photos()
    for photo_path in photos:
        if _send_photo(phone, photo_path):
            results["photos"] += 1
        else:
            results["errors"].append(f"Photo failed: {os.path.basename(photo_path)}")
        time.sleep(1)  # 1s between photos

    print(f"[Welcome] {len(photos)} photos sent to {phone}. Waiting 30s before videos...")

    # ── Step 4: Wait 30 seconds ──
    time.sleep(30)

    # ── Step 5: Send video intro message ──
    videos = get_flat_videos()
    if videos:
        send_whatsapp_message(phone, VIDEO_INTRO_MESSAGE)
        results["texts"] += 1
        time.sleep(1)

        # ── Step 6: Send ALL flat videos ──
        for video_path in videos:
            if _send_video(phone, video_path):
                results["videos"] += 1
            else:
                results["errors"].append(f"Video failed: {os.path.basename(video_path)}")
            time.sleep(2)  # 2s between videos (larger files)

        print(f"[Welcome] {len(videos)} videos sent to {phone}. Waiting 60s before final msg...")

        # ── Step 7: Wait 60 seconds ──
        time.sleep(60)

    # ── Step 8: Send final message ──
    send_whatsapp_message(phone, FINAL_MESSAGE)
    results["texts"] += 1

    print(f"[Welcome] Sequence complete for {phone}: {results}")
    return results
