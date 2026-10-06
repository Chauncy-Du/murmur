"""Local account metadata and salted password verification; no secret storage."""
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
from pathlib import Path


def password_hash(password):
    if not isinstance(password,str) or not 8<=len(password)<=256:raise ValueError('Use a password with 8–256 characters.')
    salt=secrets.token_bytes(16)
    digest=hashlib.scrypt(password.encode('utf-8'),salt=salt,n=16384,r=8,p=1,dklen=32)
    return {'scheme':'scrypt-v1','salt':salt.hex(),'digest':digest.hex()}


def verify_password(stored,password):
    if stored is None:return True
    if not isinstance(password,str) or len(password)>256:return False
    try:
        if stored['scheme']!='scrypt-v1':return False
        salt=bytes.fromhex(stored['salt']);digest=bytes.fromhex(stored['digest'])
        if len(salt)!=16 or len(digest)!=32:return False
        actual=hashlib.scrypt(password.encode('utf-8'),salt=salt,n=16384,r=8,p=1,dklen=32)
        return hmac.compare_digest(actual,digest)
    except (KeyError,TypeError,ValueError):return False


class ProfileRegistry:
    def __init__(self,root):
        self.root=Path(root).resolve();self.path=self.root/'accounts.json'
        self.records=[dict(id='default',name='Personal',username='personal',password=None)]
        self.current='default'
        if self.path.exists():
            try:
                saved=json.loads(self.path.read_text('utf-8'));records=saved['accounts']
                if not isinstance(records,list) or not 1<=len(records)<=100:raise ValueError()
                ids=set();names=set()
                for record in records:
                    identifier=record['id']
                    if identifier!='default' and not re.fullmatch(r'[a-f0-9]{32}',identifier):raise ValueError()
                    self.validate_name(record['name'],record['username'])
                    if identifier in ids or record['username'].casefold() in names:raise ValueError()
                    ids.add(identifier);names.add(record['username'].casefold())
                    if record['password'] is not None:
                        password=record['password']
                        if password.get('scheme')!='scrypt-v1' or not re.fullmatch(r'[a-f0-9]{32}',password.get('salt','')) or not re.fullmatch(r'[a-f0-9]{64}',password.get('digest','')):raise ValueError()
                if 'default' not in ids or saved['current'] not in ids:raise ValueError()
                self.records=records;self.current=saved['current']
            except (ValueError,TypeError,KeyError,AttributeError):
                raise ValueError('Account metadata could not be read. The original file has been preserved; restore accounts.json from your backup.') from None

    @staticmethod
    def validate_name(name,username):
        if not isinstance(name,str) or not 1<=len(name.strip())<=32 or any(ord(c)<32 for c in name):raise ValueError('Display name must contain 1–32 visible characters.')
        if not isinstance(username,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{2,31}',username):raise ValueError('Account name: 3–32 letters, numbers, dots, underscores or hyphens.')

    def get(self,identifier):
        return next(record for record in self.records if record['id']==identifier)

    def folder(self,identifier):
        self.get(identifier)
        return self.root if identifier=='default' else self.root/'profiles'/identifier

    def save(self):
        self.root.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.tmp')
        with temporary.open('w',encoding='utf-8') as stream:
            json.dump({'version':1,'current':self.current,'accounts':self.records},stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,self.path)

    def create(self,name,username,password):
        name=name.strip();username=username.strip();self.validate_name(name,username)
        if any(r['username'].casefold()==username.casefold() for r in self.records):raise ValueError('That account name is already in use.')
        if len(self.records)>=100:raise ValueError('The local account limit has been reached.')
        record=dict(id=uuid.uuid4().hex,name=name,username=username,password=password_hash(password))
        self.records.append(record)
        try:self.save()
        except Exception:self.records.pop();raise
        return record

    def authenticate(self,identifier,password):return verify_password(self.get(identifier)['password'],password)

    def activate(self,identifier,password):
        if not self.authenticate(identifier,password):raise ValueError('Incorrect password.')
        previous=self.current;self.current=identifier
        try:self.save()
        except Exception:self.current=previous;raise

    def edit(self,identifier,name,username,current_password,new_password=''):
        if not self.authenticate(identifier,current_password):raise ValueError('Incorrect current password.')
        name=name.strip();username=username.strip();self.validate_name(name,username)
        if any(r['id']!=identifier and r['username'].casefold()==username.casefold() for r in self.records):raise ValueError('That account name is already in use.')
        new_hash=password_hash(new_password) if new_password else None
        record=self.get(identifier);previous=copy.deepcopy(record)
        record.update(name=name,username=username)
        if new_hash:record['password']=new_hash
        try:self.save()
        except Exception:record.clear();record.update(previous);raise
