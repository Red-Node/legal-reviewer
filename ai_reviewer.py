"""Preparation for future Claude calls; the PDF application does not call this module."""

import os
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv


DEFAULT_MODEL = "claude-sonnet-5-5"


def _read_configuration():
    """Load local settings without replacing existing environment variables."""
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if api_key == "your_key_here":
        api_key = ""
    model = os.getenv("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODEL
    return api_key, model


def get_configuration_status():
    """Report presence only: this never contacts Anthropic or returns the key."""
    api_key, model = _read_configuration()
    return {"api_key_configured": bool(api_key), "model": model}


def send_text_to_claude(text):
    """Future API entry point. Calling this with a real key makes a paid request.

    This function is deliberately not connected to uploads or the webpage.
    In this milestone it is exercised only with a mocked SDK client.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Provide non-empty text.")
    api_key, model = _read_configuration()
    if not api_key:
        raise ValueError("Set ANTHROPIC_API_KEY before using the Claude function.")

    with Anthropic(api_key=api_key) as client:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": text}],
        )
    return "\n".join(block.text for block in response.content if block.type == "text")
