import base64
import io
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from queue import Queue

import qrcode
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field
import printer

ROOT = Path(__file__).parent
DATA = Path(os.environ.get('QUTIE_DATA', ROOT / 'data'))
DATA.mkdir(parents=True, exist_ok=True)
for folder in ('images', 'previews'):
    (DATA / folder).mkdir(exist_ok=True)
queue = Queue()
device_lock = threading.Lock()
printer_cache = {}
printer_checked_at = 0.0


def db():
    con = sqlite3.connect(DATA / 'qutie.sqlite3')
    con.row_factory = sqlite3.Row
    return con


with db() as con:
    con.executescript('''CREATE TABLE IF NOT EXISTS templates(id TEXT PRIMARY KEY, name TEXT, document TEXT);
    CREATE TABLE IF NOT EXISTS previews(id TEXT PRIMARY KEY, path TEXT);
    CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, preview_id TEXT, state TEXT, message TEXT);''')
    con.execute("UPDATE jobs SET state='unknown',message='Server restarted. Check the label before printing again.' WHERE state IN ('queued','printing')")


def update_job(id, state, message):
    with db() as con:
        con.execute('UPDATE jobs SET state=?,message=? WHERE id=?', (state, message, id))


def worker():
    global printer_checked_at
    while True:
        item = queue.get()
        if item is None:
            queue.task_done()
            return
        id, path, feed = item
        update_job(id, 'printing', 'Checking printer and sending job …')
        try:
            with device_lock, Image.open(path) as image:
                message = printer.print_image(image, feed)
            update_job(id, 'sent', message)
        except Exception as e:
            update_job(id, 'unknown', f'{e} — No automatic retry. Check the printed label.')
        finally:
            printer_checked_at = 0.0
            queue.task_done()


@asynccontextmanager
async def lifespan(app):
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    yield
    queue.put(None)
    thread.join(timeout=2)


app = FastAPI(lifespan=lifespan)


@app.middleware('http')
async def limits(request: Request, call_next):
    if int(request.headers.get('content-length', '0')) > 12_000_000:
        return Response('File too large (max. 12 MB).', status_code=413)
    # Only same-origin pages may issue mutations to the LAN print server.
    origin = request.headers.get('origin')
    if request.method not in ('GET', 'HEAD') and origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
        return Response('Origin not allowed', status_code=403)
    return await call_next(request)


