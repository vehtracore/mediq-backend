"""Install SDK-shaped model doubles behind the provider boundary."""

import json

from app.services.gemini_adapter import GeminiAdapter


def scope_payload(text="This information does not establish a diagnosis.", *, sentence_id=None):
    point = {"text": text, "evidence_sentence_ids": [sentence_id]} if sentence_id else None
    return {"supported_points": [point] if point else [], "next_steps": [],
            "warning_points": [], "not_established": [] if point else [text]}


def scope_json(text="This information does not establish a diagnosis.", *, sentence_id=None):
    return json.dumps(scope_payload(text, sentence_id=sentence_id))


def install_model(monkeypatch, consumer_module, purpose, model):
    adapter = GeminiAdapter.__new__(GeminiAdapter)
    adapter.api_key = "test-key"
    adapter.model_names = {
        "standard": "test-standard", "heavy": "test-heavy",
        "summary": "test-heavy", "lab": "test-heavy",
        "router": "test-heavy",
    }
    adapter.models = {key: model for key in adapter.model_names}
    monkeypatch.setattr(consumer_module, "get_clinical_ai_provider", lambda: adapter)
    return adapter
