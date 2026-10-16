import base64
from email.parser import BytesParser
from email.policy import default
from io import BytesIO
import json
import subprocess
import urllib.error

from click.testing import CliRunner
from PIL import Image
import pytest

from press_chrome import client, vision, vision_http
from press_chrome.cli import main


def png(width=800, height=600):
    stream = BytesIO()
    Image.new('RGB', (width, height)).save(stream, format='PNG')
    return stream.getvalue()


@pytest.mark.parametrize('size', [(3200, 200), (200, 3200), (7, 9), (1569, 999), (800, 600)])
def test_mapping_roundtrip(size):
    image = vision.prepare_image(png(*size))
    assert 280 <= image.upload_width <= 1568
    assert 280 <= image.upload_height <= 1568
    assert 78400 <= image.upload_width * image.upload_height <= 2458624
    fractions = dict(left=(image.pad_x + image.resized_width*.2)/image.upload_width,
                     right=(image.pad_x + image.resized_width*.8)/image.upload_width,
                     top=(image.pad_y + image.resized_height*.1)/image.upload_height,
                     bottom=(image.pad_y + image.resized_height*.9)/image.upload_height)
    result = image.map_box(fractions)
    assert result['left'] == pytest.approx(size[0]*.2)
    assert result['right'] == pytest.approx(size[0]*.8)
    assert result['top'] == pytest.approx(size[1]*.1)
    assert result['bottom'] == pytest.approx(size[1]*.9)
    full = image.map_box(dict(left=0, right=1, top=0, bottom=1))
    assert full['width'] == size[0] and full['height'] == size[1]


def response(noul=.8):
    return dict(model=vision.MODEL, usage={'input_tokens': 12}, answers={
        'presence': {'noul': noul},
        'location': {'box': dict(top=.1, bottom=.5, left=.2, right=.6), 'confidence': .9}})


@pytest.fixture
def image_path(tmp_path):
    path = tmp_path/'image.png'
    path.write_bytes(png())
    return path


def test_one_request_presence_and_box(monkeypatch, image_path):
    calls = []
    def request(image, questions):
        calls.append(questions)
        return response(.2)
    monkeypatch.setattr(vision, 'request_model', request)
    result = vision.analyze('box', 'a cat', image_path=str(image_path))
    assert result['box'] is None and result['noul'] == .2
    assert len(calls) == 1
    assert calls[0] == {'presence': {'type': 'noul', 'instructions': 'Is there a cat in `screenshot`?'},
                        'location': {'type': 'box', 'instructions': 'a cat in `screenshot`'}}


def test_screenshot_css_page_and_save(monkeypatch, tmp_path):
    raw = png()
    def capture(tab_id):
        assert tab_id == 17
        return dict(dataUrl='data:image/png;base64,'+base64.b64encode(raw).decode(),
                    devicePixelRatio=2, scrollX=30, scrollY=400)
    monkeypatch.setattr(client, 'screenshot', capture)
    monkeypatch.setattr(vision, 'request_model', lambda *args: response())
    save = tmp_path/'capture.png'
    result = vision.analyze('box', 'cat', tab_id=17, save_screenshot=str(save))
    box = result['box']
    assert box['screenshot']['left'] == 160
    assert box['viewport']['left'] == 80
    assert box['page']['left'] == 110
    assert box['page']['top'] == 430
    assert box['confidence'] == .9
    assert save.read_bytes() == raw


def test_file_page_null_and_threshold(monkeypatch, image_path):
    monkeypatch.setattr(vision, 'request_model', lambda *args: response(.5))
    result = vision.analyze('box', 'cat', image_path=str(image_path))
    assert result['answer'] == 'yes'
    assert result['box']['page'] is None and result['box']['viewport'] is None
    assert vision.analyze('box', 'cat', image_path=str(image_path), threshold=.6)['box'] is None


