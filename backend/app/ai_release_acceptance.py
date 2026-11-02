"""Fail-closed, evidence-based acceptance for BLINK's two AI release targets.

This is NOT a replacement for trained-model inference. Reports come from the
existing true Real-ESRGAN GPU tools; math/contract checks here cannot certify
that severely defocused source content is recoverable.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

ENGINE = 'real-esrgan-ncnn-vulkan'


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def validate_photo_evidence(quality_report: dict, *, min_samples: int = 5) -> list[str]:
    issues = []
    if quality_report.get('status') != 'passed':
        issues.append('Benchmark photo asli belum lulus')
    if quality_report.get('engine') != ENGINE:
        issues.append('Engine inferensi foto tidak terverifikasi sebagai Real-ESRGAN NCNN')
    preflight = quality_report.get('gpu_preflight') or {}
    if preflight.get('status') != 'passed' or preflight.get('engine') != ENGINE:
        issues.append('Preflight GPU/model foto belum berhasil')
    if not quality_report.get('model_fingerprint') or quality_report.get('model_fingerprint') != preflight.get('model_fingerprint'):
        issues.append('Fingerprint binary/model foto tidak cocok')
    samples = quality_report.get('samples') or []
    if len(samples) < min_samples or quality_report.get('total_samples') != len(samples):
        issues.append(f'Perlu minimal {min_samples} sampel referensi independen')
    if len({item.get('reference') for item in samples}) != len(samples):
        issues.append('Nama referensi foto duplikat')
    actual_passes = 0
    for item in samples:
        gain = item.get('gain_db')
        changed = item.get('changed_pixels_mean', [])
        if not isinstance(gain, (float, int)) or not math.isfinite(gain):
            issues.append('Metrik foto tidak valid')
            continue
        truly_passed = gain > 0 and item.get('passed') is True and changed and max(changed) >= 0.15
        actual_passes += bool(truly_passed)
        if not truly_passed:
            issues.append(f"Tidak ada bukti kualitas lebih baik pada {item.get('reference', 'sampel')}")
    fraction_required = quality_report.get('required_pass_fraction', 0.8)
    if not isinstance(fraction_required, (int, float)) or not 0.8 <= fraction_required <= 1:
        issues.append('Ambang kualitas kurang ketat')
    elif samples and actual_passes / len(samples) < fraction_required:
        issues.append('Persentase peningkatan foto di bawah ambang')
    if actual_passes != quality_report.get('passed_samples'):
        issues.append('Jumlah lulus foto tidak cocok dengan bukti per sampel')
    return issues


def validate_video_evidence(video_report: dict, *, actual_file: Path | None = None,
                            expected_fingerprint: dict | None = None) -> list[str]:
    issues = []
    if video_report.get('inference_executed') is not True or video_report.get('engine') != ENGINE:
        issues.append('Tidak ada bukti inferensi Real-ESRGAN asli untuk video')
    if not isinstance(video_report.get('model_fingerprint'), dict) or not video_report.get('model_fingerprint'):
        issues.append('Laporan video belum memuat fingerprint model asli')
    if expected_fingerprint is not None and video_report.get('model_fingerprint') != expected_fingerprint:
        issues.append('Fingerprint model video tidak sesuai instalasi aktif')
    if video_report.get('target') != '4k':
        issues.append('Target pengujian video harus 4k')
    dims = video_report.get('output_dimensions')
    if dims not in ([3840, 2160], [2160, 3840]):
        issues.append('Dimensi output video bukan 4K')
    if not isinstance(video_report.get('video_frames_inferred'), int) or video_report['video_frames_inferred'] < 2:
        issues.append('Minimal dua frame video harus diproses model')
    if not isinstance(video_report.get('output_duration_seconds'), (float, int)) or video_report['output_duration_seconds'] <= 0:
        issues.append('Durasi video output tidak valid')
    if video_report.get('input_had_audio') and not video_report.get('output_has_audio'):
        issues.append('Track audio sumber hilang')
    diff = video_report.get('mean_difference_from_lanczos')
    if (not isinstance(diff, list) or not diff
            or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in diff)
            or max(diff) < 0.15):
        issues.append('Belum ada bukti output AI berbeda dari interpolasi')
    # An automatically produced smoke report is never sufficient for a quality
    # promise. A separate human reviewer must inspect real motion and artifacts.
    review = video_report.get('visual_review') or {}
    if (video_report.get('quality_verdict') != 'REVIEW_PASSED'
            or review.get('flicker_ok') is not True
            or review.get('detail_natural') is not True
            or review.get('audio_sync_ok') is not True
            or not review.get('reviewer')
            or not review.get('notes')):
        issues.append('Kualitas temporal dan artefak video masih perlu evaluasi nyata')
    if actual_file is not None:
        if not video_report.get('output_sha256'):
            issues.append('Laporan video tidak memuat hash file hasil')
        if not actual_file.is_file() or actual_file.stat().st_size <= 0:
            issues.append('File video hasil AI tidak ditemukan')
        elif video_report.get('output_sha256') and sha256_file(actual_file) != video_report['output_sha256']:
            issues.append('Hash file video tidak cocok dengan laporan inferensi')
    return issues


def acceptance_report(photo_report: dict | None, video_report: dict | None, *,
                      video_file: Path | None = None, expected_fingerprint: dict | None = None,
                      active_engine_verified: bool = False) -> dict:
    photo_issues = validate_photo_evidence(photo_report) if photo_report is not None else ['Laporan benchmark foto AI tidak ada']
    video_issues = validate_video_evidence(video_report, actual_file=video_file,
                                           expected_fingerprint=expected_fingerprint) if video_report is not None else ['Laporan inferensi video AI tidak ada']
    if not active_engine_verified or not expected_fingerprint:
        photo_issues.append('Engine AI aktif belum berhasil diverifikasi dengan model sungguhan')
        video_issues.append('Engine AI aktif belum berhasil diverifikasi dengan model sungguhan')
    elif photo_report and photo_report.get('model_fingerprint') != expected_fingerprint:
        photo_issues.append('Fingerprint foto tidak sesuai model yang saat ini terpasang')
    return {
        'status': 'PASSED' if not photo_issues and not video_issues else 'NOT_READY',
        'targets': {
            'real_ai_photo_4k': 'PASSED' if not photo_issues else 'NOT_VERIFIED',
            'real_ai_video_4k': 'PASSED' if not video_issues else 'NOT_VERIFIED',
        },
        'blocking_issues': photo_issues + video_issues,
        'notice': ('Lulus adalah bukti pada sampel yang diuji, bukan jaminan semua media buruk dapat '
                   'dipulihkan sempurna atau layanan sudah aman untuk pelanggan umum.'),
    }
