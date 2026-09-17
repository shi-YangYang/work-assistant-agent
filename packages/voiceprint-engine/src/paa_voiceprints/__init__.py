"""Versioned speaker features; imports are cheap and never load model weights."""
import hashlib
import math
import os
from pathlib import Path

MODEL_ID = 'wespeaker-resnet34-lm:6f10ff60898a1d18:pcm16k-v1'
MODEL_SHA256 = '6f10ff60898a1d185fa22e1d11e0bfa8a92efec811f11bca48cb8cafebefd929'
DIMENSION = 256
MAX_TEMPLATES = 12
MAX_PROFILES = 500
# Independent public calibration impostors plus a 0.05 safety gap; new held-out
# validation is separate. Similarities are not probabilities or company accuracy.
MATCH_THRESHOLD = .52
MATCH_MARGIN = .10
MIN_QUERY_SECONDS = 3.0


class VoiceprintError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def unit(vector):
    if len(vector) != DIMENSION or any(type(x) not in (float, int) or not math.isfinite(x) for x in vector):
        raise VoiceprintError('invalid_template', '声纹向量格式无效。')
    norm = math.sqrt(sum(x*x for x in vector))
    if norm < 1e-8:
        raise VoiceprintError('invalid_template', '声纹向量无效。')
    return [float(x / norm) for x in vector]


def validate_profiles(model_id, profiles):
    if model_id != MODEL_ID:
        raise VoiceprintError('model_mismatch', '公司声纹模型版本不兼容，请更新应用或重新登记声纹。')
    if not isinstance(profiles, list) or len(profiles) > MAX_PROFILES:
        raise VoiceprintError('invalid_template', '公司声纹数量超限。')
    result, seen = [], set()
    for item in profiles:
        if not isinstance(item, dict) or set(item) != {'memberId', 'name', 'templates'}:
            raise VoiceprintError('invalid_template', '公司声纹格式无效。')
        member, name, templates = item['memberId'], item['name'], item['templates']
        if not isinstance(member, str) or not 1 <= len(member) <= 128 or member in seen or not isinstance(name, str) or not 1 <= len(name.strip()) <= 100 or any(ord(c)<32 or 127<=ord(c)<160 for c in name):
            raise VoiceprintError('invalid_template', '声纹成员信息无效。')
        if not isinstance(templates, list) or not 1 <= len(templates) <= MAX_TEMPLATES:
            raise VoiceprintError('invalid_template', '声纹模板数量无效。')
        normalized = []
        for vector in templates:
            if not isinstance(vector, list):
                raise VoiceprintError('invalid_template', '声纹向量格式无效。')
            normal = unit(vector)
            if not .98 <= math.sqrt(sum(x*x for x in vector)) <= 1.02:
                raise VoiceprintError('invalid_template', '声纹向量未归一化。')
            normalized.append(normal)
        seen.add(member)
        result.append({'memberId': member, 'name': name.strip(), 'templates': normalized})
    return result


def match(templates, profiles, speech_seconds, *, threshold=MATCH_THRESHOLD, margin=MATCH_MARGIN):
    """Reject short, ambiguous and out-of-library voices; never force a name."""
    if speech_seconds < MIN_QUERY_SECONDS or not templates or not profiles:
        return None
    queries = [unit(t) for t in templates]
    ranked, per_query = [], []
    for profile in profiles:
        # A centroid is less vulnerable to one coincidentally similar short sample.
        center = unit([sum(v[i] for v in profile['templates']) for i in range(DIMENSION)])
        scores = [sum(a*b for a,b in zip(query, center)) for query in queries]
        score = sum(scores) / len(scores)
        ranked.append((score, profile))
        per_query.append((profile['memberId'],scores))
    ranked.sort(key=lambda item: -item[0])
    score, profile = ranked[0]
    runner_up = ranked[1][0] if len(ranked)>1 else -1
    if score < threshold or score-runner_up < margin:
        return None
    # A diarization cluster can accidentally merge a speaker change. Averaging
    # must not let the dominant voice assign its name to the other person's words.
    for index in range(len(queries)):
        own=next(scores[index] for member,scores in per_query if member==profile['memberId'])
        other=max((scores[index] for member,scores in per_query if member!=profile['memberId']),default=-1)
        if own < threshold or own-other < margin:
            return None
    return {'memberId': profile['memberId'], 'name': profile['name'], 'similarity': score}


