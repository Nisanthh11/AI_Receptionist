"""Diagnostic script to verify real Google Gemini API connectivity and API key validity.
DO NOT expose or print the API key or secret credentials.
"""
import sys
import os
import re

# Add backend directory to sys.path so app packages can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import get_settings
from google import genai
from google.genai import types
from google.genai.errors import APIError


def mask_key(key: str | None) -> str:
    if not key:
        return "[NOT SET]"
    s = key.strip()
    if len(s) < 8:
        return f"[SET, length={len(s)}]"
    return f"{s[:3]}...{s[-3:]} (length={len(s)})"


def run_diagnostics():
    print("=" * 60)
    print("GOOGLE GEMINI API LIVE CONNECTIVITY DIAGNOSTICS")
    print("=" * 60)

    settings = get_settings()
    api_key = settings.gemini_api_key
    enabled = settings.gemini_enabled
    model = settings.gemini_model
    timeout = max(30, settings.gemini_timeout_seconds)

    print(f"GEMINI_ENABLED in .env      : {enabled}")
    print(f"GEMINI_MODEL in .env        : {model}")
    print(f"GEMINI_TIMEOUT_SECONDS      : {timeout}s")
    print(f"GEMINI_API_KEY Configured   : {'Yes' if api_key and len(api_key.strip()) > 5 else 'No'}")
    print(f"Key Format / Masked Info    : {mask_key(api_key)}")
    print("-" * 60)

    if not api_key or len(api_key.strip()) <= 5 or api_key.startswith("REPLACE_WITH"):
        print("RESULT: FAILED - API Key is missing or contains placeholder.")
        print("Category: API key missing or not loaded.")
        print("Fix: Add a valid Google Gemini API key to backend/.env under GEMINI_API_KEY.")
        return False

    # Attempt direct real API test with the configured model
    print(f"Initiating live request to model '{model}' via google-genai SDK...")
    client = None
    try:
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),
        )
    except Exception as e:
        print(f"RESULT: FAILED - Client Initialization Error")
        print(f"Category: Initialization failure ({type(e).__name__})")
        print(f"Detail: {e}")
        return False

    prompt = "Respond with: Gemini API connection successful"
    models_to_try = [model]
    # If the configured model is not gemini-2.0-flash, add it as a backup attempt if model is not found
    if model != "gemini-2.0-flash":
        models_to_try.append("gemini-2.0-flash")

    last_error_category = None
    last_error_detail = None

    for idx, test_model in enumerate(models_to_try):
        if idx > 0:
            print(f"\nAttempting fallback model check with '{test_model}'...")
        try:
            response = client.models.generate_content(
                model=test_model,
                contents=prompt,
            )
            response_text = response.text.strip() if response and response.text else "[EMPTY RESPONSE]"
            # Sanitize response text so it never contains the key
            if api_key in response_text:
                response_text = response_text.replace(api_key, "[REDACTED]")

            print("\n" + "=" * 60)
            print("CONNECTIVITY TEST RESULT: SUCCESS")
            print("=" * 60)
            print(f"Model used              : {test_model}")
            print(f"Response from Google    : {response_text}")
            print(f"Status                  : Confirmed genuine response received from Google Gemini API.")
            return True

        except APIError as api_err:
            status_code = getattr(api_err, "code", None)
            err_msg = str(api_err)
            # Redact key if it somehow appears in error message
            if api_key in err_msg:
                err_msg = err_msg.replace(api_key, "[REDACTED]")

            print(f"\nAPI Error received (HTTP Status: {status_code}):")
            print(f"Error Message: {err_msg}")

            if status_code in (401, 403) or "API_KEY_INVALID" in err_msg or "INVALID_ARGUMENT" in err_msg and "key" in err_msg.lower():
                last_error_category = "Invalid API key or authentication failure"
                print(f"Category: {last_error_category}")
                print("Explanation: The API key was rejected by Google as invalid or unauthorized.")
                break  # No point in trying other models if key is invalid

            elif status_code == 404 or "NOT_FOUND" in err_msg or "models/" in err_msg and "not found" in err_msg.lower():
                last_error_category = "Model not found or unsupported"
                print(f"Category: {last_error_category}")
                print(f"Explanation: Model '{test_model}' is not available for this API key or is deprecated/renamed.")
                continue  # Try next model if available

            elif status_code == 429 or "RESOURCE_EXHAUSTED" in err_msg or "quota" in err_msg.lower():
                last_error_category = "Quota exceeded or rate limit reached"
                print(f"Category: {last_error_category}")
                print("Explanation: Rate limit or free tier quota limit reached on Google AI Studio.")
                break

            else:
                last_error_category = f"Other Google API error (HTTP {status_code})"
                print(f"Category: {last_error_category}")
                break

        except Exception as exc:
            exc_name = type(exc).__name__
            err_msg = str(exc)
            if api_key in err_msg:
                err_msg = err_msg.replace(api_key, "[REDACTED]")

            print(f"\nException ({exc_name}): {err_msg}")
            if "timeout" in exc_name.lower() or "timeout" in err_msg.lower():
                last_error_category = "Network, DNS, timeout, or connection failure"
                print(f"Category: {last_error_category}")
            else:
                last_error_category = f"Unexpected Error: {exc_name}"
                print(f"Category: {last_error_category}")
            break

    print("\n" + "=" * 60)
    print("CONNECTIVITY TEST RESULT: FAILED")
    print("=" * 60)
    print(f"Failure Category: {last_error_category}")
    return False


if __name__ == "__main__":
    success = run_diagnostics()
    sys.exit(0 if success else 1)
