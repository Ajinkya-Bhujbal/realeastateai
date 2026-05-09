# LeadPilot — AI Real Estate Lead Management System

> **Automated, local-first CRM** for Indian real estate agents. Ingests leads from Housing.com, 99acres, MagicBricks via Gmail, manages WhatsApp conversations with AI-powered replies, and sends property media automatically.

![Stack](https://img.shields.io/badge/Backend-FastAPI-009688?style=flat-square) ![AI](https://img.shields.io/badge/AI-Ollama%20(gemma2%3A9b)-blueviolet?style=flat-square) ![DB](https://img.shields.io/badge/DB-SQLite-003B57?style=flat-square) ![Vector](https://img.shields.io/badge/VectorDB-ChromaDB-orange?style=flat-square)

---

## Quick Start

```bash
# 1. Clone & install
git clone <repo-url> && cd real-estate-leads
install.bat            # creates venv, installs deps, pulls Ollama model

# 2. Configure
copy .env.example .env  # fill in Gmail + WhatsApp API credentials

# 3. Run
start.bat               # starts Ollama + FastAPI server, opens browser
```

Dashboard: **http://localhost:8000** | API Docs: **http://localhost:8000/docs**

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        BROWSER (localhost:8000)                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │Dashboard │  │  Leads   │  │ Messages │  │   AI Tools     │  │
│  │  Stats   │  │  Table   │  │(WA Web)  │  │  KB / RAG      │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────────┘  │
│                    frontend/app.js  +  style.css                 │
└──────────────────────────────┬──────────────────────────────────┘
                               │ fetch() API calls
┌──────────────────────────────▼──────────────────────────────────┐
│                     FastAPI  (backend/main.py)                   │
│                                                                  │
│  Static Files ──► /static/*  (frontend/)                         │
│  Media Files  ──► /media/*   (data/media/)                       │
│  REST API     ──► /api/*                                         │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              APScheduler (backend/followup.py)            │   │
│  │  ┌──────────────┐ ┌───────────────┐ ┌────────────────┐  │   │
│  │  │ Gmail Poller │ │ Auto-Reply    │ │ Follow-up      │  │   │
│  │  │  (30 sec)    │ │ Processor     │ │ Scheduler      │  │   │
│  │  │              │ │  (10 sec)     │ │  (5 min)       │  │   │
│  │  └──────┬───────┘ └──────┬────────┘ └───────┬────────┘  │   │
│  └─────────┼────────────────┼──────────────────┼────────────┘   │
│            │                │                  │                 │
│  ┌─────────▼────┐  ┌───────▼────────┐  ┌──────▼──────────┐    │
│  │ parser.py    │  │ ai.py          │  │ whatsapp.py     │    │
│  │ Gmail IMAP   │  │ Ollama LLM     │  │ WA Cloud API    │    │
│  │ HTML parsing │  │ RAG replies    │  │ Send/receive    │    │
│  └──────────────┘  └───────┬────────┘  └─────────────────┘    │
│                            │                                    │
│  ┌─────────────────────────▼──────────────────────────────┐    │
│  │                    rag.py + ChromaDB                     │    │
│  │  data/knowledge_base/*.txt  →  chunked & embedded       │    │
│  │  data/properties.json       →  property search          │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              SQLite (leads.db) via SQLAlchemy             │    │
│  │   Lead  │  Message  │  Property  │  FollowUpSchedule     │    │
│  └─────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘

External Services:
  • Gmail IMAP  ←  Lead emails from Housing / 99acres / MagicBricks
  • Ollama      ←  Local AI (gemma2:9b, phi3:mini)
  • WhatsApp Business Cloud API  ←  Send/receive messages
```

---

## Project Structure

```
real-estate-leads/
├── backend/
│   ├── main.py              # FastAPI app, ALL API routes, lifespan events
│   ├── models.py            # SQLAlchemy models: Lead, Message, Property, FollowUp
│   ├── db.py                # Database engine & session factory
│   ├── parser.py            # Gmail IMAP poller, HTML lead extraction
│   ├── followup.py          # APScheduler jobs: auto-reply, follow-ups, email polling
│   ├── welcome_sequence.py  # Welcome message + media sending flow
│   ├── whatsapp.py          # WhatsApp Cloud API: send messages, upload media
│   ├── ai.py                # Ollama integration: generate replies, summaries
│   └── rag.py               # ChromaDB: knowledge base indexing & search
├── frontend/
│   ├── index.html           # Single-page app HTML
│   ├── app.js               # All frontend logic (fetch API, DOM manipulation)
│   └── style.css            # Complete design system (dark theme)
├── data/
│   ├── media/
│   │   ├── amenities/       # 24 amenity photos (JPEG)
│   │   ├── flats/           # 5 flat tour videos (MP4, ~18-22MB each)
│   │   └── locations/       # Location/direction map images
│   ├── knowledge_base/      # Text files for RAG (e.g., vanaha_knowledge_base.txt)
│   ├── properties.json      # Sample property data for RAG indexing
│   └── chroma_db/           # ChromaDB persistent storage (auto-generated)
├── .env                     # Environment config (gitignored)
├── .env.example             # Template for .env
├── requirements.txt         # Python dependencies
├── start.bat                # Launch script (Ollama + FastAPI)
├── install.bat              # First-time setup script
└── leads.db                 # SQLite database (auto-created)
```

---

## Feature Reference

### 1. Lead Ingestion (Gmail Poller)
| Detail | Value |
|--------|-------|
| **File** | `backend/parser.py`, called from `backend/followup.py` |
| **Interval** | Every 30 seconds |
| **Portals** | Housing.com, 99acres, MagicBricks |
| **Extraction** | Name, Phone, Email, Config (1BHK/2BHK), Price, Location |
| **Dedup** | Skips duplicate phone+email combos; breaks after 20 consecutive dupes |
| **Obfuscation** | Housing.com hides phones behind `awstrack.me → hsng.co → api.whatsapp.com/send?phone=...` redirect chains; parser follows them |

### 2. WhatsApp Web-Style Chat UI
| Detail | Value |
|--------|-------|
| **File** | `frontend/app.js` (lines 353–505) |
| **Polling** | Every **45 seconds** (configurable in `startChatPolling()`) |
| **Smart refresh** | Tracks `_lastSeenMsgId`; only re-renders if new messages exist |
| **Simulate** | "Simulate" button sends test incoming messages; chat refreshes instantly via `await selectChat(r.lead_id)` |
| **Media Gallery** | Groups consecutive `[IMAGE:*]` / `[VIDEO:*]` messages into a grid |
| **Lightbox** | Click any image/video → full-screen viewer with prev/next/close (keyboard arrows + Escape) |
| **Event Delegation** | All media click handlers use `$('wa-messages').addEventListener('click', ...)` for reliability |

### 3. Welcome Sequence (Auto-send on first message)
| Detail | Value |
|--------|-------|
| **File** | `backend/welcome_sequence.py` |
| **Trigger** | First incoming message from a lead (checked in `followup.py::process_unread_messages`) |
| **Flow** | Text greeting → Amenity overview → Pricing → Photo intro → **ALL 24 photos** (1s gap) → Wait 30s → Video intro → **ALL 5 videos** (5s gap) → Wait 60s → Final contact message |
| **Re-trigger** | Can be manually queued for re-sending via the "Re-send Welcome" button in the chat header UI |
| **DB Tokens** | Photos stored as `[IMAGE:filename]`, Videos as `[VIDEO:filename]` |
| **Media Folders** | `data/media/amenities/` (photos), `data/media/flats/` (videos) |

### 4. AI Auto-Reply (RAG-powered)
| Detail | Value |
|--------|-------|
| **Files** | `backend/ai.py`, `backend/rag.py`, `backend/followup.py` |
| **Interval** | Checks every 10 seconds for unread incoming messages |
| **Model** | `gemma2:9b` via Ollama (configurable in `.env` as `OLLAMA_MODEL`) |
| **RAG** | Searches `data/knowledge_base/*.txt` files via ChromaDB embeddings |
| **Embeddings** | `sentence-transformers` (auto-downloaded HuggingFace model) |
| **Intent Detection** | Keywords trigger special flows: location → directions sequence, media → send all photos+videos |

### 5. Intent-Based Media Sending
| Detail | Value |
|--------|-------|
| **File** | `backend/followup.py::_send_media_on_request()` |
| **Trigger keywords** | `photo`, `video`, `pic`, `picture`, `1bhk`, `2bhk`, `furnished`, `sample flat`, `layout`, `amenity`, etc. |
| **Behavior** | Sends disclaimer ("These are videos of sample flat layout...") → ALL amenity photos → ALL flat videos |
| **AI Captions**| Uses Ollama to generate short, enthusiastic, emoji-rich captions for each media file based on its filename |
| **Important** | System sends ALL media regardless of specific flat type asked — because layout is the same for all |

### 6. Location Sequence
| Detail | Value |
|--------|-------|
| **File** | `backend/followup.py::_send_location_sequence()` |
| **Trigger keywords** | `location`, `address`, `where`, `kaha`, `direction`, `how to reach` |
| **Content** | Address text → Step-by-step Google Maps directions → Location map images from `data/media/locations/` |

---

## Database Schema

```
Lead (leads)
├── id, name, phone, email, source, status
├── budget_min, budget_max, preferred_location, property_type
├── configuration, price, tag, notes
├── last_message_at, unread_count, auto_reply_enabled, welcome_sent
├── created_at, updated_at
├──→ messages[]    (1:many)
└──→ followups[]   (1:many)

Message (messages)
├── id, lead_id (FK), direction (in/out), channel, content
├── status, is_read, is_auto_replied, wa_message_id
└── created_at

Property (properties)
├── id, title, location, price, property_type
├── bedrooms, area_sqft, description, amenities, builder
├── status, created_at

FollowUpSchedule (followup_schedules)
├── id, lead_id (FK), frequency_hours, next_followup_at
├── message_template, is_active, max_followups, followups_sent
└── created_at
```

**Media tokens in Message.content:**
- `[IMAGE:filename.jpg]` → rendered as clickable thumbnail
- `[VIDEO:filename.mp4]` → rendered as video preview with play icon

---

## API Endpoints Summary

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serve frontend HTML |
| `GET` | `/api/dashboard/stats` | Dashboard statistics |
| `GET/POST` | `/api/leads` | List / create leads |
| `GET/PUT/DELETE` | `/api/leads/{id}` | Get / update / delete lead |
| `POST` | `/api/leads/{id}/force-welcome` | Trigger welcome sequence manually |
| `GET` | `/api/chats` | List all conversations (sidebar) |
| `GET` | `/api/chats/{lead_id}` | Get full chat history |
| `POST` | `/api/chats/{lead_id}/send` | Send text message |
| `POST` | `/api/chats/{lead_id}/send-media` | Send media (file upload) |
| `POST` | `/api/chats/{lead_id}/read` | Mark messages as read |
| `POST` | `/api/chats/{lead_id}/toggle-auto-reply` | Toggle AI auto-reply |
| `POST` | `/api/chats/{lead_id}/reset-welcome` | Reset `media_sent` flag to re-send welcome sequence |
| `POST` | `/api/chats/simulate-incoming` | Simulate incoming message (testing) |
| `POST` | `/api/parse-email/save` | Parse + save a single email |
| `GET/POST` | `/api/properties` | List / create properties |
| `POST` | `/api/properties/search` | Semantic property search |
| `POST` | `/api/properties/index-samples` | Index sample properties |
| `GET` | `/api/kb/status` | Knowledge base status |
| `POST` | `/api/kb/index` | Re-index knowledge base |
| `POST` | `/api/kb/search` | Search knowledge base |
| `POST` | `/api/ai/reply` | Generate AI reply for a lead |
| `GET` | `/api/ai/status` | Ollama connection status |
| `POST` | `/api/followups` | Create follow-up schedule |
| `GET/POST` | `/api/webhooks/whatsapp` | WhatsApp webhook (verify + receive) |

---

## Configuration (.env)

```env
# AI Model
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=gemma2:9b          # or phi3:mini

# Gmail (for auto lead ingestion)
GMAIL_USER=your-email@gmail.com
GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx   # Google App Password, NOT regular password

# WhatsApp Business API
WA_API_URL=https://graph.facebook.com/v18.0
WA_PHONE_NUMBER_ID=your-phone-id
WA_ACCESS_TOKEN=your-access-token
WA_VERIFY_TOKEN=leadbot_verify_2024

# Server
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
```

---

## Known Bugs & Issues

### Active Bugs

| # | Bug | Root Cause | Status | Files |
|---|-----|-----------|--------|-------|
| 1 | **Browser caching old JS/CSS** | FastAPI serves static files with no cache-control headers | **Fixed** — Added `NoCacheStaticMiddleware` in `main.py` + cache-busting `?v=` params in `index.html` | `main.py:178-193`, `index.html:8,229` |
| 2 | **Simulated messages don't appear in chat** | `selectChat()` wasn't called after simulation; browser cached old code | **Fixed** — `sim-send` handler now calls `await selectChat(r.lead_id)` directly + 8s delayed re-check for AI reply | `app.js:618-638` |
| 3 | **Chat window flashing every 3s** | Old 3-second `setInterval` was cached by browser | **Fixed** — Poll is 45,000ms; no-cache middleware prevents stale JS | `app.js:641-658` |
| 4 | **Lightbox not opening on image click** | Inline `onclick` with `JSON.stringify` broke HTML attribute quoting | **Fixed** — Uses event delegation on `$('wa-messages')` with `data-media-group` attribute | `app.js:511-560` |
| 5 | **Sidebar name concatenation** | Duplicate name in display (e.g., "TestLeadTestLead") | **Open** — Cosmetic, in `loadChats()` sidebar rendering | `app.js:375-387` |
| 6 | **WhatsApp sandbox limits** | Meta sandbox restricts to pre-registered numbers only | **Open** — Requires production API onboarding | External |

### Important Notes for Debugging
- **Always hard-refresh** (Ctrl+Shift+R) the browser after changing `app.js` or `style.css`
- The `NoCacheStaticMiddleware` should prevent caching, but if issues persist, bump the `?v=` parameter in `index.html`
- Check the **terminal/console** for Python errors — most silent failures log to stdout
- WhatsApp API returns `{ "mock": true }` when credentials aren't set — this is expected in dev mode

---

## Development Guide

### Adding a New Feature

1. **Database changes** → `backend/models.py` → delete `leads.db` to recreate tables (no migrations)
2. **API route** → `backend/main.py` → add Pydantic schema + FastAPI route
3. **Background task** → `backend/followup.py` → add to APScheduler or to `process_unread_messages()`
4. **Frontend** → `frontend/index.html` (HTML) + `frontend/app.js` (JS) + `frontend/style.css` (CSS)
5. **Bump cache** → Update `?v=` in `index.html` script/link tags after any JS/CSS change

### Key Design Decisions
- **No framework** — Frontend is vanilla JS/HTML/CSS for zero-build simplicity
- **No WebSockets** — Uses `setInterval` polling to avoid complexity; 45s for chat, 15s for dashboard
- **No migrations** — Delete `leads.db` to reset schema (acceptable for early-stage product)
- **Thread-based media** — Welcome sequences run in daemon threads to keep API responsive
- **Event delegation** — All dynamic content click handlers use delegation on parent containers

### File-by-File Quick Reference

| File | Purpose | Key Functions |
|------|---------|---------------|
| `main.py` | All API routes, app startup, static file serving | `lifespan()`, `simulate_incoming_message()`, `send_chat_message()` |
| `followup.py` | Background automation engine | `process_unread_messages()`, `_send_media_on_request()`, `_send_location_sequence()` |
| `welcome_sequence.py` | Welcome flow with media | `send_welcome_sequence()`, `get_welcome_db_messages()`, `get_amenity_photos()`, `get_flat_videos()` |
| `parser.py` | Gmail IMAP + HTML lead extraction | `fetch_gmail_leads()`, `parse_lead_from_email()` |
| `ai.py` | Ollama LLM interface | `generate_rag_reply()`, `generate_auto_reply()`, `check_ollama()` |
| `rag.py` | ChromaDB vector operations | `search_kb()`, `index_kb_folder()`, `search_properties()` |
| `whatsapp.py` | WhatsApp Business Cloud API | `send_whatsapp_message()`, `upload_whatsapp_media()`, `parse_webhook_message()` |
| `app.js` | Entire frontend application | `selectChat()`, `loadChats()`, `openMediaViewer()`, `renderMsgContent()` |
| `style.css` | Complete design system | CSS variables in `:root`, WhatsApp-themed classes, lightbox styles |

---

## Message Flow Diagrams

### Incoming Message → Auto-Reply Flow
```
Lead sends WhatsApp message
        │
        ▼
WhatsApp Webhook (main.py)  ──OR──  Simulate Button (app.js)
        │                                    │
        ▼                                    ▼
   Save to DB as Message(direction="in")
        │
        ▼
   process_unread_messages() [every 10 sec]
        │
        ├── First message? ──YES──► send_welcome_sequence() [in thread]
        │                           └── Texts → Photos → Wait → Videos → Final msg
        │
        ├── Location keywords? ──YES──► _send_location_sequence()
        │                               └── Address → Google Maps links → Map images
        │
        ├── Media keywords? ──YES──► generate_rag_reply() + _send_media_on_request()
        │                            └── Disclaimer → ALL photos → ALL videos
        │
        └── General query ──► generate_rag_reply()
                              └── Search ChromaDB → Build prompt → Ollama → Send reply
```

### Frontend Chat Rendering
```
selectChat(leadId)
    │
    ├── GET /api/chats/{leadId}  → messages[]
    │
    ├── For each message:
    │   ├── [IMAGE:*] or [VIDEO:*] → Group consecutive → Render gallery grid
    │   │                             └── data-media-group="encoded JSON"
    │   │                             └── data-idx="N" on each item
    │   └── Text → renderMsgContent() → escape, linkify, bold, newlines
    │
    ├── box.innerHTML = html
    │
    └── _lastSeenMsgId = last message ID
    
Click on gallery item:
    │
    └── Event delegation on $('wa-messages')
        ├── .wa-gallery-item → decode data-media-group → openMediaViewer()
        ├── .wa-media-img    → extract filename → openMediaViewer()
        └── .wa-media-vid    → extract filename → openMediaViewer()
```

---

## Media File Conventions

| Folder | Contents | Naming | Used By |
|--------|----------|--------|---------|
| `data/media/amenities/` | Amenity photos | `01_amenity_space.jpeg`, `05_swimming_pool.jpeg`, `17_Gym.jpeg` | `get_amenity_photos()` |
| `data/media/flats/` | Flat tour videos | `01_1bhk.mp4`, `02_2bhk.mp4`, ... `05_4bhk.mp4` | `get_flat_videos()` |
| `data/media/locations/` | Direction maps | Any `.jpg/.jpeg/.png/.webp` | `_send_location_sequence()` |

**Frontend media routing** (in `app.js`):
- Images: filename containing `amenity`, `pool`, `gym`, `lounge`, `ground`, `kids`, `indoor`, `yoga`, `reading`, `work`, `multipurpose` → `/media/amenities/`
- All other images and ALL videos → `/media/flats/`

**Supported formats**: `jpg`, `jpeg`, `png`, `webp` (images) | `mp4`, `3gp`, `avi`, `mov`, `mkv`, `webm` (videos)

---

## Scheduler Intervals

| Job | Interval | Function | File |
|-----|----------|----------|------|
| Gmail lead poller | 30 sec | `fetch_gmail_leads()` | `followup.py` |
| Auto-reply processor | 10 sec | `process_unread_messages()` | `followup.py` |
| Follow-up sender | 5 min | `process_followups()` | `followup.py` |
| Frontend chat poll | 45 sec | `startChatPolling()` | `app.js` |
| Frontend dashboard poll | 15 sec | `setInterval` in `app.js` | `app.js` |
| Frontend time-ago updater | 5 sec | `setInterval` in `app.js` | `app.js` |
