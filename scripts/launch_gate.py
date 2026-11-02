#!/usr/bin/env python3
"""BLINK H-1 read-only production smoke test. No fake AI or bank payment claims.

Usage: python scripts/launch_gate.py --site https://USER.github.io/blink/ \
    --api https://api.example.com --admin https://admin.example.com \
    --report launch-result.json

Does not submit payments, log in, debit users, or upload media. A successful
HTTP/config smoke test is NOT evidence of AI image quality or settled funds.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urljoin
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT=Path(__file__).resolve().parents[1]
LIMIT=1024*1024*4


def require_https(value, name):
    parsed=urlsplit(value)
    if parsed.scheme!='https' or not parsed.netloc or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f'{name} must be a public HTTPS URL without credentials, query or fragment')
    if name!='site' and parsed.path not in ('','/'):
        raise ValueError(f'{name} must be a bare HTTPS origin')
    return value.rstrip('/')+('/' if name=='site' else '')


def get(url, origin=None, content_type=None):
    req=Request(url,headers={'User-Agent':'BLINK-read-only-go-live-check/1.0', **({'Origin':origin} if origin else {})})
    with urlopen(req,timeout=18) as response:
        code=response.status; final=response.url
        if urlsplit(final).netloc!=urlsplit(url).netloc:
            raise RuntimeError('Unexpected cross-host redirect')
        body=response.read(LIMIT+1)
        if len(body)>LIMIT:
            raise RuntimeError('Response unexpectedly large')
        typ=response.headers.get('Content-Type','')
        if content_type and content_type not in typ:
            raise RuntimeError(f'Expected content type {content_type}, got {typ}')
        return code,body,response.headers


def check(name, fn, results):
    try:
        details=fn()
        results[name]={'status':'PASS','evidence':details}
    except Exception as exc:
        results[name]={'status':'FAIL','reason':str(exc)[:320]}


def validate_site(site,api):
    code,html,headers=get(site,content_type='text/html')
    text=html.decode('utf-8',errors='replace')
    if code!=200 or 'BLINK' not in text or 'intro-enter' not in text:
        raise RuntimeError('BLINK landing page is missing or incomplete')
    if 'https://t.me/Marvel_sh' not in text:
        raise RuntimeError('Developer link not present in published page')
    assets=['assets/app.js','assets/media.js','assets/intro.js','assets/style.css','assets/logo.png','assets/config.js','assets/qris-nanzera.jpg']
    for asset in assets:
        _,data,_=get(urljoin(site,asset))
        if not data: raise RuntimeError('Empty website asset: '+asset)
    _,config,_=get(urljoin(site,'assets/config.js'))
    configtext=config.decode('utf-8',errors='replace')
    if api not in configtext:
        raise RuntimeError('Published browser API configuration does not point at this backend HTTPS origin')
    return {'page_http':code,'assets_checked':len(assets),'api_origin_in_config':True}


def validate_backend(api,site):
    origin=urlsplit(site).scheme+'://'+urlsplit(site).netloc
    _,data,headers=get(api+'/api/health',origin=origin,content_type='application/json')
    health=json.loads(data)
    if health.get('status')!='ok' or health.get('service')!='BLINK API':
        raise RuntimeError('Wrong backend health result')
    cors=headers.get('Access-Control-Allow-Origin')
    if cors!=origin:
        raise RuntimeError(f'Browser CORS denied GitHub Pages origin (expected {origin}, got {cors})')
    return {'api_version':health.get('api_version'),'cors_origin':cors}


def capabilities(api,site):
    origin=urlsplit(site).scheme+'://'+urlsplit(site).netloc
    _,data,headers=get(api+'/api/public/capabilities',origin=origin,content_type='application/json')
    obj=json.loads(data)
    if headers.get('Access-Control-Allow-Origin')!=origin:
        raise RuntimeError('Capabilities endpoint has incorrect CORS')
    return obj


def validate_ai(obj):
    services=obj.get('services',{})
    if not services.get('ai_models_installed'):
        raise RuntimeError('Genuine model artifacts not installed on deployed backend')
    if not services.get('ai_gpu_verified'):
        raise RuntimeError('Real-ESRGAN inference verification is missing, stale, or failed')
    return {'model_installed':True,'inference_preflight':True,
            'warning':'Model preflight is not a quality test on real photo/video samples'}


def validate_qris(api,obj):
    if not obj.get('services',{}).get('qris_image_configured'):
        raise RuntimeError('QRIS backend not configured')
    _,data,headers=get(api+'/api/public/qris',content_type='image/jpeg')
    reference=ROOT/'backend/assets/qris-nanzera.jpg'
    if not reference.is_file():raise RuntimeError('QRIS original reference asset missing in repository')
    expected=hashlib.sha256(reference.read_bytes()).hexdigest()
    actual=hashlib.sha256(data).hexdigest()
    if expected!=actual:
        raise RuntimeError('Backend QRIS differs from the owner-supplied QRIS in this repository')
    return {'reference_sha256':expected,'backend_qris_matches_repository':True,
            'warning':'Image match does NOT prove merchant bank settlement or provider validity'}


def validate_payment_config(obj):
    if not obj.get('services',{}).get('email_configured'):
        raise RuntimeError('SMTP configuration absent; customer verification cannot be completed')
    premium=obj.get('premium',{})
    if premium.get('price_idr')!=20000 or premium.get('tokens')!=20 or premium.get('duration_days')!=30:
        raise RuntimeError('Deployed Premium terms do not match BLINK contract')
    return {'premium_terms':premium,'email_configured':True,
            'warning':'SMTP configured does NOT prove email delivery or a real paid order'}


def validate_admin(admin):
    status,data,_=get(admin+'/admin')
    if status!=200:raise RuntimeError(f'Unexpected admin HTTP {status}')
    if b'__NEXT_DATA__' not in data and b'_next/' not in data and b'BLINK' not in data:
        raise RuntimeError('Admin URL does not look like BLINK Next.js')
    return {'admin_route_reachable':True,
            'warning':'Browser admin login, MFA and manual payment approval still need separate verified end-to-end testing'}


def main(argv=None):
    parser=argparse.ArgumentParser(description='Read-only production readiness assessment; FAIL CLOSED')
    parser.add_argument('--site',required=True,help='Full published GitHub Pages site URL with repository path')
    parser.add_argument('--api',required=True,help='Public backend HTTPS origin')
    parser.add_argument('--admin',required=True,help='Public Next.js admin HTTPS origin')
    parser.add_argument('--report',default='BLINK_LAUNCH_GATE_RESULT.json')
    args=parser.parse_args(argv)
    site=require_https(args.site,'site');api=require_https(args.api,'api');admin=require_https(args.admin,'admin')
    results={}
    check('website_public_and_assets',lambda:validate_site(site,api),results)
    check('backend_and_browser_cors',lambda:validate_backend(api,site),results)
    obj={}
    try:obj=capabilities(api,site)
    except Exception as exc:results['capabilities']={'status':'FAIL','reason':str(exc)[:320]}
    else: results['capabilities']={'status':'PASS','evidence':{'api_version':obj.get('api_version')}}
    if obj:
        check('real_ai_inference_preflight',lambda:validate_ai(obj),results)
        check('owner_qris_asset',lambda:validate_qris(api,obj),results)
        check('premium_and_email_config',lambda:validate_payment_config(obj),results)
    else:
        for item in ('real_ai_inference_preflight','owner_qris_asset','premium_and_email_config'):
            results[item]={'status':'BLOCKED','reason':'Capabilities unavailable'}
    check('admin_route_public',lambda:validate_admin(admin),results)
    for manual in ('ai_photo_video_real_quality_4k','real_qris_bank_settlement_and_admin_approval',
                   'customer_live_account_email_and_download','mobile_physical_device_acceptance',
                   'production_security_and_backup_review'):
        results[manual]={'status':'MANUAL_REQUIRED','reason':'Cannot be verified with read-only HTTP probe'}
    automated=all(v['status']=='PASS' for k,v in results.items() if k not in (
       'ai_photo_video_real_quality_4k','real_qris_bank_settlement_and_admin_approval',
       'customer_live_account_email_and_download','mobile_physical_device_acceptance',
       'production_security_and_backup_review'))
    report={'checked_at_utc':datetime.now(timezone.utc).isoformat(), 'site':site,'api':api,'admin':admin,
            'automated_smoke_passed':automated,'commercial_go_live_verified':False,
            'reason':'Commercial readiness requires additional real AI quality, real payment, mobile, and security evidence',
            'results':results}
    target=Path(args.report);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2,ensure_ascii=False))
    return 0 if automated else 1

if __name__=='__main__':sys.exit(main())