@pytest.mark.parametrize('kind', ['ask', 'box'])
def test_cli_json(monkeypatch, image_path, kind):
    monkeypatch.setattr(vision, 'request_model', lambda *args: response())
    result = CliRunner().invoke(main, ['vision', kind, '--image', str(image_path), 'cat?', '--format', 'json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data['image'] == {'width': 800, 'height': 600}
    assert data['answer'] == 'yes'
    text = CliRunner().invoke(main, ['vision', kind, '--image', str(image_path), 'cat?'])
    assert text.exit_code == 0 and 'noul: 0.8' in text.output


def test_ask_one_noul_and_tab_cli(monkeypatch):
    monkeypatch.setattr(client, 'screenshot', lambda tab: dict(dataUrl='data:image/png;base64,'+base64.b64encode(png()).decode()))
    def request(image, questions):
        assert questions == {'presence': {'type': 'noul', 'instructions': 'Is there a cat?'}}
        return response()
    monkeypatch.setattr(vision, 'request_model', request)
    result = CliRunner().invoke(main, ['vision', 'ask', '42', 'Is there a cat?', '--format', 'json'])
    assert result.exit_code == 0, result.output


def test_client_screenshot_errors(monkeypatch):
    monkeypatch.setattr(client, 'rpc', lambda payload: {'ok': False, 'error': 'tab not visible', 'code': 5})
    with pytest.raises(client.ClientError, match='tab not visible'):
        client.screenshot(4)


def test_av_multipart(monkeypatch):
    monkeypatch.delenv('HTTPS_PROXY', raising=False)
    monkeypatch.setenv('CHTABS_AV', '/custom/av')
    def run(argv, **kwargs):
        assert argv[0] == '/custom/av'
        assert not any('Bearer' in arg for arg in argv)
        envelope = json.loads(kwargs['input'])
        message = BytesParser(policy=default).parsebytes(
            ('Content-Type: '+envelope['content_type']+'\r\n\r\n').encode()+base64.b64decode(envelope['body']))
        parts = list(message.iter_parts())
        assert parts[0].get_param('name', header='content-disposition') == 'request'
        assert parts[0].get_content_type() == 'application/json'
        payload = json.loads(parts[0].get_payload(decode=True))
        reference = payload['state']['screenshot']
        assert payload['assets'][reference] == {'type': 'image', 'part': 'img'}
        assert payload['model'] == 'jev-1.14.0'
        assert parts[1].get_payload(decode=True).startswith(b'\x89PNG')
        return subprocess.CompletedProcess(argv, 0, json.dumps(response()), '')
    monkeypatch.setattr(subprocess, 'run', run)
    assert vision.request_model(vision.prepare_image(png()), {})['model'] == vision.MODEL


def test_in_process_proxy_http(monkeypatch):
    monkeypatch.setenv('HTTPS_PROXY', 'http://localhost:1111')
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-placeholder')
    monkeypatch.setenv('SSL_CERT_FILE', '/test/cert.pem')
    monkeypatch.setattr(vision_http.ssl, 'create_default_context', lambda **kw: kw)
    class Response(BytesIO):
        pass
    def urlopen(req, **kwargs):
        assert req.full_url == 'https://api.typesafe.ai/v1/systemone'
        assert req.get_header('Authorization') == 'Bearer test-placeholder'
        assert req.get_header('Typesafe-danger-zone-images') == 'true'
        assert kwargs['context'] == {'cafile': '/test/cert.pem'}
        return Response(json.dumps(response()).encode())
    monkeypatch.setattr(vision_http.urllib.request, 'urlopen', urlopen)
    assert vision.request_model(vision.prepare_image(png()), {})['model'] == vision.MODEL


@pytest.mark.parametrize('status', [400, 413, 429])
def test_http_errors(monkeypatch, status):
    monkeypatch.setenv('HTTPS_PROXY', 'http://proxy')
    monkeypatch.setenv('TYPESAFE_API_KEY', 'secret-test')
    monkeypatch.setattr(vision_http.ssl, 'create_default_context', lambda **kw: None)
    def fail(*args, **kwargs):
        raise urllib.error.HTTPError('url', status, 'error', {}, BytesIO(b'bad asset secret-test'))
    monkeypatch.setattr(vision_http.urllib.request, 'urlopen', fail)
    with pytest.raises(vision.VisionError, match=f'HTTP {status}: bad asset \\[redacted\\]'):
        vision_http.post(b'body', 'multipart/form-data')


def test_av_failure(monkeypatch):
    monkeypatch.delenv('HTTPS_PROXY', raising=False)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess([], 5, '{"worker_error":"TypeSafe HTTP 429: slow down"}', ''))
    with pytest.raises(vision.VisionError, match='HTTP 429'):
        vision.request_model(vision.prepare_image(png()), {})


def test_agent_help():
    result = CliRunner().invoke(main, ['agent-help', '--format', 'json'])
    assert result.exit_code == 0
    assert 'vision ask' in result.output and 'vision box' in result.output
