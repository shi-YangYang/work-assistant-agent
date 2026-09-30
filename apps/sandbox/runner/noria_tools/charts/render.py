from ..tables.io import read_table, _number
from ..common.paths import output_file
from ..common.fonts import require_font
from ..common.results import result


def wrap_text(value, renderer, font, width):
    """Wrap by measured glyph width, retaining every character and explicit line break."""
    lines = []
    for paragraph in value.split('\n'):
        line = ''
        for character in paragraph:
            if line and renderer.get_text_width_height_descent(line + character, font, ismath=False)[0] > width:
                lines.append(line)
                line = ''
            line += character
        lines.append(line)
    return '\n'.join(lines)


def check_layout(fig, ax, legend):
    """Reject an overfull fixed canvas before publishing any output."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    canvas = fig.bbox
    if ax.bbox.width < fig.dpi * 2 or ax.bbox.height < fig.dpi * 1.5:
        raise ValueError('图表文字超出固定画布容量，请缩短标题、坐标标签或图例，或使用Python自定义布局')
    texts = [ax.title, ax.xaxis.label, ax.yaxis.label, ax.xaxis.offsetText, ax.yaxis.offsetText, *legend.get_texts()]
    for axis in (ax.xaxis, ax.yaxis):
        lower, upper = sorted(axis.get_view_interval())
        # Matplotlib also allocates labels outside the view interval; those are not drawn.
        for tick in [*axis.get_major_ticks(), *axis.get_minor_ticks()]:
            if lower <= tick.get_loc() <= upper:
                texts.extend((tick.label1, tick.label2))
    boxes = []
    for text in texts:
        if not text.get_visible() or not text.get_text():
            continue
        box = text.get_window_extent(renderer)
        if box.x0 < 0 or box.y0 < 0 or box.x1 > canvas.width or box.y1 > canvas.height:
            raise ValueError('图表文字超出固定画布边界，请缩短标题、坐标标签、图例或类别文字')
        if any(box.overlaps(other) for other in boxes):
            raise ValueError('图表文字在固定画布中重叠，请缩短标签或减少类别、数值列')
        boxes.append(box)
    legend_box = legend.get_window_extent(renderer)
    if legend_box.overlaps(ax.bbox):
        raise ValueError('图例超出固定布局容量，请缩短图例或减少数值列')
    # Save exactly the layout checked at the output DPI, without a second layout pass.
    fig.set_layout_engine('none')


def create_chart(*, filename, x, y, data=None, source=None, kind='bar', title='', x_label='', y_label=''):
    columns, rows, warnings = read_table(data, source)
    if not rows or len(rows) > 60:
        raise ValueError('图表需要1至60行；请先明确汇总口径或用Python处理更复杂图表')
    if any(column not in columns for column in [x, *y]):
        raise ValueError('图表引用的列不存在')
    labels = [str(row[columns.index(x)]) if row[columns.index(x)] is not None else '' for row in rows]
    if any(not label or len(label) > 30 for label in labels):
        raise ValueError('横轴标签不能为空或超过30字；请先提供简短标签')
    if len(set(labels)) != len(labels):
        raise ValueError('横轴类别重复，请先明确分组或汇总规则，工具不自动聚合')
    numbers = [[_number(row[columns.index(column)]) for row in rows] for column in y]
    if any(value is None for series in numbers for value in series):
        raise ValueError('数值列有空值，未擅自补零或丢弃行')
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    from matplotlib.font_manager import FontProperties
    font = FontProperties(fname=require_font())
    plt.rcParams['axes.unicode_minus'] = False
    fig, ax = plt.subplots(figsize=(max(8, min(16, len(rows) * .4)), 6), dpi=150, layout='constrained')
    colors = ['#333333', '#666666', '#909090', '#b0b0b0', '#484848', '#787878']
    try:
        renderer = fig.canvas.get_renderer()
        title_font = FontProperties(fname=require_font(), size=16)
        label_width = fig.bbox.width * .58
        legend_width = fig.bbox.width * .2
        category_width = min(120, label_width / len(rows))
        wrapped_labels = [wrap_text(label, renderer, font, category_width) for label in labels]
        positions = list(range(len(rows)))
        for index, (column, values) in enumerate(zip(y, numbers, strict=True)):
            legend_label = wrap_text(column, renderer, font, legend_width)
            if kind == 'bar':
                width = .8 / len(y)
                ax.bar([value - .4 + width * (index + .5) for value in positions], values, width=width, label=legend_label, color=colors[index])
            else:
                ax.plot(positions, values, marker='o', markersize=4, linewidth=1.7, label=legend_label, color=colors[index], linestyle=['-', '--', '-.', ':', '-', '--'][index])
        ax.set_xticks(positions, wrapped_labels, fontproperties=font, parse_math=False)
        ax.set_title(wrap_text(title, renderer, title_font, label_width), fontproperties=title_font, pad=16, parse_math=False)
        ax.set_xlabel(wrap_text(x_label or x, renderer, font, label_width), fontproperties=font, parse_math=False)
        ax.set_ylabel(wrap_text(y_label, renderer, font, fig.bbox.height * .4), fontproperties=font, parse_math=False)
        legend = ax.legend(prop=font, frameon=False, loc='upper left', bbox_to_anchor=(1.02, 1), borderaxespad=0)
        for text in legend.get_texts():
            text.set_parse_math(False)
        ax.spines[['top', 'right']].set_visible(False)
        ax.grid(axis='y', color='#dddddd', linewidth=.5); ax.set_axisbelow(True)
        check_layout(fig, ax, legend)
        with output_file(filename, '.png') as path:
            fig.savefig(path, dpi=fig.dpi, facecolor='white')
            from PIL import Image
            with Image.open(path) as image:
                image.verify()
    finally:
        plt.close(fig)
    return result({'filename': filename, 'rowCount': len(rows), 'series': y, 'aggregation': 'none'}, warnings)
