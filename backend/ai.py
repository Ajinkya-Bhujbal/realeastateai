"""
AI module - Ollama integration with Phi-3 mini.
Generates auto-replies, follow-up messages, and lead summaries.
Uses RAG knowledge base for context-aware responses.
Runs fully on CPU, uses GPU if available.
"""
import os
import requests
import json
from typing import Optional

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "phi3:mini")


def check_ollama() -> bool:
    """Check if Ollama is running."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def list_models() -> list:
    """List available Ollama models."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if r.status_code == 200:
            data = r.json()
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        pass
    return []


def generate(prompt: str, model: str = DEFAULT_MODEL, max_tokens: int = 300, temperature: float = 0.7) -> str:
    """Generate text using Ollama. Keeps prompts short for low RAM usage."""
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                    "top_p": 0.9,
                    "num_ctx": 4096,  # Gemma2 9B can handle 8192; 4096 is safe for RAM
                },
            },
            timeout=120,
        )
        if r.status_code == 200:
            return r.json().get("response", "").strip()
        else:
            return f"[AI Error: {r.status_code}]"
    except requests.exceptions.ConnectionError:
        return "[Ollama not running. Start Ollama first.]"
    except Exception as e:
        return f"[AI Error: {str(e)}]"


def generate_lead_reply(lead_name: str, property_interest: str, context: str = "") -> str:
    """Generate a WhatsApp reply for a new lead."""
    prompt = f"""You are a friendly Indian real estate agent. Write a short WhatsApp reply (2-3 lines max) to a new lead.

Lead: {lead_name}
Interest: {property_interest}
{f'Context: {context}' if context else ''}

Reply (be warm, professional, mention you will share options):"""
    return generate(prompt, max_tokens=150)


def generate_followup_message(lead_name: str, interaction_count: int, last_message: str = "") -> str:
    """Generate a follow-up WhatsApp message."""
    prompt = f"""Write a short WhatsApp follow-up message (2-3 lines max) for a real estate lead.

Lead: {lead_name}
Follow-up #{interaction_count}
{f'Last msg: {last_message[:100]}' if last_message else ''}

Keep it friendly and brief. Ask if they need help or want to schedule a visit:"""
    return generate(prompt, max_tokens=120)


def generate_property_recommendation(lead_name: str, preferences: str, properties: list) -> str:
    """Generate a property recommendation message using RAG results."""
    props_text = ""
    for i, p in enumerate(properties[:3], 1):
        props_text += f"{i}. {p.get('title', 'N/A')} - {p.get('location', 'N/A')} - Rs {p.get('price', 'N/A')}L - {p.get('bedrooms', 'N/A')}BHK\n"

    prompt = f"""You are a real estate agent. Recommend properties to the lead in a WhatsApp message (4-5 lines max).

Lead: {lead_name}
Preferences: {preferences}

Matching Properties:
{props_text}

Write a friendly WhatsApp message recommending these properties:"""
    return generate(prompt, max_tokens=200)


def generate_auto_reply(incoming_message: str, lead_name: str, lead_context: str = "") -> str:
    """Generate an auto-reply for an incoming WhatsApp message."""
    prompt = f"""You are a real estate agent's AI assistant. Reply to this WhatsApp message in 2-3 lines.

From: {lead_name}
Message: {incoming_message[:200]}
{f'Context: {lead_context[:200]}' if lead_context else ''}

Reply (be helpful, professional, brief):"""
    return generate(prompt, max_tokens=150)


def _load_full_knowledge_base() -> str:
    """Load the entire knowledge base from disk so the AI always has full context."""
    kb_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "knowledge_base")
    kb_text = ""
    if os.path.isdir(kb_dir):
        for fname in os.listdir(kb_dir):
            if fname.endswith((".txt", ".md")):
                fpath = os.path.join(kb_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        kb_text += f.read() + "\n"
                except Exception:
                    pass
    return kb_text.strip()


def generate_rag_reply(
    incoming_message: str,
    lead_name: str,
    lead_context: str = "",
    kb_results: list = None,
    property_results: list = None,
    conversation_history: list = None,
) -> str:
    """
    Generate an AI reply using the FULL knowledge base injected into the prompt.
    Supports Hinglish/Marathi detection and uses last 20 messages for context.
    """
    # Load the FULL knowledge base (small file, ~7KB — fits easily)
    full_kb = _load_full_knowledge_base()

    # Build recent conversation history (last 20 messages for context)
    history_text = ""
    if conversation_history:
        recent = conversation_history[-20:]
        lines = []
        for m in recent:
            role = "Customer" if m.get("direction") == "in" else "You"
            lines.append(f"{role}: {m.get('content', '')[:250]}")
        history_text = "\n".join(lines)

    prompt = f"""You are a WhatsApp sales agent for Armstrong Properties — the biggest property broker at Shapoorji Pallonji Vanaha Township, Bavdhan, Pune. Phase 1 is called Yahavi.

=== COMPANY KNOWLEDGE BASE ===
{full_kb[:5500]}
=== END ===

RULES:
1. Use ONLY facts from the knowledge base above. Never invent prices, places, or details.
2. If the customer writes in Hinglish (Hindi written in English) or Marathi written in English, reply in Hinglish.
3. If the customer writes in English, reply in English.
4. Keep replies SHORT — maximum 2-3 sentences. No long paragraphs.
5. Give EXACT numbers: rent = 16k-28k, buy = 51L-1Cr, deposit = 2 months.
6. If info is not in KB, say: "Ek min, team se check karke batata hu."
7. Never add disclaimers, notes, or meta-commentary.
8. Be warm, friendly, and direct — like a real broker on WhatsApp.

{f'CONVERSATION SO FAR:' if history_text else ''}
{history_text}

Customer: {lead_name}
{f'Preferences: {lead_context}' if lead_context else ''}
Latest message: {incoming_message[:300]}

Your reply:"""
    return generate(prompt, max_tokens=200, temperature=0.1)


def summarize_lead(lead_data: dict) -> str:
    """Generate a brief summary of a lead."""
    prompt = f"""Summarize this real estate lead in 2 lines:
Name: {lead_data.get('name', 'N/A')}
Budget: {lead_data.get('budget_min', 'N/A')}-{lead_data.get('budget_max', 'N/A')} Lakhs
Location: {lead_data.get('preferred_location', 'N/A')}
Type: {lead_data.get('property_type', 'N/A')}
Source: {lead_data.get('source', 'N/A')}

Summary:"""
    return generate(prompt, max_tokens=100)
