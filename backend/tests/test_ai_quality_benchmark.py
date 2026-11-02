"""Math and fail-closed benchmark tests. Fake output is NEVER certified as real AI."""
from pathlib import Path
from PIL import Image
import pytest
from app.ai_quality_benchmark import psnr, evaluate_references


def test_identical_images_have_infinite_psnr():
    im = Image.new('RGB', (16, 16), '#335577')
    assert psnr(im, im) == float('inf')


def test_psnr_rejects_size_mismatch():
    with pytest.raises(ValueError):
        psnr(Image.new('RGB', (16,16)), Image.new('RGB', (8,8)))


def test_missing_real_ai_must_not_be_marked_passed(tmp_path):
    sample=tmp_path/'source.png'
    Image.new('RGB',(512,512),'#445566').save(sample)
    def unavailable(*a,**k):
        raise RuntimeError('no genuine model weights')
    with pytest.raises(RuntimeError,match='no genuine model weights'):
        evaluate_references([sample], verify_engine=False, run_inference=unavailable)


def test_interpolation_only_fails_quality_gate(tmp_path):
    sample=tmp_path/'source.png'
    im=Image.new('RGB',(512,512))
    pix=im.load()
    for y in range(512):
        for x in range(512):
            pix[x,y]=(x%256, y%256, (x+y)%256)
    im.save(sample)
    def resize_only(src,dst,scale):
        with Image.open(src) as inp:
            inp.resize((inp.width*scale, inp.height*scale),Image.Resampling.LANCZOS).save(dst)
    result=evaluate_references([sample],verify_engine=False, run_inference=resize_only)
    assert result['status']=='failed'
    assert not result['samples'][0]['passed']


def test_rejects_missing_or_invalid_reference():
    with pytest.raises(ValueError,match='At least one'):
        evaluate_references([],verify_engine=False)
    with pytest.raises(ValueError,match='positive'):
        evaluate_references([Path('/nonexistent')],minimum_gain_db=0,verify_engine=False)