class Template(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    document: dict


class Preview(BaseModel):
    image: str
    length_mm: float = Field(ge=10, le=80)
    threshold: int = Field(default=160, ge=0, le=255)
    dither: bool = False
    length_scale: float = Field(default=100, ge=90, le=110)


class Job(BaseModel):
    preview_id: str
    feed_mm: float = Field(default=14, ge=0, le=30)
    request_id: str = Field(min_length=1, max_length=100)


def decode_image(encoded):
    try:
        data = base64.b64decode(encoded.split(',')[-1], validate=True)
        if len(data) > 8_000_000:
            raise ValueError('Image too large')
        image = Image.open(io.BytesIO(data))
        if image.format not in ('PNG', 'JPEG') or image.width * image.height > 12_000_000:
            raise ValueError('Use PNG/JPEG images up to 12 megapixels')
        image.load()
        return image.convert('RGBA')
    except Exception as e:
        raise HTTPException(400, f'Invalid image: {e}')


@app.get('/')
def index():
    return FileResponse(ROOT / 'static/index.html')


@app.get('/api/templates')
def templates():
    with db() as con:
        return [dict(row) for row in con.execute('SELECT id,name FROM templates ORDER BY name')]


@app.get('/api/templates/{id}')
def template(id: str):
    with db() as con:
        row = con.execute('SELECT * FROM templates WHERE id=?', (id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Template not found')
    return {'id': row['id'], 'name': row['name'], 'document': json.loads(row['document'])}


@app.put('/api/templates/{id}')
def save_template(id: str, value: Template):
    if len(json.dumps(value.document)) > 10_000_000:
        raise HTTPException(413, 'Template too large')
    with db() as con:
        con.execute('INSERT OR REPLACE INTO templates VALUES (?,?,?)', (id, value.name, json.dumps(value.document)))
    return {'id': id}


@app.delete('/api/templates/{id}')
def delete_template(id: str):
    with db() as con:
        con.execute('DELETE FROM templates WHERE id=?', (id,))
    return {'ok': True}


@app.post('/api/images')
def upload_image(value: dict):
    image = decode_image(value.get('image', ''))
    id = uuid.uuid4().hex
    image.save(DATA / 'images' / f'{id}.png')
    return {'url': f'/api/images/{id}.png'}


@app.get('/api/images/{name}')
def image_file(name: str):
    if not name.endswith('.png') or not name[:-4].isalnum():
        raise HTTPException(400)
    path = DATA / 'images' / name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)


@app.get('/api/qr')
def qr(text: str):
    if len(text) > 1000:
        raise HTTPException(400, 'QR content too long')
    try:
        code = qrcode.QRCode(box_size=4, border=4)
        code.add_data(text)
        code.make(fit=True)
        out = io.BytesIO()
        code.make_image().save(out, format='PNG')
        return Response(out.getvalue(), media_type='image/png')
    except Exception:
        raise HTTPException(400, 'Could not create QR code')


def render_raster(value: Preview):
    source = decode_image(value.image)
    canvas = Image.new('RGBA', source.size, 'white')
    canvas.alpha_composite(source)
    # Editor is landscape. Rotate the whole design into the paper feed direction.
    gray = canvas.convert('L').resize((round(value.length_mm * 8 * value.length_scale / 100), 96), Image.Resampling.LANCZOS)
    bw = gray.convert('1') if value.dither else gray.point(lambda v: 255 if v >= value.threshold else 0).convert('1')
    raster_image = bw.transpose(Image.Transpose.ROTATE_270)
    output = io.BytesIO()
    raster_image.save(output, format='PNG')
    return output.getvalue(), raster_image.height


@app.post('/api/render')
def render(value: Preview):
    data, rows = render_raster(value)
    return Response(data, media_type='image/png', headers={
        'X-Raster-SHA256': hashlib.sha256(data).hexdigest(),
        'Cache-Control': 'no-store',
    })


@app.post('/api/previews')
def preview(value: Preview):
    data, rows = render_raster(value)
    id = uuid.uuid4().hex
    path = DATA / 'previews' / f'{id}.png'
    path.write_bytes(data)
    with db() as con:
        con.execute('INSERT INTO previews VALUES (?,?)', (id, str(path)))
    return {'id': id, 'url': f'/api/previews/{id}.png', 'width': 96, 'rows': rows,
            'sha256': hashlib.sha256(data).hexdigest()}


@app.get('/api/previews/{id}.png')
def preview_file(id: str):
    with db() as con:
        row = con.execute('SELECT path FROM previews WHERE id=?', (id,)).fetchone()
    if not row:
        raise HTTPException(404)
    return FileResponse(row['path'])


@app.get('/api/printer')
def printer_status():
    global printer_cache, printer_checked_at
    if not device_lock.acquire(blocking=False):
        return {**printer_cache, 'busy': True, 'ready': False,
                'message': 'Print job in progress'}
    try:
        # Multiple open browsers share the last hardware query.
        if time.monotonic() - printer_checked_at < 15:
            return printer_cache
        try:
            printer_cache = printer.status()
        except Exception as e:
            printer_cache = {'connected': False, 'message': str(e)}
        printer_checked_at = time.monotonic()
        return printer_cache
    finally:
        device_lock.release()


@app.post('/api/jobs')
def create_job(value: Job):
    with db() as con:
        existing = con.execute('SELECT * FROM jobs WHERE id=?', (value.request_id,)).fetchone()
        if existing:
            if existing['preview_id'] != value.preview_id:
                raise HTTPException(409, 'Job ID already used for a different preview')
            return dict(existing)
        row = con.execute('SELECT path FROM previews WHERE id=?', (value.preview_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Please create a new print preview')
        inserted = con.execute('INSERT OR IGNORE INTO jobs VALUES (?,?,?,?)', (value.request_id, value.preview_id, 'queued', 'Waiting for printer')).rowcount
    if inserted:
        queue.put((value.request_id, row['path'], value.feed_mm))
    return {'id': value.request_id, 'state': 'queued'}


@app.get('/api/jobs')
def jobs():
    with db() as con:
        return [dict(row) for row in con.execute('SELECT * FROM jobs ORDER BY rowid DESC LIMIT 30')]


app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
