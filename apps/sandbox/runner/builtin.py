"""Fixed structured dispatcher. Task data is never interpolated into code."""
import json
from pathlib import Path
import sys
from noria_tools import TOOLS
from noria_tools.common.results import result


def main():
    try:
        task = json.load(sys.stdin)
        if set(task) != {'kind', 'name', 'version', 'arguments'} or task['kind'] != 'builtin' or task['version'] != 1 or task['name'] not in TOOLS:
            raise ValueError('内置工具协议不支持，请更新沙盒镜像')
        value = TOOLS[task['name']](**task['arguments'])
        result(value['data'], value['warnings'])
        Path('/work/builtin-result.json').write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    except Exception as error:
        print(f'{type(error).__name__}: {str(error)[:1000]}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
