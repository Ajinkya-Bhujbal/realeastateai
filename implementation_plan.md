# LeadPilot: Implementation Plan & Project Context

## 🌟 Project Overview
LeadPilot is an AI-Powered Real Estate Lead Management System designed specifically for Indian real estate agents. It acts as an automated, local-first CRM that ingests leads from popular real estate portals (Housing.com, 99acres, MagicBricks) directly from a connected Gmail inbox, extracts obfuscated contact details, and presents them in a modern dashboard.

It features a built-in WhatsApp Web-style messaging interface, automated AI replies powered by local LLMs (Ollama), and a RAG (Retrieval-Augmented Generation) pipeline backed by ChromaDB to recommend properties and answer lead queries based on a local knowledge base.

## 🏗️ Technology Stack
- **Backend:** Python, FastAPI, Uvicorn
- **Database:** SQLite with SQLAlchemy ORM
- **Frontend:** Vanilla HTML/CSS/JS (Zero-build pipeline, direct static serving)
- **AI/LLM:** Ollama (Phi-3 Mini by default) running locally
- **Vector Database:** ChromaDB (for RAG document indexing and semantic search)
- **Background Tasks:** APScheduler (polling Gmail, sending follow-ups)
- **External Integrations:**
  - `imaplib` for Gmail ingestion
  - `urllib` for parsing and resolving complex HTTP redirect chains (to extract hidden phone numbers)
  - WhatsApp Business Cloud API (Graph API)

## ⚡ Core Features & Functionality
### 1. Automated Lead Ingestion (Gmail Poller)
- **Mechanism:** Background task polls Gmail via IMAP every 60 seconds.
- **Extraction:** Parses HTML & Text bodies from Housing, MagicBricks, and 99acres.
- **Obfuscation Bypass:** Housing.com hides phone numbers behind tracking URLs (`awstrack.me` -> `hsng.co` -> `api.whatsapp.com/send?phone=...`). The parser intercepts and resolves these HTTP redirects with short timeouts to extract the verified phone number.
- **Schema Mapping:** Extracts Lead Name, Phone, Email, Property Configuration (e.g., "1 BHK", "2 BHK"), Budget/Price (e.g., "₹ 18.0k", "52 Lakhs"), Location, and original Timestamp.
- **Streaming & Deduplication:** Parses from newest to oldest. Uses a generator to save leads sequentially. Features a smart early-exit (breaks after 20 consecutive duplicates) to rapidly ingest new leads without rescanning the entire inbox history.

### 2. WhatsApp Web-Style Dashboard
- **UI Architecture:** Single-page application built with raw HTML/CSS/JS. Dark mode, responsive design.
- **Views:** Dashboard Stats, Leads Table, Properties/Knowledge Base Indexer, and a dedicated Messages view that mimics WhatsApp Web.
- **Real-Time feel:** Uses `setInterval` polling (every 3 seconds) instead of WebSockets to fetch new messages and update the UI seamlessly.

### 3. Local AI Auto-Replies & RAG
- **RAG Engine:** Documents in `data/knowledge_base/` and sample properties in `data/properties.json` are chunked, embedded using `sentence-transformers`, and stored in ChromaDB.
- **Auto-Reply:** When an incoming message is received (via webhook or UI simulation), if `auto_reply` is enabled for that lead, the backend queries ChromaDB for context, constructs a prompt, and queries the local Ollama instance to generate a contextual, helpful response.

## 🗄️ Database Schema (`models.py`)
- **Lead:** `id`, `name`, `phone`, `email`, `source`, `status`, `budget_min`, `budget_max`, `preferred_location`, `property_type`, `configuration`, `price`, `notes`, `created_at`, `updated_at`.
- **Message:** `id`, `lead_id`, `direction` (inbound/outbound), `content`, `status`, `timestamp`.
- **Property:** `id`, `title`, `description`, `price`, `location`, `property_type`, `bedrooms`, `bathrooms`, `size_sqft`, `amenities`.
- **FollowUp:** `id`, `lead_id`, `frequency_hours`, `next_run`, `max_followups`, `completed_followups`, `message_template`, `active`.

## 🚀 How to Implement New Features (Guide for LLMs)
If you are tasked with adding a new feature, follow these guidelines to maintain architectural consistency:

1. **Database Changes:**
   - Update `backend/models.py`.
   - Update the Pydantic schemas in `backend/main.py` to ensure the new fields are serialized in JSON responses.
   - If the database schema changes significantly, you may need to drop `leads.db` (as there are no alembic migrations currently configured).

2. **Backend API Changes:**
   - Add routes directly in `backend/main.py` using FastAPI decorators.
   - For heavy background processing, use the `apscheduler` instance in `backend/followup.py`.

3. **Frontend Changes:**
   - Update `frontend/index.html` for DOM structure.
   - Add vanilla CSS to `frontend/style.css` (we avoid Tailwind unless strictly necessary to maintain the custom design system).
   - Update `frontend/app.js` using standard `fetch` API for network calls and DOM manipulation. Be mindful of browser caching during local development.

4. **Parser/Ingestion Changes:**
   - Modify `backend/parser.py`.
   - Ensure generic regex fallbacks are placed at the end of the extraction logic to catch any edge cases that specific portal parsers miss. 
   - Always validate extracted strings (e.g. `strip()`, `upper()`) before insertion.
