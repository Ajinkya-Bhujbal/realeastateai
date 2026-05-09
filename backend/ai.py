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
    """Post-process AI output for brokerage mentions.
    
    Brokerage info is now correctly provided in the prompt:
    - Rental: 1 month rent brokerage
    - Buying: Zero brokerage
    So we no longer strip these mentions — they are valid answers.
    Only strip GST mentions (never relevant).
    """
    import re
    if not text:
        return text
    # Only strip GST mentions — brokerage is now legitimate info
    text = re.sub(r'\s*[,.]?\s*(?:plus|with|and)?\s*(?:no\s+)?GST[^.!?]*[.!?]?', '', text, flags=re.IGNORECASE)
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


def _strip_price_chunks(kb_text: str) -> str:
    """Remove Rent Structure and Buying Prices chunks from KB text.
    
    These are already provided as an explicit price table in the prompt.
    Having them duplicated in the FACTS section causes phi3:mini to
    mix up rent (thousands) and buy (lakhs) prices.
    """
    import re
    # Remove the Rent Structure chunk (VAN-005)
    kb_text = re.sub(
        r'CHUNK_ID:\s*VAN-005.*?={10,}',
        '',
        kb_text,
        flags=re.DOTALL
    )
    # Remove the Buying Prices chunk (VAN-006)
    kb_text = re.sub(
        r'CHUNK_ID:\s*VAN-006.*?={10,}',
        '',
        kb_text,
        flags=re.DOTALL
    )
    # Clean up multiple blank lines
    kb_text = re.sub(r'\n{3,}', '\n\n', kb_text)
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
    Generate an AI reply using RAG context.
    """
    # 1. Process KB results into a clean context string
    context_text = ""
    if kb_results:
        chunks = []
        for res in kb_results:
            # Skip price chunks if they somehow got in (we want prices ONLY from our table)
            if "VAN-005" in res['text'] or "VAN-006" in res['text']:
                continue
            chunks.append(res['text'])
        context_text = "\n\n".join(chunks)

    # 2. Build recent conversation history
    history_text = ""
    if conversation_history:
        filtered = []
        for m in conversation_history:
            content = m.get("content", "")
            if not content or content.startswith("[IMAGE:") or content.startswith("[VIDEO:"):
                continue
            if len(content) > 300:  # Skip very long welcome messages
                continue
            if any(skip in content for skip in ["wait and don't reply", "find below the photos", "find below the Videos"]):
                continue
            filtered.append(m)
        
        recent = filtered[-10:]
        lines = []
        for m in recent:
            role = "Customer" if m.get("direction") == "in" else "Agent"
            content = m.get('content', '')
            # Skip old agent replies that contain wrong price/brokerage info 
            # (from previous hallucinations) to prevent the model from repeating them
            if role == "Agent" and any(bad in content.lower() for bad in [
                'rs.10l', 'rs.25l', '26l', 'equivalent to one month', 'matey',
                'ranges from rs. 16k to', 'rs.16k to rs'
            ]):
                continue
            lines.append(f"{role}: {content}")
        history_text = "\n".join(lines)

    # 3. Create a bullet-proof prompt
    prompt = f"""You are an expert real estate agent at Armstrong Properties, Vanaha Township, Bavdhan, Pune.
Task: Answer the Customer's query accurately using ONLY the data below.

=== PRICE TABLE (THESE ARE THE ONLY CORRECT PRICES) ===
FOR RENT (Monthly):
  1 BHK rent = 16,000 to 18,000 per month
  2 BHK rent = 21,000 to 22,000 per month
  3 BHK Compact rent = 23,000 to 25,000 per month
  3 BHK Grande rent = 26,000 to 28,000 per month
  Deposit = 2 months rent
  Brokerage for RENT = 1 month rent (example: if rent is 16k then brokerage is 16k)

FOR BUYING (Purchase Price):
  1 BHK buy = 51 Lakhs (negotiable)
  2 BHK buy = 81 Lakhs (negotiable)
  3 BHK Compact buy = 90 Lakhs (negotiable)
  3 BHK Grande buy = 1 Crore (negotiable)
  Brokerage for BUYING = ZERO. No brokerage for buying.
=== END PRICE TABLE ===

RULES:
1. Keep reply to 1-2 sentences. End with a question.
2. Brokerage is NOT rent. Brokerage is our service fee. For rent it equals 1 month rent. For buy it is zero.
3. Never combine rent and buy prices in one answer.

CONTEXT:
{context_text[:1500] if context_text else "Vanaha Township, Bavdhan, Pune. 12 min from Chellaram Hospital."}

{f'CONVERSATION:' if history_text else ''}
{history_text}

Customer: {incoming_message}
Agent:"""
    
    # Use higher temperature for Gemma2 9B to sound more natural, but keep top_p high for facts
    reply = generate(prompt, max_tokens=100, temperature=0.3)
    print(f"[AI] Generating reply using {DEFAULT_MODEL} for {lead_name}...")
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
