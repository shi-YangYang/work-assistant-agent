import argparse
import contextlib
import json
import sys
from . import VoiceprintError, extract_file

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('audio')
    parser.add_argument('--model')
    args=parser.parse_args()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result=extract_file(args.audio, args.model)
    except VoiceprintError as exc:
        print(json.dumps({'error': {'code':exc.code, 'message':str(exc)}},ensure_ascii=False))
        return 2
    except Exception:
        print(json.dumps({'error': {'code':'inference_failed','message':'声纹提取失败，请检查推理依赖和录音后重试。'}},ensure_ascii=False))
        return 2
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    return 0

if __name__=='__main__':
    sys.exit(main())
