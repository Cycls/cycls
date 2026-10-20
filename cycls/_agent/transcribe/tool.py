"""The Transcribe tool as the model is given it: one call, a recording's path, its words back."""

AUDIO_TYPES = {"mp3", "wav", "m4a", "ogg", "oga", "opus", "webm", "flac", "aac", "amr", "caf", "aif", "aiff",
               "mp4", "m4v", "mov", "mkv", "3gp"}
LANGUAGES = ("auto", "ar", "en")

TRANSCRIBE_TOOL = {
    "type": "custom",
    "name": "transcribe",
    "description": (
        "Transcribe: write down what is said in a recording in the workspace — a voice note, a phone call, a "
        "meeting, a lecture, an interview, or the sound of a video (mp3, wav, m4a, ogg, opus, webm, flac, aac, "
        "mp4, mov; up to 512 MB and 3 hours). Strong on Arabic, Gulf dialects included, and on English; other "
        "languages work too. The reply is the transcript with a [mm:ss] mark at each paragraph, and who speaks "
        "(Speaker 1, Speaker 2…) when several voices are told apart; it is also saved beside the recording as <name>.transcript.md (to read, quote, summarise or translate) and "
        "<name>.words.json (every word timed). Use it whenever the person attaches or names audio and wants to "
        "know, use or keep what is said: then summarise, translate, write minutes or answer from the transcript "
        "as they asked. A recording already transcribed comes back at once. A long recording takes a minute or "
        "two: if the reply says it is still transcribing, call again with the same path. The words are a "
        "machine's: names, numbers and dialect words can be misheard — say so where it matters."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "The recording's path in the workspace."},
            "language": {"type": "string", "enum": list(LANGUAGES),
                         "description": "The main language spoken: ar (any Arabic, dialects included, also when "
                                        "English words are mixed in), en, or auto (the default) to have it found."},
            "fresh": {"type": "boolean",
                      "description": "Transcribe again even if a transcript is saved (e.g. it was heard in the "
                                     "wrong language). Leave out otherwise."},
            "names": {"type": "array", "items": {"type": "string"},
                      "description": "Names and terms likely said in it — people, companies, places, products — from "
                                     "the chat, the file name or what the person told you, so they come out spelled "
                                     "right (each under 50 characters; up to 100). Leave out when there are none."},
            "speakers": {"type": "object", "additionalProperties": {"type": "string"},
                         "description": "Who each voice is, e.g. {\"1\": \"Khalfan\", \"2\": \"Sara\"}: renames "
                                        "Speaker 1, Speaker 2… in the saved transcript without hearing it again. Only "
                                        "when the person said so, or the transcript makes it plain (they name each "
                                        "other)."},
        },
        "required": ["path"],
    },
}


def transcribe_step(inp):
    return {"tool_name": "Transcribing", "step": str(inp.get("path") or "")}
