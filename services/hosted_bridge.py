"""Opt-in, same-computer access for a separately hosted static interface."""
from __future__ import annotations

import secrets
from pathlib import Path
from urllib.parse import urlsplit

ORIGIN_FILE = 'hosted_ui_origin.txt'
TOKEN_FILE = 'hosted_ui_token.txt'


def hosted_origin(root: Path) -> str:
    path = root / ORIGIN_FILE
    try:
        value = path.read_text(encoding='utf-8').strip().rstrip('/')
    except FileNotFoundError:
        return ''
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return ''
    # Only the exact Cloudflare Pages site approved on this computer can read
    # local invoice data. No user info, path, query, fragment, or custom port.
    if (parsed.scheme != 'https' or not parsed.hostname or
            not parsed.hostname.endswith('.pages.dev') or
            parsed.username or parsed.password or port or
            parsed.path or parsed.query or parsed.fragment or
            value != f'https://{parsed.hostname}'):
        return ''
    return value


def bridge_token(root: Path) -> str:
    path = root / TOKEN_FILE
    try:
        token = path.read_text(encoding='ascii').strip()
        if len(token) >= 40:
            return token
        raise ValueError('The hosted interface key is invalid; remove it only after disconnecting the site.')
    except FileNotFoundError:
        root.mkdir(parents=True, exist_ok=True)
        token = secrets.token_urlsafe(32)
        try:
            with path.open('x', encoding='ascii') as stream:
                stream.write(token)
            return token
        except FileExistsError:
            # Another local process created it concurrently.
            return bridge_token(root)
