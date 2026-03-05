"""
Auth — Google Gemini API authentication helper.

Supports:
  1. API Key (via GOOGLE_API_KEY env var)
  2. Application Default Credentials (ADC) via gcloud CLI
"""
import os
import logging

logger = logging.getLogger(__name__)


def create_genai_client():
    """
    Create and return a google.genai.Client using the best
    available authentication method.

    Priority:
      1. GOOGLE_API_KEY environment variable
      2. Application Default Credentials (ADC)
    """
    from google import genai

    api_key = os.getenv("GOOGLE_API_KEY", "").strip()

    if api_key:
        logger.info("Using API Key authentication for Gemini")
        return genai.Client(api_key=api_key)

    # Fall back to ADC (gcloud auth application-default login)
    logger.info("Using Application Default Credentials (ADC) for Gemini")
    return genai.Client()