def isolated_turns(turns):
    """Sweep once over diarization boundaries; never embed overlapping voices."""
    from collections import Counter
    events = sorted((point,delta,label) for start,end,label in turns
                    for point,delta in ((start,1),(end,-1)))
    active, result, previous = Counter(), {}, None
    for point,delta,label in events:
        if previous is not None and point>previous and len(active)==1:
            owner=next(iter(active))
            spans=result.setdefault(owner,[])
            if spans and spans[-1][1]==previous:
                spans[-1]=(spans[-1][0],point)
            else:
                spans.append((previous,point))
        active[label]+=delta
        if active[label]==0:del active[label]
        previous=point
    return result


def model_file(path=None):
    value = path or os.environ.get('PAA_VOICEPRINT_MODEL')
    if value is None:
        value = Path(__file__).resolve().parents[4] / 'apps/desktop/resources/models/speaker-community-1/embedding/pytorch_model.bin'
    value = Path(value)
    try:
        if value.is_symlink() or not value.is_file() or value.stat().st_size > 50_000_000:
            raise OSError()
        with value.open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() != MODEL_SHA256:
                raise OSError()
    except OSError:
        raise VoiceprintError('model_unavailable', '声纹模型缺失或校验失败，请检查部署。') from None
    return value


class Extractor:
    def __init__(self, model_path=None, device='cpu'):
        path = model_file(model_path)
        os.environ['PYANNOTE_METRICS_ENABLED'] = '0'
        os.environ['HF_HUB_OFFLINE'] = '1'
        import torch
        from pyannote.audio import Model
        torch.set_num_threads(2)
        self.device = torch.device(device)
        self.model = Model.from_pretrained(str(path), map_location='cpu').eval().to(self.device)
        if self.model.dimension != DIMENSION:
            raise VoiceprintError('model_unavailable', '声纹模型维数不兼容。')

    def extract(self, waveform, *, minimum=MIN_QUERY_SECONDS):
        import numpy as np
        import torch
        audio = np.asarray(waveform, dtype=np.float32).reshape(-1)
        if not np.isfinite(audio).all() or len(audio) > 180*16000:
            raise VoiceprintError('audio_duration', '单次声纹音频最长 3 分钟。')
        # Remove long silence consistently in enrollment and meeting matching.
        frame = 480
        voiced = [audio[i:i+frame] for i in range(0, len(audio), frame)
                  if len(audio[i:i+frame]) == frame and np.sqrt(np.mean(audio[i:i+frame]**2)) >= .003]
        speech = np.concatenate(voiced) if voiced else np.empty(0, np.float32)
        seconds = len(speech)/16000
        if seconds < minimum:
            raise VoiceprintError('audio_quality', '有效声音不足，请上传更清晰且至少含 6 秒发言的单人录音。')
        templates = []
        count = min(MAX_TEMPLATES, max(1, int(seconds//6)))
        with torch.inference_mode():
            for start in np.linspace(0, max(0, len(speech)-6*16000), count, dtype=int):
                part = speech[start:start+6*16000]
                result = self.model(torch.from_numpy(part).reshape(1,1,-1).to(self.device))
                templates.append(unit(result[0].detach().cpu().tolist()))
        return {'modelId': MODEL_ID, 'templates': templates, 'speechSeconds': round(seconds,3)}


def extract_file(path, model_path=None):
    import wave
    import numpy as np
    try:
        with wave.open(str(path), 'rb') as wav:
            if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate()) != (1,2,16000):
                raise VoiceprintError('audio_format', '声纹音频需要单声道 16kHz PCM WAV。')
            if not 6*16000 <= wav.getnframes() <= 180*16000:
                raise VoiceprintError('audio_duration', '登记录音长度应为 6 秒至 3 分钟。')
            data = wav.readframes(wav.getnframes())
    except (OSError, wave.Error, EOFError):
        raise VoiceprintError('audio_format', '无法读取声纹音频，请重新上传。') from None
    return Extractor(model_path).extract(np.frombuffer(data,dtype='<i2').astype(np.float32)/32768,minimum=6)
