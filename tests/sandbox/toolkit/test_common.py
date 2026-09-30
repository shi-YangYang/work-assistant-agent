from pathlib import Path
from unittest.mock import patch
from support import Workspace
from noria_tools.common.paths import output_file, input_path
from noria_tools.contracts import validate
from noria_tools.common.results import result


class Boundaries(Workspace):
    def test_traversal_links_and_missing_files(self):
        for value in ('../secret.csv', '/secret.csv', 'a\\b.csv', '.', '..', 'bad\x00.csv'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                input_path(value, {'.csv'})
        Path('inputs/link.csv').symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):
            input_path('link.csv', {'.csv'})
        with self.assertRaises(ValueError):
            input_path('missing.csv', {'.csv'})

    def test_failed_atomic_export_and_no_silent_overwrite(self):
        with self.assertRaisesRegex(ValueError, 'stop'):
            with output_file('结果.txt', '.txt') as path:
                path.write_text('partial')
                raise ValueError('stop')
        self.assertFalse(list(Path('output').iterdir()))
        self.assertFalse(list(Path('tmp').iterdir()))
        with output_file('结果.txt', '.txt') as path:
            path.write_text('original')
        with self.assertRaises(ValueError):
            with output_file('结果.txt', '.txt'):
                pass
        self.assertEqual(Path('output/结果.txt').read_text(), 'original')

    def test_schema_rejects_code_unknown_fields_and_wrong_shapes(self):
        samples = [('unknown', {}), ('inspect_table', {'source': {'input': 'a.csv'}, 'code': 'print(1)'}),
                   ('export_table', {'filename': 'a.csv', 'data': {'columns': ['a'], 'rows': [[1, 2]]}}),
                   ('create_document', {'filename': 'x.pdf', 'title': 'x', 'blocks': [{'type': 'paragraph', 'text': 'x', 'items': ['lost']}]})]
        for name, args in samples:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate(name, args)
        with self.assertRaises(ValueError):
            result({'oversized': '汉' * 30000})

    def test_missing_font_is_explicit(self):
        from noria_tools.common.fonts import require_font
        with patch('noria_tools.common.fonts.FONT_PATH', Path('/missing/font.ttc')), self.assertRaisesRegex(ValueError, '中文字体'):
            require_font()
