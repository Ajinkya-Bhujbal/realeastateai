# 🏠 LeadPilot — AI-Powered Real Estate Lead Management System

A **fully local**, AI-powered lead management system for Indian real estate agents. Ingests leads from Housing.com, 99acres, and MagicBricks emails, sends WhatsApp messages, auto-replies with AI, recommends properties using RAG, and automates follow-ups — all running on your own machine.

---

## 📋 Table of Contents

1. [System Requirements](#-system-requirements)
2. [Quick Start (2 Steps)](#-quick-start)
3. [Detailed Installation Guide](#-detailed-installation-guide)
   - [Step 1: Install Python](#step-1-install-python-310)
   - [Step 2: Install Ollama](#step-2-install-ollama-local-ai)
   - [Step 3: Install Project Dependencies](#step-3-install-project-dependencies)
   - [Step 4: Configure Environment](#step-4-configure-environment-env-file)
4. [WhatsApp Business API Setup](#-whatsapp-business-cloud-api-setup)
5. [Gmail App Password Setup](#-gmail-app-password-setup)
6. [Running the System](#-running-the-system)
7. [Using the Dashboard](#-using-the-dashboard)
8. [API Reference](#-api-reference)
9. [Folder Structure](#-folder-structure)
10. [Troubleshooting](#-troubleshooting)

---

## 💻 System Requirements

| Requirement     | Minimum                          |
|-----------------|----------------------------------|
| **OS**          | Windows 10/11                    |
| **RAM**         | 8 GB (system uses ~3-4 GB)       |
| **CPU**         | Intel i5 / AMD Ryzen 5 or better |
| **Disk Space**  | ~5 GB (for models + dependencies)|
| **GPU**         | ❌ Not required (optional, auto-detected) |
| **Internet**    | Only needed for first-time setup + WhatsApp API |

---

## ⚡ Quick Start

If you just want to get running fast:

```batch
:: Step 1 — Install everything (run once)
install.bat

:: Step 2 — Start the system
start.bat
```

The dashboard opens at **http://localhost:8000**

> ⚠️ You must have **Python 3.10+** and **Ollama** installed first. See detailed steps below.

---

## 📦 Detailed Installation Guide

### Step 1: Install Python 3.10+

1. Download Python from **https://www.python.org/downloads/**
2. Run the installer
3. ✅ **IMPORTANT:** Check **"Add Python to PATH"** during installation
4. Verify it works:
   ```
   python --version
   ```
   You should see `Python 3.10.x` or higher.

---

### Step 2: Install Ollama (Local AI)

Ollama runs AI models locally on your machine. No cloud, no API keys, completely private.

1. Go to **https://ollama.com/download/windows**
2. Download and run the Windows installer
3. After installation, open a terminal and verify:
   ```
   ollama --version
   ```
4. Pull the AI model we use (Phi-3 Mini, ~2.3 GB download):
   ```
   ollama pull phi3:mini
   ```
   Wait for the download to complete. This only happens once.

5. Start Ollama (if not already running):
   ```
   ollama serve
   ```
   > Ollama usually runs automatically after installation. You can check by visiting http://localhost:11434 in your browser — if you see "Ollama is running", you're good.

**That's it for AI setup.** No API keys, no cloud accounts, no GPU required.

---

### Step 3: Install Project Dependencies

Option A — **Use the install script** (recommended):
```batch
install.bat
```

Option B — **Manual install**:
```batch
:: Create virtual environment
python -m venv venv

:: Activate it
venv\Scripts\activate

:: Install Python packages
pip install -r requirements.txt
```

**What gets installed:**

| Package              | Purpose                        | Size    |
|----------------------|--------------------------------|---------|
| `fastapi`            | Web API server                 | ~2 MB   |
| `uvicorn`            | ASGI server                    | ~1 MB   |
| `sqlalchemy`         | Database ORM (SQLite)          | ~3 MB   |
| `pydantic`           | Data validation                | ~2 MB   |
| `requests`           | HTTP client                    | ~500 KB |
| `apscheduler`        | Follow-up scheduling           | ~200 KB |
| `chromadb`           | Vector database for RAG        | ~50 MB  |
| `sentence-transformers` | Text embeddings (MiniLM)    | ~100 MB |
| `python-dotenv`      | Load .env config               | ~30 KB  |
| `torch` (CPU)        | ML framework (auto-installed)  | ~150 MB |

---

### Step 4: Configure Environment (.env file)

1. **Copy the template:**
   ```batch
   copy .env.example .env
   ```

2. **Edit `.env`** with your values:
   ```env
   # --- Ollama (usually no changes needed) ---
   OLLAMA_URL=http://localhost:11434
   OLLAMA_MODEL=phi3:mini

   # --- Gmail (optional — only if you want email ingestion) ---
   GMAIL_USER=your.email@gmail.com
   GMAIL_APP_PASSWORD=abcd efgh ijkl mnop

   # --- WhatsApp (optional — only if you want WhatsApp messaging) ---
   WA_API_URL=https://graph.facebook.com/v18.0
   WA_PHONE_NUMBER_ID=your_phone_number_id
   WA_ACCESS_TOKEN=your_access_token
   WA_VERIFY_TOKEN=leadbot_verify_2024

   # --- Server ---
   SERVER_HOST=0.0.0.0
   SERVER_PORT=8000
   ```

> **Note:** Gmail and WhatsApp are **optional**. The system works perfectly without them — you can add leads manually and use AI features without any external API.

---

## 📱 WhatsApp Business Cloud API Setup

This is a **step-by-step guide** to get your WhatsApp API credentials. It's free for testing (up to 1,000 conversations/month).

### Prerequisites
- A **Facebook account**
- A **phone number** that can receive SMS (for verification)

### Step-by-step

#### 1. Create a Meta Developer Account

1. Go to **https://developers.facebook.com/**
2. Click **"Get Started"** (top right)
3. Log in with your Facebook account
4. Accept the terms and complete verification

#### 2. Create a New App

1. Go to **https://developers.facebook.com/apps/**
2. Click **"Create App"**
3. Select **"Other"** → Click Next (If prompted for Use Cases, select **"Connect with customers through WhatsApp"**)
4. Select **"Business"** → Click Next
5. Fill in:
   - **App name:** `LeadPilot` (or any name)
   - **Contact email:** your email
6. Click **"Create App"**

#### 3. Add WhatsApp to Your App

*Note: Meta frequently updates their dashboard. If you don't see an "Add products" section, follow these steps:*

1. On the app dashboard, look for the **"App customization and requirements"** section and click **"Customize the Connect with customers through WhatsApp use case"**.
   *(Alternatively, click on **"Use cases"** in the left sidebar and add WhatsApp).*
2. Follow the on-screen prompts. If asked, create a new **Meta Business Account** or select an existing one.
3. Once completed, a **"WhatsApp"** menu item will appear in the left sidebar.

#### 4. Get Your Credentials

After setup, expand the **"WhatsApp"** menu in the left sidebar and click on **"API Setup"**:

1. **Temporary Access Token** — Copy this. It's your `WA_ACCESS_TOKEN`
   > ⚠️ This token expires in 24 hours. For production, generate a permanent token (see below).

2. **Phone Number ID** — Under "Step 1: Select phone numbers", you'll see a test phone number. The **Phone number ID** shown below it is your `WA_PHONE_NUMBER_ID`

3. **Test Phone Number** — Meta provides a free test phone number. You can send messages FROM this number.

4. **Add a Recipient** — Under "To", click **"Manage phone number list"** and add the phone numbers you want to send messages TO (up to 5 for testing).

#### 5. Set Your .env Values

```env
WA_API_URL=https://graph.facebook.com/v18.0
WA_PHONE_NUMBER_ID=123456789012345
WA_ACCESS_TOKEN=EAAxxxxxxxxxxxxxxx...
WA_VERIFY_TOKEN=leadbot_verify_2024
```

#### 6. (Optional) Set Up Webhook for Receiving Messages

To receive incoming WhatsApp messages:

1. In your app's WhatsApp settings, go to **"Configuration"**
2. Click **"Edit"** next to Webhook
3. Set:
   - **Callback URL:** `https://your-domain.com/api/webhook/whatsapp`
   - **Verify Token:** `leadbot_verify_2024` (must match your `.env`)
4. Subscribe to **"messages"** field

> **Note:** Webhooks require a public URL. For local development, use **ngrok**:
> ```
> ngrok http 8000
> ```
> Then use the ngrok URL as your callback URL.

#### 7. (Optional) Generate a Permanent Access Token

The temporary token expires in 24 hours. For a permanent token:

1. Go to **Business Settings** → **System Users**
2. Create a system user (Admin role)
3. Click **"Generate Token"**
4. Select your WhatsApp app
5. Add permission: `whatsapp_business_messaging`
6. Copy the generated token — this one never expires

### WhatsApp API Summary

| .env Variable         | Where to Find It                                      |
|-----------------------|-------------------------------------------------------|
| `WA_API_URL`          | Always `https://graph.facebook.com/v18.0`             |
| `WA_PHONE_NUMBER_ID`  | WhatsApp > API Setup > "Phone number ID"              |
| `WA_ACCESS_TOKEN`     | WhatsApp > API Setup > "Temporary access token"       |
| `WA_VERIFY_TOKEN`     | You choose this (default: `leadbot_verify_2024`)      |

---

## 📧 Gmail App Password Setup

To fetch leads from your Gmail inbox (from Housing.com, 99acres, MagicBricks emails):

### Step 1: Enable 2-Step Verification

1. Go to **https://myaccount.google.com/security**
2. Under "How you sign in to Google", enable **2-Step Verification**

### Step 2: Generate an App Password

1. Go to **https://myaccount.google.com/apppasswords**
   > If you don't see this page, make sure 2-Step Verification is enabled first.
2. Enter a name: `LeadPilot`
3. Click **"Create"**
4. Google will show a **16-character password** like `abcd efgh ijkl mnop`
5. Copy it — you won't see it again!

### Step 3: Set Your .env Values

```env
GMAIL_USER=your.email@gmail.com
GMAIL_APP_PASSWORD=abcd efgh ijkl mnop
```

> **Security Note:** This is NOT your regular Gmail password. App passwords only work for specific apps and can be revoked anytime at the link above.

---

## 🚀 Running the System

### Option A: Use start.bat (Recommended)

```batch
start.bat
```

This automatically:
1. Starts Ollama (if not running)
2. Launches the FastAPI server
3. Opens the dashboard in your browser

### Option B: Manual Start

```batch
:: Terminal 1 — Start Ollama
ollama serve

:: Terminal 2 — Start the server
venv\Scripts\activate
cd backend
python main.py
```

### Access Points

| URL                        | Purpose            |
|----------------------------|---------------------|
| http://localhost:8000      | Dashboard UI        |
| http://localhost:8000/docs | Swagger API docs    |

---

## 🖥️ Using the Dashboard

### Dashboard
- View total leads, status breakdown, messages sent, active follow-ups
- See recent leads and lead sources at a glance

### Leads
- Search, filter by status (New / Contacted / Interested / Converted / Lost)
- **Tags** — Assign custom tags like "Visited", "Interested", "Not Interested" or create your own custom tags via the dropdown.
- **Source Filtering** — Housing.com / 99acres / MagicBricks / Manual
- **Auto-Extraction** — The system automatically extracts **Price**, **Location**, and **Flat Configuration** (e.g., 1BHK, 2BHK) from incoming emails.
- Add leads manually or via automated Gmail polling (refreshes every 1 minute).

### Properties
- Click **"Index Samples"** to load 15 sample Indian properties into the RAG engine
- Search properties using natural language: *"3BHK apartment in Whitefield under 100 lakhs"*
- Results show relevance scores based on semantic similarity

### Messages (WhatsApp Web-style)
The Messages view is a full **WhatsApp Web-style chat interface**:

- **Left panel** — Contact list sorted by last message time, with:
  - Avatar (initials), name, last message preview
  - Unread message count badge (green circle)
  - 🤖 icon showing auto-reply is enabled
  - Search bar to filter contacts
- **Right panel** — Chat area with:
  - Message bubbles (outgoing = right/blue, incoming = left/dark)
  - Date dividers between message groups
  - Timestamps on each message
  - Auto-reply toggle (🤖 button in header) — ON/OFF per lead
- **Input bar** — Type message + Send, or click 🤖 to generate AI reply
- **Simulate button** (📩) — Test incoming messages without real WhatsApp webhook
- **Real-time polling** — UI refreshes every 3 seconds for new messages

**Auto-reply flow:**
1. Incoming message arrives (via webhook or simulate)
2. System checks knowledge base + properties for relevant context
3. Ollama generates a contextual reply using RAG
4. Reply is sent via WhatsApp automatically (if auto-reply is ON)

### AI Tools
- **AI Status** — Check if Ollama is running and which models are loaded
- **Knowledge Base** — View indexed files, click "Index Knowledge Base" to re-index
- **Parse Email** — Paste a real estate email and extract lead info automatically
- **RAG Search** — Search the knowledge base with AI-powered semantic matching
- **Follow-up** — Schedule automated follow-ups (frequency in hours, max count)

---

## 📚 Knowledge Base (RAG)

The system uses a **knowledge base** to generate smarter AI replies. When a lead asks a question, the AI searches your knowledge base for relevant info and includes it in the response.

### Adding Knowledge Base Files

1. Place `.txt` or `.md` files in the `data/knowledge_base/` folder
2. Go to **AI Tools** → click **"Index Knowledge Base"**
3. Files are split into chunks, embedded, and stored in ChromaDB

### Sample Files Included

| File | Content |
|------|---------|
| `about_company.txt` | Company info, services, working hours |
| `pricing_faq.txt` | Common pricing questions, costs, documents needed |
| `localities.txt` | Bangalore locality guide with price ranges |

### Tips for Good Knowledge Base Files
- Write in clear Q&A or structured format
- Include specific details: prices, locations, builder names
- Keep files focused on one topic each
- Update and re-index whenever information changes

---

## 📡 API Reference

### Lead Management
| Method   | Endpoint                  | Description                    |
|----------|---------------------------|--------------------------------|
| `POST`   | `/api/leads`              | Create a new lead              |
| `GET`    | `/api/leads`              | List leads (filter/search)     |
| `GET`    | `/api/leads/{id}`         | Get lead details + messages    |
| `PUT`    | `/api/leads/{id}`         | Update a lead                  |
| `DELETE` | `/api/leads/{id}`         | Delete a lead                  |

### Email Parsing
| Method   | Endpoint                  | Description                    |
|----------|---------------------------|--------------------------------|
| `POST`   | `/api/parse-email`        | Parse email, return data       |
| `POST`   | `/api/parse-email/save`   | Parse email, save as lead      |
| `POST`   | `/api/gmail/fetch`        | Fetch leads from Gmail inbox   |

*Note: The email parser extracts hidden phone numbers by automatically following housing.com redirects. It also extracts configuration (e.g., "2 BHK") and budget/pricing details directly from the email body. The background poller uses a streaming generator to live-ingest thousands of historical emails with a smart early-exit strategy for duplicates.*

### Chat (WhatsApp Web)
| Method   | Endpoint                              | Description                    |
|----------|---------------------------------------|--------------------------------|
| `GET`    | `/api/chats`                          | List all conversations (sidebar) |
| `GET`    | `/api/chats/{lead_id}`                | Get full chat history          |
| `POST`   | `/api/chats/{lead_id}/send`           | Send a message                 |
| `POST`   | `/api/chats/{lead_id}/read`           | Mark all messages as read      |
| `POST`   | `/api/chats/{lead_id}/toggle-auto-reply` | Toggle auto-reply ON/OFF    |
| `GET`    | `/api/chats/unread-count`             | Total unread across all leads  |
| `POST`   | `/api/chats/simulate-incoming`        | Simulate incoming message (test) |

### Messaging (Legacy)
| Method   | Endpoint                  | Description                    |
|----------|---------------------------|--------------------------------|
| `POST`   | `/api/messages/send`      | Send WhatsApp message          |
| `GET`    | `/api/messages/{lead_id}` | Get conversation history       |
| `GET`    | `/api/webhook/whatsapp`   | WhatsApp webhook verification  |
| `POST`   | `/api/webhook/whatsapp`   | Receive WhatsApp messages      |

### AI
| Method   | Endpoint                  | Description                    |
|----------|---------------------------|--------------------------------|
| `POST`   | `/api/ai/reply`           | Generate AI reply for lead     |
| `POST`   | `/api/ai/recommend`       | AI property recommendation     |
| `GET`    | `/api/ai/status`          | Check Ollama status            |

### Knowledge Base
| Method   | Endpoint                  | Description                    |
|----------|---------------------------|--------------------------------|
| `POST`   | `/api/kb/index`           | Index all KB files             |
| `GET`    | `/api/kb/status`          | KB file count + chunks indexed |
| `POST`   | `/api/kb/search`          | Semantic search the KB         |

### Properties
| Method   | Endpoint                       | Description                 |
|----------|--------------------------------|-----------------------------|
| `POST`   | `/api/properties`              | Add a property              |
| `GET`    | `/api/properties`              | List all properties         |
| `POST`   | `/api/properties/search`       | RAG semantic search         |
| `POST`   | `/api/properties/index-samples`| Index sample properties     |

### Follow-ups
| Method   | Endpoint                  | Description                    |
|----------|---------------------------|--------------------------------|
| `POST`   | `/api/followups`          | Create follow-up schedule      |
| `GET`    | `/api/followups`          | List active follow-ups         |
| `DELETE` | `/api/followups/{id}`     | Cancel a follow-up             |

### System
| Method   | Endpoint                  | Description                    |
|----------|---------------------------|--------------------------------|
| `GET`    | `/api/health`             | Health check                   |
| `GET`    | `/api/dashboard/stats`    | Dashboard statistics           |

---

## 📁 Folder Structure

```
real-estate-leads/
├── backend/
│   ├── main.py          # FastAPI app — all endpoints (including Chat & KB APIs)
│   ├── db.py            # SQLAlchemy + SQLite setup
│   ├── models.py        # Database models (Lead, Message, Property, FollowUp)
│   ├── parser.py        # Email parser (Housing.com, 99acres, MagicBricks)
│   ├── ai.py            # Ollama AI + RAG-powered reply generation
│   ├── rag.py           # ChromaDB RAG (property search + knowledge base)
│   ├── whatsapp.py      # WhatsApp Business API integration
│   └── followup.py      # APScheduler: follow-ups + auto-reply processor
├── frontend/
│   ├── index.html       # Dashboard UI (WhatsApp Web-style Messages view)
│   ├── style.css        # Dark mode design system
│   └── app.js           # Frontend JS (ChatManager with 3s polling)
├── data/
│   ├── properties.json  # 15 sample Indian properties
│   ├── knowledge_base/  # RAG knowledge base (.txt and .md files)
│   │   ├── about_company.txt
│   │   ├── pricing_faq.txt
│   │   └── localities.txt
│   ├── leads.db         # SQLite database (auto-created)
│   └── chroma_db/       # Vector store (auto-created)
├── .env.example         # Environment variable template
├── .env                 # Your actual config (not in git)
├── requirements.txt     # Python dependencies
├── install.bat          # One-click installer
├── start.bat            # One-click launcher
└── README.md            # This file
```

---

## 🔧 Troubleshooting

### "Python not found"
- Make sure Python is installed and added to PATH
- Try: `python --version` or `python3 --version`

### "Ollama not running"
- Open a terminal and run: `ollama serve`
- Or restart your computer (Ollama auto-starts on boot)
- Check: visit http://localhost:11434 in your browser

### "No models loaded"
- Run: `ollama pull phi3:mini`
- Wait for the download (~2.3 GB)
- Verify: `ollama list` should show `phi3:mini`

### "Port 8000 already in use"
- Change the port in `.env`: `SERVER_PORT=8001`
- Or kill the process using port 8000:
  ```batch
  netstat -aon | findstr :8000
  taskkill /F /PID <PID_NUMBER>
  ```

### "WhatsApp messages not sending"
- Check your `WA_ACCESS_TOKEN` hasn't expired (temporary tokens last 24 hours)
- Make sure recipient phone numbers are added to your test list in Meta Developer Console
- The system works in mock mode without WhatsApp configured — messages are logged but not sent

### "Gmail fetch not working"
- Make sure 2-Step Verification is enabled on your Google account
- Generate a fresh App Password at https://myaccount.google.com/apppasswords
- Check that `GMAIL_USER` and `GMAIL_APP_PASSWORD` are set in `.env`

### "RAG search returns no results"
- Click **"Index Samples"** on the Properties page first
- Or call: `POST /api/properties/index-samples`

### "AI replies are slow"
- First request takes ~30-60 seconds (model loading into RAM)
- Subsequent requests are faster (~5-15 seconds)
- Phi-3 Mini uses ~2.3 GB RAM — make sure you have enough free memory

---

## 📄 License

MIT License — use freely for personal or commercial purposes.
