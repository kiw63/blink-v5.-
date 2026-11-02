#!/usr/bin/env python3
"""Verify BLINK's owner-supplied QRIS image is genuinely machine-readable.

This tests QR decode, EMVCo/TLV structural integrity, CRC-16/CCITT-FALSE,
Indonesian IDR merchant metadata and that the bytes exposed to the browser,
API and server are identical. It cannot prove merchant ownership, a bank's
settlement, or availability of a payment app.

Runtime: Pillow, pyzbar and the system libzbar shared library (QA only).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/assets/qris-nanzera.jpg'
COPIES = [ROOT / 'backend/assets/qris-nanzera.jpg', ROOT / 'frontend/public/qris-nanzera.jpg']


def crc16_ccitt_false(data: bytes) -> str:
    crc = 0xffff
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ (0x1021 if crc & 0x8000 else 0)) & 0xffff
    return f'{crc:04X}'


def parse_tlv(text: str) -> dict[str, str]:
    fields = {}
    position = 0
    while position < len(text):
        if len(text) - position < 4 or not text[position:position + 4].isdigit():
            raise ValueError('Truncated/invalid EMVCo TLV header')
        tag, count = text[position:position+2], int(text[position+2:position+4])
        position += 4
        value = text[position:position+count]
        if len(value) != count or tag in fields:
            raise ValueError('Truncated/duplicate EMVCo TLV field')
        fields[tag] = value
        position += count
    return fields


def verify_payload(payload: str) -> dict:
    if not payload.isascii() or not payload.endswith(payload[-4:]) or len(payload) < 30:
        raise ValueError('Invalid QR payload encoding or size')
    fields = parse_tlv(payload)
    if payload[-8:-4] != '6304' or fields.get('63') != payload[-4:]:
        raise ValueError('CRC field must be last and must contain four hex digits')
    if crc16_ccitt_false(payload[:-4].encode('ascii')) != fields['63'].upper():
        raise ValueError('QRIS CRC failed')
    if fields.get('00') != '01' or fields.get('53') != '360' or fields.get('58') != 'ID':
        raise ValueError('QR is not a valid Indonesian IDR merchant payload')
    if fields.get('01') != '11':
        raise ValueError('BLINK owner-supplied QRIS is expected to be a static QR')
    if fields.get('59', '').strip() != 'NANZERA':
        raise ValueError('QRIS merchant name does not match the owner-supplied asset')
    if '54' in fields:
        raise ValueError('This fixed-price flow expects a static QRIS with amount entered in app')
    return {'merchant_name':fields['59'], 'merchant_city':fields.get('60'),
            'country':'ID','currency':'IDR','qr_kind':'static',
            'amount_in_qr':False,'crc16_valid':True}


def verify_image() -> dict:
    try:
        from PIL import Image
        from pyzbar.pyzbar import decode
    except (ImportError, OSError) as exc:
        raise RuntimeError('Install pyzbar + libzbar (QA dependency, not website dependency)') from exc
    raw = SOURCE.read_bytes()
    for destination in COPIES:
        if destination.read_bytes() != raw:
            raise RuntimeError(f'QRIS mismatch between browser and {destination}')
    with Image.open(SOURCE) as picture:
        qr = [entry for entry in decode(picture) if entry.type == 'QRCODE']
    if len(qr) != 1:
        raise RuntimeError(f'Expected exactly one readable QR code, got {len(qr)}')
    payload = qr[0].data.decode('ascii')
    result = verify_payload(payload)
    result['asset_sha256'] = hashlib.sha256(raw).hexdigest()
    result['bytes_identical_across_frontend_backend_and_pages'] = True
    result['note'] = ('Readable valid QRIS data only. Verify actual Rp20.000 receipt'
                      ' in merchant account before admin approval.')
    return result


if __name__ == '__main__':
    print(json.dumps(verify_image(), ensure_ascii=False, indent=2))
