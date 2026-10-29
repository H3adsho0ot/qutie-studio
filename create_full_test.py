"""Create a reusable editor document. This script never prints."""
import base64
import io
import json
import uuid
from pathlib import Path
import httpx
import qrcode
from PIL import Image, ImageDraw

def encoded(image):
    out = io.BytesIO()
    image.save(out, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()

nodes = []
def add(kind, **attrs):
    nodes.append({'type': kind, 'attrs': attrs})

add('Rect', x=4, y=4, width=1272, height=184, stroke='black', strokeWidth=2)
for text, y, size in [('QUTIE  ÄÖÜ äöü ß €', 14, 32),
                      ('12 px · 0123456789', 58, 24),
                      ('9 px · small text', 94, 18)]:
    add('Text', x=20, y=y, text=text, fontFamily='Noto', fontSize=size, fill='black')
add('Line', x=20, y=160, points=[0, 0, 640, 0], stroke='black', strokeWidth=2)
for mm in range(0, 41, 5):
    add('Line', x=20 + mm*16, y=160, points=[0, -12 if mm % 10 == 0 else -6, 0, 8], stroke='black', strokeWidth=2)
add('Text', x=230, y=128, text='40 mm ruler', fontFamily='Noto', fontSize=18, fill='black')
add('Line', x=480, y=60, points=[0, 0, 180, 0], stroke='black', strokeWidth=2)
add('Line', x=640, y=60, points=[0, -10, 20, 0, 0, 10], closed=True, fill='black')
add('Line', x=480, y=88, points=[0, 0, 180, 0], stroke='black', strokeWidth=2)
add('Line', x=480, y=106, points=[0, 0, 180, 0], stroke='black', strokeWidth=4)

icon = Image.new('RGB', (60,60), 'white')
d = ImageDraw.Draw(icon)
d.rectangle((1,1,58,58), outline='black', width=2)
for row in range(4):
    for col in range(4):
        if (row+col)%2==0:
            d.rectangle((7+col*11,7+row*11,17+col*11,17+row*11),fill='black')
add('Image', x=720, y=30, width=120, height=120, src=encoded(icon))
add('Text', x=736, y=158, text='PNG', fontFamily='Noto', fontSize=18, fill='black')
code = qrcode.QRCode(box_size=6, border=4)
code.add_data('Qutie-Test'); code.make(fit=True)
add('Image', x=880, y=8, width=174, height=174, src=encoded(code.make_image().convert('RGB')), qrText='Qutie-Test')
add('Text', x=1115, y=167, text='90° TEST', rotation=270, fontFamily='Noto', fontSize=24, fill='black')
add('Line', x=1210, y=20, points=[0,0,0,145], stroke='black', strokeWidth=1)
document = {'version':1, 'length':80, 'lengthScale':100, 'feed':14,
            'threshold':160, 'dither':False, 'nodes':nodes}
value = {'name':'Full test · 80 mm', 'document':document}
root = Path(__file__).parent
(root/'data/full-test.json').write_text(json.dumps(value, ensure_ascii=False, indent=2),encoding='utf-8')
with httpx.Client(base_url='http://127.0.0.1:8765', timeout=20) as client:
    id = 'full-test-' + uuid.uuid4().hex
    result = client.put('/api/templates/'+id, json=value)
    result.raise_for_status()
    print(json.dumps({'template_id':id, 'elements':len(nodes)}))
