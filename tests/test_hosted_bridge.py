"""The hosted shell may call only an explicitly paired local service."""
from dataclasses import replace

from fastapi.testclient import TestClient

import web_app
from config.settings import settings
from services.hosted_bridge import ORIGIN_FILE, TOKEN_FILE, hosted_origin


def test_hosted_bridge_requires_exact_origin_and_local_key(tmp_path, monkeypatch):
    approved = 'https://invoice-iq-example.pages.dev'
    (tmp_path / ORIGIN_FILE).write_text(approved, encoding='utf-8')
    monkeypatch.setattr(web_app, 'settings', replace(settings, local_storage_dir=str(tmp_path)))
    client = TestClient(web_app.app)

    preflight = client.options('/api/config', headers={
        'Origin': approved, 'Access-Control-Request-Method': 'GET',
        'Access-Control-Request-Headers': 'authorization',
        'Access-Control-Request-Private-Network': 'true',
    })
    assert preflight.status_code == 204
    assert preflight.headers['access-control-allow-origin'] == approved
    assert preflight.headers['access-control-allow-private-network'] == 'true'
    assert client.get('/api/config', headers={'Origin': approved}).status_code == 401
    assert client.get('/api/config', headers={
        'Origin': approved, 'Authorization': 'Bearer wrong'}).status_code == 401

    pairing = client.get('/bridge/pair', headers={'Host': '127.0.0.1:8505'})
    assert pairing.status_code == 200
    assert 'no-store' in pairing.headers['cache-control']
    token = (tmp_path / TOKEN_FILE).read_text(encoding='ascii')
    assert len(token) >= 40
    assert token in pairing.text
    allowed = client.get('/api/config', headers={
        'Origin': approved, 'Authorization': f'Bearer {token}'})
    assert allowed.status_code == 200
    assert allowed.headers['access-control-allow-origin'] == approved
    assert 'ui_settings' in allowed.json()

    wrong_site = client.post('/api/reset/prepare', headers={
        'Origin': 'https://unapproved.pages.dev', 'Authorization': f'Bearer {token}'})
    assert wrong_site.status_code == 403
    assert 'access-control-allow-origin' not in wrong_site.headers
    assert client.post('/api/reset/prepare').status_code == 200


def test_bad_or_missing_hosted_origin_never_enables_bridge(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, 'settings', replace(settings, local_storage_dir=str(tmp_path)))
    client = TestClient(web_app.app)
    assert client.get('/bridge/pair', headers={'Host': '127.0.0.1:8505'}).status_code == 404
    for value in ('http://invoice.pages.dev', 'https://invoice.pages.dev/extra',
                  'https://invoice.pages.dev:444', 'https://invoice.pages.dev.evil.org',
                  'https://invoice.pages.dev/?token=bad', 'https://invoice.pages.dev:bad'):
        (tmp_path / ORIGIN_FILE).write_text(value, encoding='utf-8')
        assert hosted_origin(tmp_path) == ''
        assert client.get('/bridge/pair', headers={'Host': '127.0.0.1:8505'}).status_code == 404
    assert not (tmp_path / TOKEN_FILE).exists()
