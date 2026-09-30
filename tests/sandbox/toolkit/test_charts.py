from pathlib import Path
from unittest.mock import patch
from PIL import Image
from support import Workspace
from noria_tools import create_chart


class Charts(Workspace):
    def render_and_inspect(self, **arguments):
        from matplotlib.figure import Figure
        savefig = Figure.savefig
        captured = {}

        def inspect(figure, *args, **kwargs):
            renderer = figure.canvas.get_renderer()
            axis = figure.axes[0]
            texts = [axis.title, axis.xaxis.label, axis.yaxis.label, *axis.get_legend().get_texts()]
            for coordinate in (axis.xaxis, axis.yaxis):
                texts.extend(tick.label1 for tick in coordinate._update_ticks())
            for text in texts:
                if text.get_visible() and text.get_text():
                    box = text.get_window_extent(renderer)
                    self.assertGreaterEqual(box.x0, 0)
                    self.assertGreaterEqual(box.y0, 0)
                    self.assertLessEqual(box.x1, figure.bbox.width)
                    self.assertLessEqual(box.y1, figure.bbox.height)
            captured.update(title=axis.title.get_text(), x_label=axis.xaxis.label.get_text(),
                            y_label=axis.yaxis.label.get_text(), labels=[label.get_text() for label in axis.get_xticklabels()],
                            legend=[label.get_text() for label in axis.get_legend().get_texts()])
            return savefig(figure, *args, **kwargs)

        with patch.object(Figure, 'savefig', inspect):
            create_chart(**arguments)
        return captured

    def test_chinese_bar_and_line_are_readable_images(self):
        data = {'columns': ['月份', '销售额'], 'rows': [['一月', 10], ['二月', 20]]}
        for kind in ('bar', 'line'):
            value = create_chart(filename=kind + '.png', kind=kind, x='月份', y=['销售额'], data=data, title='中文销售趋势', y_label='万元')
            self.assertEqual(value['data']['rowCount'], 2)
            with Image.open('output/' + kind + '.png') as image:
                self.assertGreater(image.width, 800)
                image.verify()

    def test_175_character_title_wraps_without_losing_text_or_crossing_canvas(self):
        title = '中文销售趋势和经营目标' * 15 + '补充说明如下'
        title = (title + '保留全部内容')[:175]
        self.assertEqual(len(title), 175)
        captured = self.render_and_inspect(filename='long-title.png', x='月份', y=['销售额'], title=title,
                                           data={'columns': ['月份', '销售额'], 'rows': [['一月', 10], ['二月', 20]]})
        self.assertIn('\n', captured['title'])
        self.assertEqual(captured['title'].replace('\n', ''), title)

    def test_axis_legend_and_category_labels_wrap_without_losing_text(self):
        series = '保留原始统计指标名称' * 4
        labels = ['华东区域重点客户第一组销售统计', '华南区域重点客户第二组销售统计']
        x_label, y_label = '保留横轴分类口径说明' * 4, '保留纵轴数值口径说明' * 4
        captured = self.render_and_inspect(filename='labels.png', kind='line', x='类别', y=[series],
                                           x_label=x_label, y_label=y_label,
                                           data={'columns': ['类别', series], 'rows': [[labels[0], 10], [labels[1], 20]]})
        for field, expected in [('x_label', x_label), ('y_label', y_label)]:
            self.assertIn('\n', captured[field])
            self.assertEqual(captured[field].replace('\n', ''), expected)
        self.assertIn('\n', captured['legend'][0])
        self.assertEqual(captured['legend'][0].replace('\n', ''), series)
        self.assertEqual([label.replace('\n', '') for label in captured['labels']], labels)
        self.assertTrue(all('\n' in label for label in captured['labels']))

    def test_overfull_legend_or_category_labels_fail_without_publishing_files(self):
        series = ['统计指标说明' * 19 + str(index) for index in range(6)]
        with self.assertRaisesRegex(ValueError, '画布|图例|布局'):
            create_chart(filename='legend.png', x='类别', y=series,
                         data={'columns': ['类别', *series], 'rows': [['一月', *range(6)], ['二月', *range(6)]]})
        with self.assertRaisesRegex(ValueError, '画布|标签'):
            create_chart(filename='categories.png', x='类别', y=['值'], title='六十个类别',
                         data={'columns': ['类别', '值'], 'rows': [['过长类别说明' * 4 + str(index), index] for index in range(60)]})
        self.assertFalse(list(Path('output').iterdir()))

    def test_missing_duplicate_invalid_values_and_columns_fail_without_files(self):
        for rows, y in [([['一', None]], ['值']), ([['一', 'bad']], ['值']), ([['一', 1], ['一', 2]], ['值']), ([['一', 1]], ['missing'])]:
            with self.assertRaises(ValueError):
                create_chart(filename='bad.png', x='类别', y=y, data={'columns': ['类别', '值'], 'rows': rows})
        self.assertFalse(list(Path('output').iterdir()))
