"""Only explicit user text and recorded voice can authorize business effects."""
from app.modules.messages.audio import transcript_groups


def request_text(message, job):
    # The API records this explicit client choice only for an attached audio.
    # Uploaded audio remains reference material; transcript corrections keep the choice.
    voice, _ = transcript_groups(message.transcript, job.result if job else {})
    return '\n'.join(part for part in (message.text, voice) if part.strip())

