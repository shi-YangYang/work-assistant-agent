"""Manual real-model check using existing public enrollment/held-out samples."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys
import time
import wave

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'packages/voiceprint-engine/src'))
from paa_voiceprints import Extractor, VoiceprintError, MODEL_ID, MATCH_THRESHOLD, MATCH_MARGIN, match


def audio(path):
    import numpy as np
    with wave.open(str(path),'rb') as wav:
        assert (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())==(1,2,16000)
        return np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype(np.float32)/32768


def main():
    import numpy as np
    parser=argparse.ArgumentParser();parser.add_argument('--data',type=Path,default=ROOT/'artifacts/speaker-evaluation');parser.add_argument('--probes',type=Path,help='Separate new-sample manifest; evaluates final split only');parser.add_argument('--output',type=Path,default=ROOT/'artifacts/spec022/voiceprint-evaluation.json');args=parser.parse_args()
    manifest=json.loads((args.data/'manifest.json').read_text())
    began=time.perf_counter();extractor=Extractor(ROOT/'apps/desktop/resources/models/speaker-community-1/embedding/pytorch_model.bin')
    load=time.perf_counter()-began
    profiles=[];enrollment=[]
    for member in manifest['registeredSpeakers']:
        started=time.perf_counter();data=extractor.extract(audio(args.data/f'enrollment-{member}.wav'),minimum=6)
        profiles.append({'memberId':member,'name':member,'templates':data['templates']})
        enrollment.append({'member':member,'speechSeconds':data['speechSeconds'],'templates':len(data['templates']),'seconds':time.perf_counter()-started})
    probes=json.loads(args.probes.read_text()) if args.probes else manifest['clips']
    probe_root=args.probes.parent if args.probes else args.data
    results=[];grouped=defaultdict(list)
    enrolled_sources={x['sourcePath'] for x in manifest['clips'] if x['split']=='enroll'}
    for clip in probes:
        if clip['split']!=('final' if args.probes else 'test'):continue
        assert clip['sourcePath'] not in enrolled_sources
        samples=audio(probe_root/clip['wav']);grouped[clip['speaker']].append(samples)
        started=time.perf_counter()
        try:
            features=extractor.extract(samples)
            found=match(features['templates'],profiles,features['speechSeconds'])
            reason='matched' if found else 'below_threshold_or_ambiguous'
        except VoiceprintError as exc:
            found=None;reason=exc.code
        results.append({'source':clip['sourcePath'],'expected':clip['speaker'] if clip['speaker'] in manifest['registeredSpeakers'] else None,'actual':found['memberId'] if found else None,'reason':reason,'seconds':time.perf_counter()-started,'audioSeconds':len(samples)/16000})
    aggregate=[]
    for member,samples in grouped.items():
        started=time.perf_counter()
        try:
            features=extractor.extract(np.concatenate(samples))
            found=match(features['templates'],profiles,features['speechSeconds'])
            reason='matched' if found else 'below_threshold_or_ambiguous'
        except VoiceprintError as exc:
            found=None;reason=exc.code
        aggregate.append({'expected':member if member in manifest['registeredSpeakers'] else None,'actual':found['memberId'] if found else None,'reason':reason,'seconds':time.perf_counter()-started,'audioSeconds':sum(len(s) for s in samples)/16000})
    def totals(rows):
        known=[r for r in rows if r['expected']];unknown=[r for r in rows if not r['expected']]
        return {'known':len(known),'knownCorrect':sum(r['actual']==r['expected'] for r in known),'knownRejected':sum(r['actual'] is None for r in known),'knownMisidentified':sum(r['actual'] is not None and r['actual']!=r['expected'] for r in known),'unknown':len(unknown),'unknownRejected':sum(r['actual'] is None for r in unknown),'unknownMisidentified':sum(r['actual'] is not None for r in unknown)}
    report={'modelId':MODEL_ID,'threshold':MATCH_THRESHOLD,'margin':MATCH_MARGIN,'device':'CPU','loadSeconds':load,'dataset':manifest['dataset'],'split':'Existing enrollment versus separate final probes; calibration excluded; calibrated threshold frozen before opening final audio. Read speech, not company meeting accuracy.' if args.probes else 'Existing enrollment versus test only. Read speech, not company meeting accuracy.','enrollment':enrollment,'individual':{'totals':totals(results),'samples':results},'accumulatedHeldOutSpeech':{'totals':totals(aggregate),'samples':aggregate}}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'individual':totals(results),'accumulated':totals(aggregate)},ensure_ascii=False))

if __name__=='__main__':main()
