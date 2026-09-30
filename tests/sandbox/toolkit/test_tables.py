import csv
import json
from pathlib import Path
from openpyxl import load_workbook, Workbook
from support import Workspace
from noria_tools import inspect_table, export_table


class Tables(Workspace):
    def test_inspection_preserves_zeroes_missing_duplicate_and_sample_bounds(self):
        Path('inputs/数据.csv').write_text('账号,数量\n001,2\n001,2\n002,\n', encoding='utf-8')
        result = inspect_table(source={'input': '数据.csv', 'column_types': {'数量': 'number'}}, sample_rows=1)
        data = result['data']
        self.assertEqual(data['rowCount'], 3)
        self.assertEqual(data['sample'], [['001', 2]])
        self.assertEqual(data['duplicateRows'], 1)
        self.assertEqual(data['columns'][1]['missing'], 1)
        self.assertTrue(data['sampleTruncated'])
        self.assertFalse(list(Path('output').iterdir()))

    def test_exports_literal_formula_strings_and_empty_table(self):
        data = {'columns': ['编号', '说明'], 'rows': [['001', '=SUM(1,2)'], ['002', '中文']]}
        export_table(filename='结果.xlsx', data=data)
        book = load_workbook('output/结果.xlsx')
        self.assertEqual(book.active['A2'].value, '001')
        self.assertEqual(book.active['B2'].data_type, 's')
        self.assertEqual(book.active['B2'].value, '=SUM(1,2)')
        self.assertEqual(book.active.freeze_panes, 'A2'); book.close()
        value = export_table(filename='结果.csv', format='csv', data=data)
        with Path('output/结果.csv').open(encoding='utf-8-sig', newline='') as file:
            rows = list(csv.reader(file))
        self.assertEqual(rows[1][1], "'=SUM(1,2)")
        self.assertTrue(value['warnings'])
        empty = export_table(filename='空表.csv', format='csv', data={'columns': ['名称'], 'rows': []})
        self.assertEqual(empty['data']['rowCount'], 0)

    def test_bad_encoding_type_column_shape_are_not_silently_repaired(self):
        Path('inputs/bad.csv').write_bytes(b'name\n\xff')
        with self.assertRaises(UnicodeError):
            inspect_table(source={'input': 'bad.csv'})
        Path('inputs/bad.csv').write_text('a,b\n1\n')
        with self.assertRaises(ValueError):
            inspect_table(source={'input': 'bad.csv'})
        Path('inputs/bad.csv').write_text('a\nhello\n')
        for types in ({'a': 'number'}, {'missing': 'string'}):
            with self.assertRaises(ValueError):
                inspect_table(source={'input': 'bad.csv', 'column_types': types})

    def test_xlsx_sheet_selection_and_formula_not_calculated(self):
        book = Workbook(); book.active.title = '忽略'
        sheet = book.create_sheet('选中'); sheet.append(['编号', '公式']); sheet.append(['001', '=1+2'])
        book.save('inputs/data.xlsx')
        value = inspect_table(source={'input': 'data.xlsx', 'sheet': '选中'})
        self.assertEqual(value['data']['sample'], [['001', '=1+2']])
        self.assertTrue(value['warnings'])
        with self.assertRaises(ValueError):
            inspect_table(source={'input': 'data.xlsx', 'sheet': '不存在'})

    def test_large_samples_have_explicit_truncation_and_valid_json(self):
        with Path('inputs/wide.csv').open('w', newline='') as file:
            writer = csv.writer(file); writer.writerow([f'列{i}' for i in range(40)])
            writer.writerows([['字' * 1900] * 40 for _ in range(3)])
        value = inspect_table(source={'input': 'wide.csv'}, sample_rows=20)
        self.assertTrue(value['data']['sampleTruncated'])
        self.assertLessEqual(len(json.dumps(value, ensure_ascii=False).encode()), 65536)

    def test_explicit_numeric_conversion_and_excel_keep_large_integers(self):
        Path('inputs/large.csv').write_text('number\n9007199254740993\n')
        inspected = inspect_table(source={'input': 'large.csv', 'column_types': {'number': 'number'}})
        self.assertEqual(inspected['data']['sample'], [[9007199254740993]])
        exported = export_table(filename='large.xlsx', data={'columns': ['number'], 'rows': [[9007199254740993]]})
        book = load_workbook('output/large.xlsx')
        self.assertEqual(book.active['A2'].value, '9007199254740993')
        self.assertEqual(book.active['A2'].data_type, 's')
        self.assertTrue(exported['warnings']); book.close()
        with self.assertRaisesRegex(ValueError, 'CSV没有工作表'):
            inspect_table(source={'input': 'large.csv', 'sheet': 'ignored'})
