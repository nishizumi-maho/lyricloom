from lyricloom.stages.assemblyai import build_request, parse_transcript

RESPONSE = {
    "status": "completed",
    "language_code": "pt",
    "speech_model_used": "universal-3-5-pro",
    "text": "Texto inventado para o teste",
    "words": [
        {"text": "Texto", "start": 22600, "end": 22820, "confidence": 0.98},
        {"text": "inventado", "start": 22820, "end": 23140, "confidence": 0.91},
        {"text": "para", "start": 23140, "end": 23560, "confidence": 0.87},
        {"text": "o", "start": 23560, "end": 23800, "confidence": 0.93},
        {"text": "teste", "start": 23800, "end": 24180, "confidence": 0.95},
    ],
}


def test_parse_words_times_and_confidence():
    t = parse_transcript(RESPONSE)
    assert t.lang == "pt"
    assert [w.text for w in t.words] == ["Texto", "inventado", "para", "o", "teste"]
    assert (t.words[0].start_ms, t.words[0].end_ms, t.words[0].prob) == (22600, 22820, 0.98)


def test_markup_tags_are_stripped_from_words():
    data = {"language_code": "pt", "words": [
        {"text": "<LYRICS>Texto", "start": 0, "end": 100, "confidence": 0.9},
        {"text": "inventado...</LYRICS>", "start": 100, "end": 200, "confidence": 0.9},
        {"text": "</LYRICS>", "start": 200, "end": 210, "confidence": 0.9},
    ]}
    assert [w.text for w in parse_transcript(data).words] == ["Texto", "inventado..."]


def test_portuguese_uses_the_pro_model_with_a_prompt():
    r = build_request("https://cdn/x", "pt", "Test Artist - Synthetic Song (Test Version)")
    assert r["speech_models"] == ["universal-3-5-pro"]
    assert r["language_code"] == "pt"
    assert "Test Artist - Synthetic Song" in r["prompt"]


def test_japanese_falls_back_to_universal_2_without_prompt():
    r = build_request("https://cdn/x", "ja", "テスト歌手 - Synthetic Song")
    assert r["speech_models"] == ["universal-2"]
    assert r["language_code"] == "ja"
    assert "prompt" not in r
