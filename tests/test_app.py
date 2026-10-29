import base64
import io
import os
import tempfile
import time

os.environ['QUTIE_DATA'] = tempfile.mkdtemp(prefix='qutie-test-')
from fastapi.testclient import TestClient
from PIL import Image
import app


def png():
    image = Image.new('RGB', (320,96), 'white')
    image.putpixel((0,0),(0,0,0))
    data = io.BytesIO(); image.save(data, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(data.getvalue()).decode()


def test_template_roundtrip_and_delete():
    with TestClient(app.app) as c:
        doc = {'version':1,'length':40,'nodes':[{'type':'Text','attrs':{'text':'Größe ÄÖÜ'}}]}
        assert c.put('/api/templates/test',json={'name':'Küche','document':doc}).status_code == 200
        assert c.get('/api/templates/test').json()['document'] == doc
        assert any(t['name']=='Küche' for t in c.get('/api/templates').json())
        assert c.delete('/api/templates/test').status_code == 200
        assert c.get('/api/templates/test').status_code == 404


def test_preview_geometry_and_exact_raster_queued(monkeypatch):
    printed=[]
    def fake(image, feed):
        printed.append(image.copy())
        return 'Übertragen'
    monkeypatch.setattr(app.printer,'print_image',fake)
    with TestClient(app.app) as c:
        p=c.post('/api/previews',json={'image':png(),'length_mm':40}).json()
        expected=Image.open(io.BytesIO(c.get(p['url']).content));expected.load()
        assert expected.size==(96,320)
        for _ in range(2):
            assert c.post('/api/jobs',json={'preview_id':p['id'],'request_id':'same-request'}).status_code==200
        app.queue.join()
        assert len(printed)==1
        assert printed[0].tobytes()==expected.tobytes()


def test_failure_never_replays(monkeypatch):
    calls=[]
    def fail(*args):
        calls.append(1)
        raise OSError('USB getrennt')
    monkeypatch.setattr(app.printer,'print_image',fail)
    with TestClient(app.app) as c:
        p=c.post('/api/previews',json={'image':png(),'length_mm':40}).json()
        c.post('/api/jobs',json={'preview_id':p['id'],'request_id':'broken'})
        app.queue.join()
        assert len(calls)==1
        job=next(j for j in c.get('/api/jobs').json() if j['id']=='broken')
        assert job['state']=='unknown'
        assert 'USB getrennt' in job['message']


def test_invalid_inputs_and_origin():
    with TestClient(app.app) as c:
        assert c.post('/api/previews',json={'image':'bad','length_mm':40}).status_code==400
        assert c.post('/api/previews',json={'image':png(),'length_mm':1000}).status_code==422
        assert c.post('/api/jobs',json={'preview_id':'missing','request_id':'missing'}).status_code==404
        assert c.put('/api/templates/x',headers={'origin':'https://other.example'},json={'name':'x','document':{}}).status_code==403
        assert c.get('/api/qr?text=Hallo').headers['content-type']=='image/png'
        upload=c.post('/api/images',json={'image':png()}).json()
        assert c.get(upload['url']).status_code==200


def test_length_calibration_preserves_head_width():
    with TestClient(app.app) as c:
        response=c.post('/api/previews',json={'image':png(),'length_mm':40,'length_scale':103.6})
        assert response.status_code==200
        assert response.json()['width']==96
        assert response.json()['rows']==332
        assert c.post('/api/previews',json={'image':png(),'length_mm':40,'length_scale':500}).status_code==422


def test_usb_raw_info_disables_bluetooth_handshake(monkeypatch):
    import printer
    sent=[]
    info=bytearray(143)
    info[:7]=b'HPRT Q2'
    info[140:]=b'END'
    class FakeUSB:
        def write(self,data): sent.append(data)
        def read(self): return bytes(info)
        def close(self): pass
    monkeypatch.setattr(printer,'USB',FakeUSB)
    with printer.USBSession() as link:
        assert link.key==0
    assert sent==[printer.protocol.CMD_INFO]


def test_bluetooth_requires_explicit_printer_address(monkeypatch):
    import printer
    import pytest
    monkeypatch.setattr(printer.sys, 'platform', 'linux')
    monkeypatch.setenv('QUTIE_TRANSPORT', 'bluetooth')
    monkeypatch.delenv('QUTIE_MAC', raising=False)
    with pytest.raises(ConnectionError, match='Set QUTIE_MAC'):
        printer.session()


def test_status_cache_expiry_and_print_lock(monkeypatch):
    calls=[]
    now=[100.0]
    monkeypatch.setattr(app.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(app, 'printer_checked_at', 0)
    monkeypatch.setattr(app, 'printer_cache', {})
    def status():
        calls.append(1)
        return {'connected':True,'model':'HPRT Q2','firmware':'1.1.20',
                'battery':99,'ready':True,'problems':[]}
    monkeypatch.setattr(app.printer,'status',status)
    assert app.printer_status()['battery']==99
    assert app.printer_status()['ready']
    assert len(calls)==1
    now[0]+=16
    assert app.printer_status()['ready']
    assert len(calls)==2
    with app.device_lock:
        busy=app.printer_status()
        assert busy['busy'] and not busy['ready']
        assert busy['battery']==99
        assert len(calls)==2


def test_status_failure_does_not_keep_stale_battery(monkeypatch):
    monkeypatch.setattr(app,'printer_checked_at',0)
    monkeypatch.setattr(app,'printer_cache',{'connected':True,'battery':99})
    def fail():
        raise ConnectionError('USB getrennt')
    monkeypatch.setattr(app.printer,'status',fail)
    result=app.printer_status()
    assert result['connected'] is False
    assert result['message']=='USB getrennt'
    assert 'battery' not in result


def test_live_editor_raster_is_identical_to_print_preview():
    import hashlib
    with TestClient(app.app) as c:
        before = set((app.DATA/'previews').glob('*.png'))
        body={'image':png(),'length_mm':40,'threshold':160,'dither':True,'length_scale':103.6}
        live=c.post('/api/render',json=body)
        assert live.status_code==200
        assert live.headers['content-type']=='image/png'
        assert live.headers['cache-control']=='no-store'
        assert set((app.DATA/'previews').glob('*.png'))==before
        saved=c.post('/api/previews',json=body).json()
        assert c.get(saved['url']).content==live.content
        assert saved['sha256']==live.headers['x-raster-sha256']==hashlib.sha256(live.content).hexdigest()
        raster=Image.open(io.BytesIO(live.content))
        assert raster.mode=='1'
        assert raster.size==(96,332)
