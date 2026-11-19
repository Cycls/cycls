"""A video the person shows to say "make one like this": read by the service, told to the agent to rebuild, never used."""
from cycls._agent.video import report

READING = {"summary": "A café reel: steam, a pour, the offer, the logo.", "hook": "Steam rising over a cup.", "pace": "fast",
           "style": "warm serif on cream", "palette": ["#3b2a1e", "#f4e7d3"], "brand": "Some Café", "closest_look": "warm",
           "duration": 9.5, "width": 1080, "height": 1920,
           "shots": [{"shot": 1, "start": 0, "end": 1.5, "role": "hook", "kind": "footage", "on_screen": "",
                      "picture": "a cup", "layout": "full frame", "motion": "push in"},
                     {"shot": 2, "start": 1.5, "end": 4, "role": "offer", "kind": "graphic", "on_screen": "خصم 20%",
                      "picture": "", "layout": "centred", "motion": "words rise"}]}


def test_a_reference_is_told_as_structure_to_rebuild_and_never_to_use():
    text = report.reference_text("uploads/ref.mp4", READING, {"transcript": {"sentences": [{"text": "Wake up to better coffee."}]}})
    assert "REFERENCE" in text and "never put it" in text
    assert "1. 0.0–1.5 s · hook · footage" in text and "on screen «خصم 20%»" in text
    assert "start from the warm look" in text and "Some Café" in text and "replace every sign of it" in text
    assert "Wake up to better coffee." in text
