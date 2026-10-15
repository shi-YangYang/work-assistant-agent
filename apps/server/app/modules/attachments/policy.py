"""Shared filename policy; MIME cannot bypass a blocked extension."""
from app.core.errors import problem
from app.core.input_rules import ATTACHMENT_RULES


def check_filename(name):
    basename = name.replace('\\', '/').split('/')[-1].rstrip('. ').lower()
    suffix = basename.rsplit('.', 1)[-1] if '.' in basename else ''
    blocked = ATTACHMENT_RULES['blocked']
    if suffix in blocked['archive']:
        problem(415, '暂不支持压缩包，请解压后选择需要处理的文件。')
    if suffix in blocked['macro'] or suffix in ATTACHMENT_RULES['legacyOffice']:
        problem(415, '暂不支持旧版 Office 或含宏文件，请转换为 PDF、DOCX、PPTX、XLSX 或 CSV。')
    if suffix in blocked['program']:
        problem(415, '暂不支持上传程序、安装包、镜像或编译文件。')
    return suffix


def attachment_kind(name):
    suffix = check_filename(name)
    if suffix in ATTACHMENT_RULES['images']:
        return 'image'
    if suffix in ATTACHMENT_RULES['audio']:
        return 'audio'
    return 'document'
