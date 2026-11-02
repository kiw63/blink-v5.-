"""Conservative photo pre/post-processing for the real AI super-resolution pipeline.

These image operations are ordinary image adjustments, NOT AI models. Genuine
reconstruction is performed solely by app.ai_engine.inference.
"""
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat

MAX_SOURCE_SIDE = 4096  # Bound huge (up to 32MP) uploads before x2/x4 inference.


def analyze_photo(im):
    thumbnail=ImageOps.exif_transpose(im).convert('RGB')
    thumbnail.thumbnail((320,320))
    gray=thumbnail.convert('L')
    lum=ImageStat.Stat(gray)
    # Edge magnitude is a diagnostic only; do not over-sharpen smooth portraits.
    edges=gray.filter(ImageFilter.FIND_EDGES)
    return {'luminance':round(lum.mean[0],2),
            'contrast':round(lum.stddev[0],2),
            'edge_magnitude':round(ImageStat.Stat(edges).mean[0],2)}


def prepare_photo(original, prepared_path, mode='auto'):
    """Orient/safely cap huge input, lift genuinely dark scenes conservatively."""
    with Image.open(original) as raw:
        raw.load()
        image=ImageOps.exif_transpose(raw).convert('RGB')
    before=analyze_photo(image)
    # Any input already larger than 4K is reduced only to safe 4K processing
    # dimensions. The full original remains in private storage untouched.
    if max(image.size)>MAX_SOURCE_SIDE:
        image.thumbnail((MAX_SOURCE_SIDE,MAX_SOURCE_SIDE),Image.Resampling.LANCZOS)
    if mode in ('auto','night') and before['luminance']<58:
        # Tone lift is not a substitute for learned low-light reconstruction.
        ratio=min(1.35,max(1.0,70/max(1,before['luminance'])))
        image=ImageEnhance.Brightness(image).enhance(ratio)
    image.save(prepared_path,format='PNG')
    return before, image.size


def choose_inference_scale(source_size,requested_side):
    """Skip unnecessary x4 output when x2 already reaches target resolution."""
    side=max(source_size)
    if requested_side and side*2>=requested_side:
        return 2
    if side>=1920:
        return 2
    return 4


def photo_target_side(mode,target):
    return {'4k':3840,'2k':2560,'1080p':1920}.get(target,3840 if mode=='4k' else 2560 if mode=='hd' else 0)
