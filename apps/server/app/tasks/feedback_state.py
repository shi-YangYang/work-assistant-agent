from app.db.base import now

STAGES = frozenset({'queued', 'preparing', 'parsing', 'transcribing', 'searching', 'generating', 'operating', 'reviewing', 'complete'})


def update_feedback(job, stage=None, text=None, call_id=None):
    old = job.feedback or {}
    job.feedback = {'seq':old.get('seq',0)+1, 'stage':stage if stage in STAGES else old.get('stage','queued'), 'text':(text if text is not None else old.get('text',''))[:16000], 'callId':call_id if call_id is not None else old.get('callId')}
    job.updated_at = now()
