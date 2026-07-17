from app.services.ai_copilot import format_suggestion_payload


def test_format_suggestion_payload_returns_renderable_texts_and_details():
    payload = format_suggestion_payload(
        [
            {
                "text": "您好，请问需要了解哪方面？",
                "style": "professional",
                "confidence": 0.9,
            },
            {
                "text": "好的，我马上帮您确认。",
                "style": "friendly",
                "confidence": 0.8,
            },
        ]
    )

    assert payload["suggestions"] == [
        "您好，请问需要了解哪方面？",
        "好的，我马上帮您确认。",
    ]
    assert payload["replies"] == payload["suggestions"]
    assert payload["reply"].startswith("1. 您好")
    assert payload["suggestion_details"][0]["style"] == "professional"
