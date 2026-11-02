import os, shutil, mimetypes
from pathlib import Path
from tempfile import NamedTemporaryFile
from fastapi import HTTPException
from .config import settings

class Storage:
    def __init__(self):
        self.remote=bool(settings.s3_bucket)
        if self.remote:
            import boto3
            self.s3=boto3.client('s3',region_name=settings.s3_region,
                endpoint_url=settings.s3_endpoint_url or None,
                aws_access_key_id=settings.s3_access_key or None,
                aws_secret_access_key=settings.s3_secret_key or None)
        else:
            self.root=Path(settings.media_root)
            self.root.mkdir(parents=True,exist_ok=True)
    def path(self,key):
        if '..' in key or key.startswith('/') or '\\' in key: raise ValueError('Unsafe key')
        p=(self.root/key).resolve()
        if not p.is_relative_to(self.root.resolve()): raise ValueError('Unsafe key')
        return p
    def put_file(self,key,path):
        if self.remote:
            self.s3.upload_file(str(path),settings.s3_bucket,key,ExtraArgs={'ServerSideEncryption':'AES256',
                'ContentType':mimetypes.guess_type(key)[0] or 'application/octet-stream'})
        else:
            target=self.path(key); target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,target)
    def copy_to(self,key,path):
        if self.remote: self.s3.download_file(settings.s3_bucket,key,str(path))
        else: shutil.copyfile(self.path(key),path)
    def get_download(self,key,filename,inline=False):
        if self.remote:
            url=self.s3.generate_presigned_url('get_object',Params={'Bucket':settings.s3_bucket,'Key':key,'ResponseContentDisposition':f'{"inline" if inline else "attachment"}; filename="{filename}"'},ExpiresIn=120)
            return {'url':url}
        return {'path':str(self.path(key))}
    def remove(self,key):
        if self.remote: self.s3.delete_object(Bucket=settings.s3_bucket,Key=key)
        else: self.path(key).unlink(missing_ok=True)
