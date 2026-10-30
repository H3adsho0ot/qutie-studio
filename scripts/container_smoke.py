"""Exercise a disposable container over HTTP. Never creates a print job."""
import argparse
import base64
import hashlib
import json
import struct
import time
import urllib.error
import urllib.request
import zlib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18765')
    parser.add_argument('--phase', choices=['write', 'read'], required=True)
    args = parser.parse_args()

    def request(path, data=None, method=None):
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(args.url + path, body, method=method,
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.read(), response.headers

    def api(path, data=None, method=None):
        return json.loads(request(path, data, method)[0])

    for attempt in range(60):
        try:
            page, _ = request('/')
            assert b'<html lang="en">' in page
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(.5)
    else:
        raise RuntimeError('Container did not become ready')

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))

    image = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
    image += chunk(b'IDAT', zlib.compress(b'\x00\xff\xff\xff')) + chunk(b'IEND', b'')
    document = {'version': 1, 'length': 10, 'nodes': []}

    if args.phase == 'write':
        for path in ['/static/favicon.svg', '/static/app.js', '/static/browser-id.js', '/static/snapping.js', '/static/line-geometry.js', '/static/vendor/konva.min.js', '/static/fonts/NotoSans.ttf', '/static/fonts/NotoSans-Italic.ttf']:
            assert request(path)[0], path
        data = {'image': base64.b64encode(image).decode(), 'length_mm': 10}
        raster, headers = request('/api/render', data)
        preview = api('/api/previews', data)
        assert hashlib.sha256(raster).hexdigest() == preview['sha256'] == headers['X-Raster-SHA256']
        assert request(preview['url'])[0] == raster
        uploaded = api('/api/images', {'image': data['image']})
        assert request(uploaded['url'])[0].startswith(b'\x89PNG')
        document['smoke_preview'] = preview['id']
        api('/api/templates/container-smoke', {'name': 'Container smoke test', 'document': document}, 'PUT')

    saved = api('/api/templates/container-smoke')
    assert saved['name'] == 'Container smoke test'
    assert saved['document']['nodes'] == []
    raster, _ = request('/api/previews/' + saved['document']['smoke_preview'] + '.png')
    assert struct.unpack('>II', raster[16:24]) == (96, 80)
    assert api('/api/jobs') == [], 'The smoke test must never print'
    print('Container smoke test passed:', args.phase)


if __name__ == '__main__':
    main()
