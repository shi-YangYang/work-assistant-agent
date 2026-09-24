import base64
import io
from PIL import Image


def image_sample():
    image = Image.new('RGB', (64, 64), (255, 0, 0))
    data = io.BytesIO()
    image.save(data, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(data.getvalue()).decode()
