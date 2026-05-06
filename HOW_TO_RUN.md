# How to Run LeadPilot

Follow these steps to start the LeadPilot Real Estate Lead Management System on your Windows machine.

### 1. Prerequisite: Ollama
Ensure you have **Ollama** installed and running.
- The system will attempt to start Ollama automatically, but it's better to have it running in the background.
- You should have the `phi3:mini` model pulled: `ollama pull phi3:mini`

### 2. Fast Start (Recommended)
The easiest way to run the app is using the provided batch file:
1.  Open a terminal (PowerShell or Command Prompt) in the project directory.
2.  Run the following command:
    ```powershell
    .\start.bat
    ```
3.  Wait for the terminal to say `[OK] Server ready at http://localhost:8000`.
4.  Open your browser to: **[http://localhost:8000](http://localhost:8000)**

### 3. Manual Start (If start.bat fails)
If you prefer to run the components manually:

**Step A: Activate Virtual Environment**
```powershell
.\venv\Scripts\activate
```

**Step B: Start the Backend Server**
```powershell
python backend/main.py
```

### 4. Troubleshooting
- **Port 8000 is occupied**: If you see an error saying "Only one usage of each socket address is permitted", it means the server is already running. You can stop it by pressing `Ctrl+C` in the terminal where it's running, or by closing that terminal.
- **AI not replying**: Ensure Ollama is running and you have internet access for the first-time setup (the system needs to download a small embedding model (~100MB) for the knowledge base).

### 5. Updating Knowledge Base
If you add new `.txt` files to `data/knowledge_base/`, simply restart the server. It will automatically re-index the files on startup.
