"""
AI module - Ollama integration with Phi-3 mini.
Generates auto-replies, follow-up messages, and lead summaries.
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


def generate(prompt: str, model: str = DEFAULT_MODEL, max_tokens: int = 300) -> str:
    """
    Generate text using Ollama.
    Keeps prompts short for low RAM usage.
    """
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "num_ctx": 1024,  # Small context window for RAM savings
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
