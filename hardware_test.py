"""Create a 40 mm calibration label; --print sends exactly one job to the local app."""
import argparse
import base64
import io
from pathlib import Path
import uuid
import httpx
import qrcode
from PIL import Image, ImageDraw, ImageFont

p = argparse.ArgumentParser()
p.add_argument('--print', action='store_true', dest='send')
p.add_argument('--server', default='http://127.0.0.1:8765')
args = p.parse_args()
root = Path(__file__).parent
image = Image.new('RGB', (320, 96), 'white')
draw = ImageDraw.Draw(image)
font = ImageFont.truetype(str(root / 'static/fonts/NotoSans.ttf'), 17)
draw.rectangle((2, 2, 317, 93), outline='black', width=1)
draw.text((10, 15), 'Qutie · ÄÖÜ ß', font=font, fill='black')
draw.text((10, 48), '40 mm', font=font, fill='black')
draw.line((85, 61, 115, 61), fill='black', width=2)
draw.polygon([(115, 61), (107, 56), (107, 66)], fill='black')
qr = qrcode.QRCode(box_size=2, border=4)
qr.add_data('Qutie-Test'); qr.make(fit=True)
code = qr.make_image().convert('RGB')
image.paste(code, (240, 16))
(root / 'data').mkdir(exist_ok=True)
image.save(root / 'data/calibration-design.png')
if args.send:
    buf = io.BytesIO(); image.save(buf, format='PNG')
    with httpx.Client(base_url=args.server, timeout=20) as c:
        response = c.post('/api/previews', json={'image':base64.b64encode(buf.getvalue()).decode(), 'length_mm':40})
        response.raise_for_status()
        preview = response.json()
        response = c.post('/api/jobs', json={'preview_id':preview['id'], 'request_id':'calibration-'+uuid.uuid4().hex})
        response.raise_for_status()
        print(response.json())
else:
    print('Test image created. Printing only happens with --print.')
