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


def _truncate_reply(text: str, max_sentences: int = 2) -> str:
    """Hard-cap AI output to max_sentences. LLMs often ignore length constraints."""
    import re
    if not text:
        return text
    # Split on sentence-ending punctuation followed by space or end
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    truncated = ' '.join(sentences[:max_sentences]).strip()
    # Ensure it ends with punctuation
    if truncated and truncated[-1] not in '.!?':
        truncated += '.'
    return _scrub_brokerage(truncated)


def _scrub_brokerage(text: str) -> str:
    """Remove any mention of brokerage/commission/GST from AI output.
    The AI should NEVER proactively mention these — only when explicitly asked."""
    import re
    if not text:
        return text
    # Remove sentences/clauses that mention brokerage, commission, or GST
    # Pattern: match "with no brokerage...", "no brokerage...", "without brokerage..."
    patterns = [
        r'\s*[,.]?\s*with\s+no\s+brokerage[^.!?]*[.!?]?',
        r'\s*[,.]?\s*no\s+brokerage[^.!?]*[.!?]?',
        r'\s*[,.]?\s*without\s+(any\s+)?brokerage[^.!?]*[.!?]?',
        r'\s*[,.]?\s*zero\s+brokerage[^.!?]*[.!?]?',
        r'\s*[,.]?\s*brokerage[\s-]?free[^.!?]*[.!?]?',
    ]
    for p in patterns:
        text = re.sub(p, '', text, flags=re.IGNORECASE)
    # Also remove any standalone mention of "brokerage" or "GST" in a clause
    # e.g. "...with no brokerage or GST fees involved"
    text = re.sub(r'\s*,?\s*(?:with\s+)?no\s+(?:brokerage|commission|GST)[^.!?]*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    if text and text[-1] not in '.!?':
        text += '.'
    return text


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
    """Generate a warm, engaging WhatsApp reply for a new lead."""
    prompt = f"""You are a helpful real estate assistant at Vanaha Township, Bavdhan. 
Write a warm WhatsApp reply (1-2 sentences ONLY) to: {lead_name}.
Interest: {property_interest}
Rules: Answer directly if info is known, then ask "Aap visit kab plan kar rahe ho?" or "Should I share photos?".
Reply:"""
    return _truncate_reply(generate(prompt, max_tokens=60))


def generate_followup_message(lead_name: str, interaction_count: int, last_message: str = "") -> str:
    """Generate a follow-up WhatsApp message."""
    prompt = f"""Write a SHORT WhatsApp follow-up message (1-2 sentences ONLY) for a real estate lead.

Lead: {lead_name}
Follow-up #{interaction_count}
{f'Last msg: {last_message[:100]}' if last_message else ''}

Keep it very brief. Ask if they need help or want to visit:"""
    return _truncate_reply(generate(prompt, max_tokens=60))


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
    """Generate a quick, relevant auto-reply."""
    prompt = f"""You are a real estate assistant. Reply to: {incoming_message}
From: {lead_name}
Context: {lead_context}
Rules: 1-2 sentences ONLY. Answer the question directly then ask "Aap kab visit karenge?" or "Should I share layout videos?". No introductions.
Reply:"""
    return _truncate_reply(generate(prompt, max_tokens=60))


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
    Supports Hinglish/Marathi detection and uses last 10 messages for context.
    """
    # Load the FULL knowledge base (small file, ~7KB — fits easily)
    full_kb = _load_full_knowledge_base()

    # Build recent conversation history — skip welcome sequence messages to keep context clean
    history_text = ""
    if conversation_history:
        # Filter out welcome sequence / media messages to keep context focused
        filtered = []
        for m in conversation_history:
            content = m.get("content", "")
            # Skip welcome sequence texts, media refs, and very long messages (bulk texts)
            if not content:
                continue
            if content.startswith("[IMAGE:") or content.startswith("[VIDEO:"):
                continue
            if len(content) > 200:  # Welcome texts are long — skip them
                continue
            if any(skip in content for skip in ["Please wait and don't reply", "Please find below the photos", "Please find below the Videos", "Rent Structure", "Buying Prices"]):
                continue
            filtered.append(m)
        recent = filtered[-10:]  # Last 10 clean messages only
        lines = []
        for m in recent:
            role = "Customer" if m.get("direction") == "in" else "You"
            lines.append(f"{role}: {m.get('content', '')[:150]}")
        history_text = "\n".join(lines)

    prompt = f"""You are a WhatsApp real estate assistant at Vanaha Township, Bavdhan, Pune.

PRICES:
RENT: 1BHK=16k-18k, 2BHK=21k-22k, 3BHK Compact=23k-25k, 3BHK Grande=26k-28k
BUY: 1BHK=51L, 2BHK=81L, 3BHK Compact=90L, 3BHK Grande=1Cr
Deposit=2 months rent. Location=12 min from Chellaram Hospital, Bavdhan Highway.

FACTS:
{full_kb[:3500]}

INSTRUCTIONS: Reply in 1-2 SHORT sentences. If customer asks about RENT give rent price. If customer asks about BUYING/PURCHASE give buy price. End with a question. No introductions. Use Hinglish naturally.

{f'Recent chat:' if history_text else ''}
{history_text}

Customer: {incoming_message[:200]}
Reply:"""
    reply = generate(prompt, max_tokens=80, temperature=0.3)
    return _truncate_reply(reply)


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
