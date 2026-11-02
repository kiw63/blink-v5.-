"""Tests of fail-closed evidence checking; fabricated data is NEVER real AI proof."""
from app.ai_release_acceptance import acceptance_report, validate_photo_evidence, validate_video_evidence


def test_missing_real_evidence_is_not_a_pass():
    report = acceptance_report(None, None)
    assert report['status'] == 'NOT_READY'
    assert len(report['blocking_issues']) == 4


def test_resize_only_is_not_accepted_as_ai():
    photo = {
        'status': 'passed', 'engine': 'resize', 'gpu_preflight': {'status': 'passed'},
        'samples': [{'reference': 'a.png', 'passed': True, 'gain_db': 0.0, 'changed_pixels_mean':[0,0,0]}],
        'total_samples': 1, 'passed_samples': 1,
    }
    assert validate_photo_evidence(photo)


def test_video_with_4k_dimensions_but_no_model_is_rejected():
    video = {'target': '4k', 'output_dimensions': [3840,2160], 'video_frames_inferred': 10,
             'output_duration_seconds': 1.0, 'inference_executed': False,
             'quality_verdict': 'NEEDS_HUMAN_REVIEW_AND_REFERENCE_DATASET',
             'mean_difference_from_lanczos':[0,0,0]}
    assert validate_video_evidence(video)


def test_report_rejects_duplicate_samples_and_unreviewed_video():
    fingerprint={'binary':'x','model_bin':'y','model_param':'z'}
    photo={'status':'passed','engine':'real-esrgan-ncnn-vulkan',
           'gpu_preflight':{'status':'passed','engine':'real-esrgan-ncnn-vulkan','model_fingerprint':fingerprint},
           'model_fingerprint':fingerprint, 'passed_samples':5,'total_samples':5,
           'samples':[{'reference':'same.png','passed':True,'gain_db':1.0,'changed_pixels_mean':[1,1,1]}]*5,
           'required_pass_fraction':0.8}
    assert any('duplikat' in msg for msg in validate_photo_evidence(photo))
    video={'inference_executed':True,'engine':'real-esrgan-ncnn-vulkan','target':'4k',
           'output_dimensions':[3840,2160],'video_frames_inferred':10,
           'output_duration_seconds':1,'mean_difference_from_lanczos':[1],
           'quality_verdict':'NEEDS_HUMAN_REVIEW_AND_REFERENCE_DATASET'}
    assert 'Kualitas temporal dan artefak video masih perlu evaluasi nyata' in validate_video_evidence(video)
