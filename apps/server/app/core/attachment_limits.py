MAX_ATTACHMENTS = 20
MAX_AUDIO_ATTACHMENTS = 3
MAX_IMAGE_BYTES = 40 * 1024 * 1024
MAX_AUDIO_BYTES = 30 * 1024 * 1024
MAX_FILE_BYTES = 100 * 1024 * 1024
# One upload request contains one file, plus multipart headers.
MAX_UPLOAD_BODY_BYTES = MAX_FILE_BYTES + 2 * 1024 * 1024
MAX_REQUEST_BODY_BYTES = 32 * 1024 * 1024
MAX_CONCURRENT_UPLOADS = 4


def attachment_byte_limit(kind):
    return {'image': MAX_IMAGE_BYTES, 'audio': MAX_AUDIO_BYTES}.get(kind, MAX_FILE_BYTES)


def attachment_size_error(kind):
    label = {'image': '每张图片', 'audio': '每段语音'}.get(kind, '单个文档')
    return f'{label}不能超过 {attachment_byte_limit(kind) // (1024 * 1024)} MB'
