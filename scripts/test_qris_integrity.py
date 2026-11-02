"""Offline QRIS structure and image tests. QA-only pyzbar + system libzbar."""
import pytest
from scripts.verify_qris_integrity import crc16_ccitt_false, parse_tlv, verify_payload, verify_image

PAYLOAD = ('00020101021126570011ID.DANA.WWW011893600915391010139102099101013910303UMI'
           '51440014ID.CO.QRIS.WWW0215ID10254419468330303UMI5204899953033605802ID'
           '5907NANZERA6011Kab. Malang6105651626304A53E')


def test_owner_qris_payload_crc_and_identity():
    result=verify_payload(PAYLOAD)
    assert result['merchant_name']=='NANZERA'
    assert result['currency']=='IDR'
    assert result['qr_kind']=='static'
    assert result['amount_in_qr'] is False
    assert crc16_ccitt_false(PAYLOAD[:-4].encode())=='A53E'


def test_qris_corruption_fails_closed():
    corrupt=PAYLOAD.replace('NANZERA','NANZERM')
    with pytest.raises(ValueError,match='CRC'):verify_payload(corrupt)
    with pytest.raises(ValueError):verify_payload(PAYLOAD[:-4]+'0000')
    with pytest.raises(ValueError):parse_tlv('5909NANZERA')


def test_live_asset_decodes_and_matches_all_copies():
    result=verify_image()
    assert result['crc16_valid'] is True
    assert result['bytes_identical_across_frontend_backend_and_pages']
