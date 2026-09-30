"""Fixed fonts in the image; model input never chooses filesystem resources."""
from pathlib import Path

FONT_NAME = 'WenQuanYi Micro Hei'
FONT_PATH = Path('/usr/share/fonts/truetype/wqy/wqy-microhei.ttc')


def require_font():
    if not FONT_PATH.is_file():
        raise ValueError('执行镜像缺少中文字体，请更新沙盒镜像')
    return str(FONT_PATH)


def pdf_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if 'NoriaCJK' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('NoriaCJK', require_font(), subfontIndex=0))
    return 'NoriaCJK'
