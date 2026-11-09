#!/usr/bin/env python3
"""Local, content-addressed native agent session backup. Python standard library."""
import argparse, base64, contextlib, datetime, hashlib, html, io, json, ntpath, os, platform, plistlib, re, secrets, shutil, sqlite3, subprocess, sys, tempfile, time, webbrowser, zipfile
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse
import xml.etree.ElementTree as ET

def dump(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)
def sha(b): return hashlib.sha256(b).hexdigest()
def atomic_write(path,data,mode=0o600):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 if os.name!='nt':os.chmod(path.parent,0o700)
 fd,tmp=tempfile.mkstemp(prefix='.'+path.name+'.tmp-',dir=path.parent)
 try:
  with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
  if os.name!='nt':os.chmod(tmp,mode)
  os.replace(tmp,path)
  if os.name!='nt':
   try:
    dfd=os.open(path.parent,os.O_RDONLY);os.fsync(dfd);os.close(dfd)
   except OSError:pass
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def title_for(record, sid, fields=('name','title','preview','first_user_message')):
 for key in fields:
  value=record.get(key)
  if isinstance(value,str) and value.strip():return value.strip(),key
 return sid,'id'
def session_title_source(session):
 if session.get('title_source'):return session['title_source']
 rows=(session.get('record') or {}).get('tables',{}).get('threads',[])
 if rows:return title_for(rows[0],session.get('id','id'))[1]
 return 'stored title' if session.get('title') else 'id'
def enc(x):
 if isinstance(x,bytes): return {'$blob':base64.b64encode(x).decode()}
 return x
def dec(x):
 return base64.b64decode(x['$blob']) if isinstance(x,dict) and set(x)=={'$blob'} else x
def connect(p):
 c=sqlite3.connect(p); c.row_factory=sqlite3.Row; return c
def snapshot(p):
 c=sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True); d=sqlite3.connect(':memory:');c.backup(d);c.close();d.row_factory=sqlite3.Row;return d
def sqlite_bytes(c):
 fd,tmp=tempfile.mkstemp(prefix='session-vault-db-',suffix='.sqlite');os.close(fd)
 try:
  d=sqlite3.connect(tmp)
  try:c.backup(d)
  finally:d.close()
  return Path(tmp).read_bytes()
 finally:
  try:os.unlink(tmp)
  except FileNotFoundError:pass
def tables(c): return [r[0] for r in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' and sql not like '%VIRTUAL TABLE%'")]
def rows(c,t,where='',args=()): return [{k:enc(v) for k,v in dict(r).items()} for r in c.execute('SELECT * FROM "'+t.replace('"','""')+'" '+where,args)]
def cols(c,t): return [r[1] for r in c.execute('PRAGMA table_info("'+t.replace('"','""')+'")')]
def put(root,b):
 h=sha(b);p=root/'objects'/h[:2]/h;p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():
  try:
   if sha(p.read_bytes())==h:return h
  except OSError:pass
 atomic_write(p,b)
 if sha(p.read_bytes())!=h:raise ValueError('Object write verification failed: '+h)
 return h
def get(root,h):
 if not re.fullmatch('[0-9a-f]{64}',h):raise ValueError('Invalid object hash')
 b=(root/'objects'/h[:2]/h).read_bytes()
 if sha(b)!=h:raise ValueError('Corrupt object '+h)
 return b
def stable(p):
 a=p.stat();b=p.read_bytes();z=p.stat()
 if (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)!=(z.st_dev,z.st_ino,z.st_size,z.st_mtime_ns,z.st_ctime_ns):raise ValueError('Session changed during backup; retry when idle: '+str(p))
 return b

PROFILE_TREES={
 'codex':['memories','rules','skills','prompts'],
 'claude':['rules','skills','commands','agents'],
 'hermes':['memories','skills','prompts'],
 'pi':['skills','prompts','extensions','themes'],
 'codebuddy':['agents','rules','skills','commands','memories/global'],
 'zcode':['agents','skills','commands'],
 'agents':['skills'],
}
PROFILE_FILES={
 'codex':['AGENTS.md','config.toml'],
 'claude':['CLAUDE.md','settings.json','settings.local.json'],
 'hermes':['SOUL.md','AGENTS.md','USER.md','MEMORY.md','config.yaml','config.yml'],
 'pi':['AGENTS.md','AGENTS.override.md','CLAUDE.md','SYSTEM.md','APPEND_SYSTEM.md','settings.json','keybindings.json'],
 'codebuddy':['CODEBUDDY.md','settings.json','settings.local.json'],
 'zcode':['AGENTS.md','cli/config.json','v2/config.json','v2/credentials.json','v2/telemetry-state.json'],
 'agents':['AGENTS.md'],
}
PROFILE_EXCLUDE_PATHS={'zcode':{'v2/telemetry-state.json'}}
PROFILE_SKIP_DIRS={'.git','.locks','.system','.credentials','node_modules','__pycache__','cache','logs','pending','sessions','auth','credentials','tokens'}
SENSITIVE_FILENAME=re.compile(r'^(?:\.env(?:\..*)?|\.npmrc|\.netrc|auth(?:entication)?(?:\..*)?|credentials?(?:\..*)?|secrets?(?:\..*)?|tokens?(?:\..*)?|oauth(?:\..*)?|private[_-]?key(?:\..*)?|id_rsa(?:\..*)?|id_ed25519(?:\..*)?|.*\.(?:pem|p12|pfx|key|keystore))$',re.I)
SENSITIVE_VALUE=re.compile(r'''(?im)["']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|password|client[_-]?secret|secret[_-]?key|credentials?)["']?\s*[:=]\s*["']?([^"'\s,;}]+)''')
TOKEN_VALUE=re.compile(r'(?i)\b(?:Bearer\s+[A-Za-z0-9._~+/=-]{16,}|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|AKIA[A-Z0-9]{16})')
def sensitive_content(data):
 try:text=data.decode('utf-8')
 except UnicodeDecodeError:return False
 for match in SENSITIVE_VALUE.finditer(text):
  value=match.group(1).strip().strip('"\'')
  if value and value.lower() not in {'null','none','false','true','changeme','your_api_key','<redacted>'} and not value.startswith(('$','${','%')):return True
 return bool(TOKEN_VALUE.search(text))
def collect_profile_files(provider,home):
 home=Path(home).expanduser().resolve();candidates=[]
 for name in PROFILE_FILES.get(provider,[]):
  p=home/name
  if p.is_file() and not p.is_symlink():candidates.append(p)
 for tree in PROFILE_TREES.get(provider,[]):
  base=home/tree
  if not base.is_dir() or base.is_symlink():continue
  for p in base.rglob('*'):
   try:rel=p.relative_to(base)
   except ValueError:continue
   if p.is_symlink() or any(part in PROFILE_SKIP_DIRS for part in rel.parts):continue
   if p.is_file():candidates.append(p)
 if provider=='claude':
  for base in (home/'projects').glob('*/memory'):
   if base.is_dir():candidates.extend(p for p in base.rglob('*') if p.is_file() and not p.is_symlink() and not any(x in PROFILE_SKIP_DIRS for x in p.relative_to(home).parts))
 return sorted(set(candidates))

def parse_jsonl(path):
 raw=stable(path);data=raw.decode('utf-8');records=[]
 for number,line in enumerate(data.splitlines(),1):
  if not line.strip():continue
  try:record=json.loads(line)
  except Exception as e:raise ValueError('Invalid JSONL at '+str(path)+':'+str(number)+': '+str(e)) from e
  if not isinstance(record,dict):raise ValueError('JSONL entry must be an object at '+str(path)+':'+str(number))
  records.append(record)
 return raw,records

def text_value(value):
 if isinstance(value,str):return value.strip()
 if isinstance(value,list):return ' '.join(x for x in (text_value(v) for v in value) if x)
 if isinstance(value,dict):
  if isinstance(value.get('text'),str):return value['text'].strip()
  for key in ('content','message','prompt','text'):
   if key in value:
    found=text_value(value[key])
    if found:return found
 return ''

def first_user_text(records):
 for record in records:
  message=record.get('message')
  if isinstance(message,dict) and message.get('role') in {'user','human'}:
   found=text_value(message.get('content'))
   if found:return found[:240]
  if record.get('role') in {'user','human'} or record.get('type') in {'user','human'}:
   found=text_value(record.get('content',record.get('message',record.get('prompt'))))
   if found:return found[:240]
 return ''

CODEBUDDY_CN_SCHEMA='codebuddy.conversation'
CODEBUDDY_CN_VERSION=1
CODEBUDDY_CN_MAX_JSON_BYTES=20*1024*1024
CODEBUDDY_CN_MAX_ZIP_BYTES=1024*1024*1024
CODEBUDDY_CN_MAX_ZIP_ENTRIES=10000
CODEBUDDY_CN_ID=re.compile(r'^[a-zA-Z0-9_-]+$')
def _cbcn_json_value(value):
 if value is None or isinstance(value,(str,bool)):return True
 if isinstance(value,(int,float)):return not isinstance(value,float) or __import__('math').isfinite(value)
 if isinstance(value,list):return all(_cbcn_json_value(x) for x in value)
 if isinstance(value,dict):return all(_cbcn_json_value(x) for x in value.values())
 return False
def validate_codebuddy_cn_archive(raw,label='CodeBuddy CN archive'):
 if len(raw)>CODEBUDDY_CN_MAX_JSON_BYTES:raise ValueError(label+': JSON entry exceeds the CodeBuddy CN 20 MiB import limit')
 try:archive=json.loads(raw.decode('utf-8'))
 except Exception as e:raise ValueError(label+': invalid UTF-8 JSON: '+str(e)) from e
 if not _cbcn_json_value(archive):raise ValueError(label+': JSON contains a non-finite or unsupported value')
 def invalid(message):raise ValueError(label+': '+message)
 if not isinstance(archive,dict) or archive.get('schema')!=CODEBUDDY_CN_SCHEMA:invalid('unsupported archive schema')
 if archive.get('schemaVersion')!=CODEBUDDY_CN_VERSION:invalid('unsupported archive version')
 if not isinstance(archive.get('exportedAt'),str):invalid('exportedAt must be a string')
 data=archive.get('data')
 if not isinstance(data,dict) or not isinstance(data.get('lastMessageAt'),str):invalid('data.lastMessageAt must be a string')
 conversations=data.get('conversations')
 if not isinstance(conversations,list) or len(conversations)!=1:invalid('archive must contain exactly one conversation')
 conv=conversations[0]
 if not isinstance(conv,dict):invalid('conversation must be an object')
 def valid_id(value):return isinstance(value,str) and bool(CODEBUDDY_CN_ID.fullmatch(value))
 if not valid_id(conv.get('id')):invalid('conversation id is invalid')
 for key in ('type','name','createdAt','lastMessageAt'):
  if not isinstance(conv.get(key),str):invalid('conversation.'+key+' must be a string')
 requests=conv.get('requests')
 if not isinstance(requests,list):invalid('conversation.requests must be an array')
 request_ids=set();message_ids=set()
 for request in requests:
  if not isinstance(request,dict) or not valid_id(request.get('id')):invalid('request id is invalid')
  if request['id'] in request_ids:invalid('duplicate request id')
  request_ids.add(request['id'])
  state=request.get('state')
  if not isinstance(request.get('type'),str) or not isinstance(state,str) or state not in {'running','complete','aborted','canceled'}:invalid('request type or state is invalid')
  messages=request.get('messages')
  if not isinstance(messages,list):invalid('request.messages must be an array')
  for message in messages:
   role=message.get('role') if isinstance(message,dict) else None
   if not isinstance(message,dict) or not valid_id(message.get('id')) or not isinstance(role,str) or role not in {'user','assistant','tool','system'} or not isinstance(message.get('message'),str):invalid('message id, role or body is invalid')
   if message['id'] in message_ids:invalid('duplicate message id')
   message_ids.add(message['id'])
   status=message.get('status')
   if 'status' in message and (not isinstance(status,str) or status not in {'active','deprecate','deleted'}):invalid('message status is invalid')
   if 'extra' in message and not isinstance(message.get('extra'),str):invalid('message extra must be a string')
   if 'isNewFile' in message and not isinstance(message.get('isNewFile'),bool):invalid('message isNewFile must be a boolean')
   refs=message.get('references')
   if 'references' in message and (not isinstance(refs,list) or any(not isinstance(x,dict) or not isinstance(x.get('type'),str) or not _cbcn_json_value(x) for x in refs)):invalid('message references are invalid')
  usage=request.get('usage')
  if usage is not None:
   fields=('inputTokens','outputTokens','totalTokens','lastTokens','cacheTokens','cachedWriteTokens','cachedMissTokens','credit')
   if not isinstance(usage,dict) or any(k in usage and (not isinstance(usage[k],(int,float)) or isinstance(usage[k],bool) or isinstance(usage[k],float) and not __import__('math').isfinite(usage[k])) for k in fields):invalid('request usage is invalid')
 for key in ('originalId',):
  if key in conv and not isinstance(conv[key],str):invalid('conversation.'+key+' must be a string')
 for key in ('modelMap','effortMap','contextLengthMap'):
  if key in conv and (not isinstance(conv[key],dict) or any(not isinstance(v,str) for v in conv[key].values())):invalid('conversation.'+key+' is invalid')
 if 'maxModeMap' in conv and (not isinstance(conv['maxModeMap'],dict) or any(not isinstance(v,bool) for v in conv['maxModeMap'].values())):invalid('conversation.maxModeMap is invalid')
 if 'nameSource' in conv and (not isinstance(conv['nameSource'],str) or conv['nameSource'] not in {'user','auto'}):invalid('conversation.nameSource is invalid')
 return archive,conv
def codebuddy_cn_workspace(conv):
 def visit(value):
  if isinstance(value,dict):
   for key in ('cwd','working_directory','workingDirectory','workdir','projectPath','project_path','workspace_path'):
    path=value.get(key)
    if isinstance(path,str) and absolute_path(path):return path
   for key,child in value.items():
    if key in {'messages','message','content','text','extra'}:continue
    found=visit(child)
    if found:return found
  elif isinstance(value,list):
   for child in value:
    found=visit(child)
    if found:return found
  return ''
 return visit(conv)
def codebuddy_cn_label(conv):
 name=conv.get('name')
 if isinstance(name,str) and name.strip():return name.strip(),'name'
 for request in conv.get('requests',[]):
  for message in request.get('messages',[]):
   if message.get('role')=='user' and message.get('message','').strip():return message['message'].strip()[:240],'first_user_message'
 return conv.get('id','CodeBuddy CN session'),'id'

def session_file_label(provider,records,sid):
 for record in records:
  kind=str(record.get('type','')).lower()
  if provider=='pi' and kind=='session_info':
   label=record.get('name') or record.get('title')
   if isinstance(label,str) and label.strip():return label.strip(),'name' if record.get('name') else 'title'
  if provider=='codebuddy' and kind in {'session_info','session_name','session_title','summary'}:
   for key in ('name','title','customTitle','summary'):
    label=record.get(key)
    if isinstance(label,str) and label.strip():return label.strip(),key
  if kind in {'session_info','session_name','session_title','summary'}:
   for key in ('name','title','customTitle','summary'):
    label=record.get(key)
    if isinstance(label,str) and label.strip():return label.strip(),key
 first=first_user_text(records)
 return (first,'first_user_message') if first else (sid,'id')

def pi_session_directory(cwd):
 if ntpath.splitdrive(cwd)[0] or '\\' in cwd:
  resolved=ntpath.normpath(cwd)
  encoded=re.sub(r'[/\\:]','-',resolved.lstrip('/\\'))
 else:
  resolved=os.path.normpath(cwd)
  encoded=re.sub(r'[/\\:]','-',resolved.lstrip('/\\'))
 return '--'+encoded+'--'
def verify_snapshot(root,folder):
 root=Path(root);folder=Path(folder);errors=[]
 try:
  raw=(folder/'manifest.json').read_bytes();manifest=json.loads(raw)
 except Exception as e:return {'snapshot':str(folder),'restorable':False,'complete':False,'errors':['manifest unreadable: '+str(e)],'warnings':[]}
 if not isinstance(manifest,dict):return {'snapshot':str(folder),'restorable':False,'complete':False,'errors':['manifest root must be an object'],'warnings':[]}
 if manifest.get('version')!=1:errors.append('unsupported manifest version')
 object_count=0
 def check_hash(label,h):
  nonlocal object_count
  try:get(root,h);object_count+=1
  except Exception as e:errors.append(label+': '+str(e))
 sessions=manifest.get('sessions')
 if not isinstance(sessions,list):errors.append('manifest sessions must be a list');sessions=[]
 for s in sessions:
  if not isinstance(s,dict):errors.append('invalid session entry');continue
  label=str(s.get('provider','?'))+'/'+str(s.get('title') or s.get('id') or '?')
  if s.get('provider') not in {'codex','claude','hermes','pi','codebuddy','codebuddy-cn'}:errors.append(label+': unknown provider')
  if not isinstance(s.get('files',[]),list):errors.append(label+': files must be a list');continue
  cn_files=s.get('files',[])
  if s.get('provider')=='codebuddy-cn' and (len(cn_files)!=1 or not isinstance(cn_files[0],dict) or not str(cn_files[0].get('path','')).lower().endswith('.json')):errors.append(label+': CodeBuddy CN session must contain exactly one JSON archive')
  for f in s.get('files',[]):
   if not isinstance(f,dict):errors.append(label+': invalid file entry');continue
   h=f.get('hash','');check_hash(label,h)
   if str(f.get('path','')).lower().endswith('.jsonl'):
    try:
     data=get(root,h).decode('utf-8')
     for n,line in enumerate(data.splitlines(),1):
      if line.strip():json.loads(line)
    except Exception as e:errors.append(label+': invalid JSONL: '+str(e))
   if s.get('provider')=='codebuddy-cn' and str(f.get('path','')).lower().endswith('.json'):
    try:validate_codebuddy_cn_archive(get(root,h),label)
    except Exception as e:errors.append(label+': invalid CodeBuddy CN archive: '+str(e))
 native_dbs=manifest.get('native_databases',[])
 if not isinstance(native_dbs,list):errors.append('manifest native_databases must be a list');native_dbs=[]
 for d in native_dbs:
  if not isinstance(d,dict):errors.append('invalid native database entry');continue
  label=str(d.get('provider','?'))+'/'+str(d.get('path','state DB'));h=d.get('hash','')
  tmp=None;c=None
  try:
   data=get(root,h);fd,tmp=tempfile.mkstemp(prefix='session-vault-verify-',suffix='.sqlite');os.close(fd);Path(tmp).write_bytes(data)
   c=sqlite3.connect(Path(tmp).resolve().as_uri()+'?mode=ro',uri=True)
   check=c.execute('PRAGMA quick_check').fetchone()[0]
   names={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")};c.close();c=None
   if check!='ok':errors.append(label+': SQLite quick_check returned '+str(check))
   missing=set(d.get('required_tables',[]))-names
   if missing:errors.append(label+': missing tables '+', '.join(sorted(missing)))
  except Exception as e:errors.append(label+': invalid SQLite snapshot: '+str(e))
  finally:
   if c:
    try:c.close()
    except sqlite3.Error:pass
   if tmp:
    try:os.unlink(tmp)
    except OSError:pass
 profile_files=manifest.get('profile_files',[])
 if not isinstance(profile_files,list):errors.append('manifest profile_files must be a list');profile_files=[]
 for f in profile_files:
  if not isinstance(f,dict):errors.append('invalid profile file entry');continue
  check_hash('profile/'+str(f.get('path','?')),f.get('hash',''))
 extras=manifest.get('extras',[])
 if not isinstance(extras,list):errors.append('manifest extras must be a list');extras=[]
 for f in extras:
  if not isinstance(f,dict):errors.append('invalid extra file entry');continue
  check_hash('extra/'+str(f.get('source','?')),f.get('hash',''))
 warnings=manifest.get('warnings',[])
 if not isinstance(warnings,list):errors.append('manifest warnings must be a list');warnings=[]
 return {'snapshot':str(folder),'session_count':len(sessions),'native_database_count':len(native_dbs),'profile_file_count':len(profile_files),'object_count':object_count,'restorable':not errors,'complete':not errors and not warnings,'errors':errors,'warnings':warnings,'manifest_sha256':sha(raw)}

def safe_part(value):return re.sub(r'[^A-Za-z0-9_.-]','_',str(value))
def head_path(root,host):return Path(root)/'heads'/(safe_part(host)+'.json')
def previous_manifest(root,host):
 try:
  root=Path(root);pointer=json.loads(head_path(root,host).read_text());folder=(root/pointer['snapshot_rel']).resolve();folder.relative_to(root.resolve())
  raw=(folder/'manifest.json').read_bytes()
  if sha(raw)!=pointer.get('manifest_sha256'):return None
  manifest=json.loads(raw)
  return manifest if isinstance(manifest,dict) else None
 except Exception:return None
def matching_ack(root,folder,manifest,manifest_hash,receiver=None):
 origin=safe_part(manifest.get('host',''));sid=Path(folder).name
 ack_dir=Path(root)/'acks'/origin/sid
 if not ack_dir.is_dir():return None
 for p in sorted(ack_dir.glob('*.json')):
  if receiver and p.stem!=safe_part(receiver):continue
  try:
   ack=json.loads(p.read_text())
   if ack.get('snapshot_id')==sid and ack.get('manifest_sha256')==manifest_hash and ack.get('origin_host')==manifest.get('host') and safe_part(ack.get('receiver_host',''))==p.stem:return p
  except Exception:continue
 return None
def referenced_hashes(root):
 refs=set()
 for p in Path(root).glob('snapshots/*/*/manifest.json'):
  try:m=json.loads(p.read_text())
  except Exception as e:raise ValueError('Cannot safely collect objects because a manifest is unreadable: '+str(p)) from e
  for s in m.get('sessions',[]):
   for f in s.get('files',[]):
    if isinstance(f,dict) and re.fullmatch('[0-9a-f]{64}',str(f.get('hash',''))):refs.add(f['hash'])
  for key in ('native_databases','profile_files','extras'):
   for f in m.get(key,[]):
    if isinstance(f,dict) and re.fullmatch('[0-9a-f]{64}',str(f.get('hash',''))):refs.add(f['hash'])
 return refs
def prune_acknowledged(root,host):
 root=Path(root);hp=head_path(root,host)
 if not hp.is_file():return {'acknowledged':False,'removed_snapshots':0,'removed_objects':0}
 try:
  pointer=json.loads(hp.read_text());folder=(root/pointer['snapshot_rel']).resolve();folder.relative_to(root.resolve())
  raw=(folder/'manifest.json').read_bytes();manifest=json.loads(raw);manifest_hash=sha(raw)
  if manifest_hash!=pointer.get('manifest_sha256'):return {'acknowledged':False,'removed_snapshots':0,'removed_objects':0,'reason':'head manifest hash mismatch'}
  report=verify_snapshot(root,folder)
  if not report['complete']:return {'acknowledged':False,'removed_snapshots':0,'removed_objects':0,'reason':'head snapshot no longer verifies'}
  receipt=matching_ack(root,folder,manifest,manifest_hash)
  if not receipt:return {'acknowledged':False,'removed_snapshots':0,'removed_objects':0}
 except Exception as e:return {'acknowledged':False,'removed_snapshots':0,'removed_objects':0,'reason':str(e)}
 home=root/'snapshots'/str(host);removed=0
 if home.is_dir() and not home.is_symlink():
  for old in home.iterdir():
   if old.resolve()==folder.resolve() or old.is_symlink() or not old.is_dir():continue
   shutil.rmtree(old);removed+=1
 refs=referenced_hashes(root);removed_objects=0;objroot=root/'objects'
 if objroot.exists():
  for obj in objroot.glob('*/*'):
   if obj.is_file() and re.fullmatch('[0-9a-f]{64}',obj.name) and obj.name not in refs:
    obj.unlink();removed_objects+=1
  for d in objroot.iterdir():
   if d.is_dir() and not d.is_symlink():
    try:d.rmdir()
    except OSError:pass
 return {'acknowledged':True,'receiver':receipt.stem,'removed_snapshots':removed,'removed_objects':removed_objects,'kept_snapshot':folder.name}

def verify_command(a):
 root=Path(a.vault).expanduser().resolve();folder=resolve_snapshot(root,a.snapshot,getattr(a,'host',None))
 try:folder.relative_to(root)
 except ValueError:raise ValueError('Snapshot must be inside the selected vault')
 report=verify_snapshot(root,folder)
 if a.ack:
  if not report['complete']:raise ValueError('Snapshot is incomplete; no acknowledgement was written: '+dump(report))
  manifest=json.loads((folder/'manifest.json').read_text());origin=safe_part(manifest.get('host','unknown'));receiver=a.receiver or __import__('socket').gethostname()
  receipt=dict(version=1,origin_host=manifest.get('host'),snapshot_id=folder.name,manifest_sha256=report['manifest_sha256'],receiver_host=receiver,verified=time.time(),verification=dict(session_count=report['session_count'],native_database_count=report['native_database_count'],profile_file_count=report['profile_file_count'],object_count=report['object_count']))
  dest=root/'acks'/origin/folder.name/(safe_part(receiver)+'.json');atomic_write(dest,dump(receipt).encode());report['ack_written']=str(dest)
 print(dump(report))

def resolve_snapshot(root,value,host=None):
 root=Path(root).expanduser().resolve()
 if value!='latest':return Path(value).expanduser().resolve()
 base=root/'snapshots'/(str(host) if host else '')
 manifests=list(base.glob('*/manifest.json')) if host else list((root/'snapshots').glob('*/*/manifest.json'))
 candidates=[]
 for manifest_path in manifests:
  if manifest_path.is_symlink():continue
  folder=manifest_path.parent.resolve()
  try:
   folder.relative_to(root);manifest=json.loads(manifest_path.read_text());created=float(manifest.get('created',manifest_path.stat().st_mtime))
   candidates.append((created,folder))
  except Exception:continue
 for created,folder in sorted(candidates,key=lambda x:(x[0],x[1].name),reverse=True):
  report=verify_snapshot(root,folder)
  if report['complete']:return folder
 raise ValueError('No complete, integrity-verified snapshot is available in this vault')

def latest_command(a):
 root=Path(a.vault).expanduser().resolve();folder=resolve_snapshot(root,'latest',a.host);report=verify_snapshot(root,folder)
 print(dump({'snapshot':str(folder),'host':json.loads((folder/'manifest.json').read_text()).get('host'),'verification':report}))

@contextlib.contextmanager
def vault_lock(root):
 root=Path(root);root.mkdir(parents=True,exist_ok=True);lock_path=root/'.backup.lock';f=open(lock_path,'a+b')
 if os.name!='nt':os.chmod(root,0o700)
 try:
  if os.name=='nt':
   import msvcrt
   if lock_path.stat().st_size==0:f.write(b'\0');f.flush()
   f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
  else:
   import fcntl
   fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
 except (OSError,BlockingIOError):
  f.close();raise RuntimeError('Another session-vault backup is already running; this run was skipped')
 try:yield
 finally:
  try:
   if os.name=='nt':
    import msvcrt
    f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
   else:
    import fcntl
    fcntl.flock(f.fileno(),fcntl.LOCK_UN)
  finally:f.close()

def backup(a):
 root=Path(a.vault).expanduser().resolve()
 with vault_lock(root):return backup_locked(a)

def backup_locked(a):
 root=Path(a.vault).expanduser().resolve();root.mkdir(parents=True,exist_ok=True)
 if os.name!='nt':os.chmod(root,0o700)
 items=[];warnings=[];native_databases=[];profile_files=[];profile_exclusions=[];sources=[]
 prior=previous_manifest(root,a.host);lost=[]
 if prior:
  for src in prior.get('sources',[]):
   if src.get('present') and src.get('home') and not Path(src['home']).expanduser().exists():lost.append(src)
 for src in lost:warnings.append('previously backed-up source is missing; old head retained: '+str(src.get('provider'))+' '+str(src.get('home')))
 retention={'acknowledged':False,'removed_snapshots':0,'removed_objects':0,'reason':'source disappeared; preserving previous versions'} if lost else prune_acknowledged(root,a.host)
 def add(provider,sid,title,cwd,files,record=None,group='',parent=None,title_source='title'):
  items.append(dict(provider=provider,id=sid,title=title or sid,title_source=title_source,cwd=cwd or '',group=group,parent=parent,files=files,record=record))
 def file_data(p,home,data):return dict(path=p.resolve().relative_to(home).as_posix(),hash=put(root,data))
 def file(p,home):return file_data(p,home,stable(p))
 for provider,home in [('codex',a.codex_home),('claude',a.claude_home),('hermes',a.hermes_home),('pi',a.pi_home),('codebuddy',a.codebuddy_home),('zcode',a.zcode_home)]:
  home=Path(home).expanduser().resolve()
  if not home.exists():sources.append(dict(provider=provider,home=str(home),present=False));continue
  source=dict(provider=provider,home=str(home),present=True)
  if provider=='codex':
   seen=set(); dbs=sorted(home.glob('state_*.sqlite'),key=lambda p:int(re.search(r'state_(\d+)',p.name)[1]))
   if dbs:
    c=snapshot(dbs[-1]);blob=sqlite_bytes(c);dbhash=put(root,blob);names=tables(c)
    native_databases.append(dict(provider='codex',root_key='codex',path=dbs[-1].relative_to(home).as_posix(),hash=dbhash,required_tables=['threads']))
    source['state_database']=dbs[-1].name
    groups={t:rows(c,t) for t in ['projects','thread_sections'] if t in names}
    for r in rows(c,'threads'):
     p=Path(r['rollout_path'])
     if not p.is_file():warnings.append('codex missing rollout: '+r['id']);continue
     try:f=file(p,home)
     except ValueError: warnings.append('codex rollout outside home: '+r['id']);continue
     rec=dict(db=dbs[-1].name,tables={'threads':[r],**groups})
     title,title_source=title_for(r,r['id'])
     add(provider,r['id'],title,r.get('cwd'),[f],rec,group=r.get('thread_section_id') or r.get('project_id') or '',parent=r.get('attached_thread_parent_id'),title_source=title_source)
     seen.add(p.resolve())
    c.close()
   source['session_count_before_profile']=len(items)
   for sub in ['sessions','archived_sessions']:
    for p in (home/sub).rglob('*.jsonl'):
     if p.resolve() in seen:continue
     b=stable(p); lines=b.splitlines()
     if not lines:continue
     r=json.loads(lines[0]);r=r.get('payload',r)
     if not r.get('id'):continue
     title,title_source=title_for(r,r['id'])
     add(provider,r['id'],title,r.get('cwd'),[file(p,home)],group='unindexed',title_source=title_source)
  elif provider=='claude':
   for p in (home/'projects').glob('*/*.jsonl'):
    rr=[json.loads(x) for x in stable(p).splitlines() if x.strip()];sid=next((r.get('sessionId') for r in rr if r.get('sessionId')),p.stem)
    cwd=next((r.get('cwd') for r in rr if r.get('cwd')),'')
    title_record=next((r for r in reversed(rr) if r.get('summary') or r.get('customTitle')),{})
    title=title_record.get('summary') or title_record.get('customTitle') or sid
    title_source='summary' if title_record.get('summary') else 'customTitle' if title_record.get('customTitle') else 'id'
    fs=[file(p,home)]
    # Subagent transcripts are conversation history, not disposable artifacts.
    fs += [file(q,home) for q in (p.parent/p.stem/'subagents').glob('*.jsonl') if not q.is_symlink()]
    add(provider,sid,title,cwd,fs,group=p.parent.name,title_source=title_source)
  elif provider=='pi':
   session_root=home/'sessions'
   custom_session_root=os.environ.get('PI_CODING_AGENT_SESSION_DIR')
   if custom_session_root and Path(custom_session_root).expanduser().resolve()!=session_root.resolve():
    warnings.append('custom PI_CODING_AGENT_SESSION_DIR is outside the supported agent directory; Pi sessions were not captured: '+custom_session_root)
   if session_root.is_dir():
    for p in sorted(session_root.rglob('*.jsonl')):
     if p.is_symlink():continue
     b,records=parse_jsonl(p)
     if not records or records[0].get('type')!='session' or not isinstance(records[0].get('id'),str) or not records[0]['id']:
      raise ValueError('Unsupported Pi session header: '+str(p))
     header=records[0];sid=header['id'];title,title_source=session_file_label(provider,records,sid)
     add(provider,sid,title,header.get('cwd'),[file_data(p,home,b)],group=p.parent.name,title_source=title_source)
  elif provider=='codebuddy':
   for p in sorted((home/'projects').glob('*/*.jsonl')):
    if p.is_symlink():continue
    b,records=parse_jsonl(p)
    if not records:continue
    sid=next((r.get('sessionId') or r.get('session_id') for r in records if isinstance(r.get('sessionId') or r.get('session_id'),str) and (r.get('sessionId') or r.get('session_id'))),p.stem)
    cwd=next((r.get('cwd') or r.get('working_directory') for r in records if isinstance(r.get('cwd') or r.get('working_directory'),str) and (r.get('cwd') or r.get('working_directory'))),'')
    title,title_source=session_file_label(provider,records,sid)
    add(provider,sid,title,cwd,[file_data(p,home,b)],group=p.parent.name,title_source=title_source)
  elif provider=='zcode':
   pass
  else:
   dbs=[db for db in [home/'state.db',*sorted((home/'profiles').glob('*/state.db'))] if db.exists()]
   if not dbs:warnings.append('hermes state.db not found under '+str(home))
   for db in dbs:
    if not db.exists():continue
    c=snapshot(db);blob=sqlite_bytes(c);dbhash=put(root,blob);names=tables(c)
    if not {'sessions','messages'}<=set(names):raise ValueError('Unsupported Hermes schema')
    native_databases.append(dict(provider='hermes',root_key='hermes',path=db.relative_to(home).as_posix(),hash=dbhash,required_tables=['sessions','messages']))
    source.setdefault('state_databases',[]).append(db.relative_to(home).as_posix())
    for r in rows(c,'sessions'):
     sid=r['id'];ts={'sessions':[r]}
     for t in names:
      if t!='sessions' and 'session_id' in cols(c,t) and not any(t.startswith(x) for x in ['messages_fts','session_fts']):ts[t]=rows(c,t,'WHERE session_id=?',(sid,))
     title,title_source=title_for(r,sid,('title',))
     add(provider,sid,title,r.get('cwd') or r.get('working_directory'),[],dict(db=db.relative_to(home).as_posix(),tables=ts),group=str(db.parent.relative_to(home)),parent=r.get('parent_session_id'),title_source=title_source)
    c.close()
  source['session_count']=sum(1 for s in items if s['provider']==provider)
  sources.append(source)
  for p in collect_profile_files(provider,home):
   rel=p.relative_to(home).as_posix()
   try:
    if rel in PROFILE_EXCLUDE_PATHS.get(provider,set()):profile_exclusions.append(dict(root_key=provider,path=rel,reason='device identity; vendor says not to migrate'));continue
    if SENSITIVE_FILENAME.match(p.name):profile_exclusions.append(dict(root_key=provider,path=rel,reason='credential filename'));continue
    b=stable(p)
    if sensitive_content(b):profile_exclusions.append(dict(root_key=provider,path=rel,reason='credential-like value'));continue
    profile_files.append(dict(provider=provider,root_key=provider,path=rel,hash=put(root,b)))
   except Exception as e:profile_exclusions.append(dict(root_key=provider,path=rel,reason='unreadable: '+str(e)));warnings.append('profile file unreadable: '+provider+'/'+rel)
 export_value=getattr(a,'codebuddy_cn_exports',None)
 if export_value:
  export_root=Path(export_value).expanduser().resolve()
  if not export_root.is_dir():
   sources.append(dict(provider='codebuddy-cn',home=str(export_root),present=False));warnings.append('CodeBuddy CN export directory is missing: '+str(export_root))
  else:
   source=dict(provider='codebuddy-cn',home=str(export_root),present=True,session_count=0,archives=0)
   seen={}
   for archive_path in sorted(export_root.rglob('*')):
    if archive_path.is_symlink() or not archive_path.is_file():continue
    suffix=archive_path.suffix.lower()
    if suffix not in {'.json','.zip'}:continue
    raw=stable(archive_path);entries=[]
    if suffix=='.json':entries=[(archive_path.name,raw)]
    else:
     if len(raw)>CODEBUDDY_CN_MAX_ZIP_BYTES:raise ValueError('CodeBuddy CN ZIP exceeds the 1 GiB archive limit: '+archive_path.name)
     try:
      with zipfile.ZipFile(io.BytesIO(raw)) as zf:
       infos=[info for info in zf.infolist() if not info.is_dir()]
       if len(infos)>CODEBUDDY_CN_MAX_ZIP_ENTRIES or sum(info.file_size for info in infos)>CODEBUDDY_CN_MAX_ZIP_BYTES:raise ValueError('CodeBuddy CN ZIP expands beyond supported limits: '+archive_path.name)
       entries=[(info.filename,zf.read(info)) for info in infos if info.filename.lower().endswith('.json')]
     except (OSError,zipfile.BadZipFile,RuntimeError) as e:raise ValueError('Invalid CodeBuddy CN ZIP '+archive_path.name+': '+str(e)) from e
     if not entries:raise ValueError('CodeBuddy CN ZIP has no JSON conversation entries: '+archive_path.name)
    source['archives']+=1
    for entry_name,entry_bytes in entries:
     archive,conv=validate_codebuddy_cn_archive(entry_bytes,archive_path.name+'/'+Path(entry_name).name)
     sid=conv['id'];entry_hash=sha(entry_bytes)
     if sid in seen:
      if seen[sid]!=entry_hash:raise ValueError('Conflicting CodeBuddy CN exports have the same conversation ID: '+sid)
      continue
     seen[sid]=entry_hash;title,title_source=codebuddy_cn_label(conv)
     rel=Path('exports')/(sid+'.json')
     items.append(dict(provider='codebuddy-cn',id=sid,title=title,title_source=title_source,cwd=codebuddy_cn_workspace(conv),group='CodeBuddy CN history',parent=None,files=[dict(path=rel.as_posix(),hash=put(root,entry_bytes))],record=None))
   source['session_count']=len(seen);sources.append(source)
 # Shared Agent Skills are used by Codex and other Agent Skills-compatible tools.
 agents_home_value=getattr(a,'agents_home',None)
 agents_home=Path(agents_home_value).expanduser().resolve() if agents_home_value else None
 if agents_home and agents_home.exists():
  sources.append(dict(provider='agents',home=str(agents_home),present=True))
  for p in collect_profile_files('agents',agents_home):
   rel=p.relative_to(agents_home).as_posix()
   try:
    if SENSITIVE_FILENAME.match(p.name):profile_exclusions.append(dict(root_key='agents',path=rel,reason='credential filename'));continue
    b=stable(p)
    if sensitive_content(b):profile_exclusions.append(dict(root_key='agents',path=rel,reason='credential-like value'));continue
    profile_files.append(dict(provider='agents',root_key='agents',path=rel,hash=put(root,b)))
   except Exception as e:profile_exclusions.append(dict(root_key='agents',path=rel,reason='unreadable: '+str(e)));warnings.append('profile file unreadable: agents/'+rel)
 # Explicit auxiliary files only; never crawl the project or entire agent home.
 extras=[]
 for path in a.include:
  p=Path(path).expanduser()
  if p.is_symlink():raise ValueError('--include does not follow symbolic links')
  p=p.resolve()
  if not p.is_file():raise ValueError('--include requires an explicit regular file')
  b=stable(p)
  if SENSITIVE_FILENAME.match(p.name) or sensitive_content(b):raise ValueError('--include cannot contain credential files or credential-like values: '+str(p))
  extras.append(dict(source=str(p),hash=put(root,b)))
 if not any(s.get('present') for s in sources) and not extras:warnings.append('no agent home or shared skill directory was found')
 manifest=dict(version=1,created=time.time(),host=a.host,sources=sources,sessions=items,native_databases=native_databases,profile_files=profile_files,profile_exclusions=profile_exclusions,extras=extras,warnings=warnings)
 sid=time.strftime('%Y%m%d-%H%M%S')+'-'+sha(dump(manifest).encode())[:10]
 folder=root/'snapshots'/a.host/sid;folder.mkdir(parents=True)
 render(folder,manifest);atomic_write(folder/'manifest.json',dump(manifest).encode())
 report=verify_snapshot(root,folder);report['snapshot_id']=sid;report['retention']=retention;report['sources']=[dict(provider=s.get('provider'),present=s.get('present'),home=s.get('home'),session_count=s.get('session_count',0)) for s in sources];report['credential_files_excluded']=sum(1 for f in profile_exclusions if str(f.get('reason','')).startswith('credential'));report['profile_exclusions']=profile_exclusions
 print(dump(report))
 if not report['complete']:raise ValueError('Backup snapshot was not promoted because verification found incomplete data; the previous verified snapshot is unchanged')
 pointer=dict(snapshot_rel=folder.relative_to(root).as_posix(),manifest_sha256=report['manifest_sha256'],verified=time.time())
 atomic_write(root/'heads'/(re.sub(r'[^A-Za-z0-9_.-]','_',a.host)+'.json'),dump(pointer).encode())

def render(folder,m):
 tree={}
 for s in m['sessions']:
  p=tree.setdefault(s['provider'],{})
  p=p.setdefault(s['group'] or '(ungrouped)',{})
  p.setdefault(s['cwd'] or '(no workspace)',[]).append(s)
 lines=['# Session archive','', 'Sessions are shown by their stored display name. Internal IDs stay in the manifest and are not repeated in this tree.','']
 for provider,groups in sorted(tree.items()):
  lines.append('- '+provider)
  for group,workspaces in sorted(groups.items()):
   # Resolve native Codex section/project names, retain stable ID in manifest.
   label=group
   for s in m['sessions']:
    for t in ['projects','thread_sections']:
     for r in ((s.get('record') or {}).get('tables',{}).get(t,[])):
      if r.get('id')==group:label=r.get('name',group)
   lines.append('  - '+label)
   for cwd,ss in sorted(workspaces.items()):
    lines.append('    - '+cwd)
    for s in ss:
     label=str(s.get('title') or s['id']).replace('\n',' ')
     source=session_title_source(s)
     lines.append('      - '+label+'  ('+source+')')
 text='\n'.join(lines)+'\n';atomic_write(folder/'TREE.md',text.encode())
 cards=[]
 for s in m['sessions']:
  title=html.escape(str(s.get('title') or s['id']))
  provider=html.escape(str(s.get('provider') or ''))
  cwd=html.escape(str(s.get('cwd') or '(no workspace)'))
  source=html.escape(str(session_title_source(s)))
  sid=html.escape(str(s['id']))
  cards.append('<article><h2>'+title+'</h2><p>'+provider+' · '+source+'</p><p>'+cwd+'</p><details><summary>Internal session ID</summary><code>'+sid+'</code></details></article>')
 page='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Session archive</title><style>body{font:15px system-ui;max-width:1120px;margin:32px auto;padding:0 20px;background:#f5f7fb;color:#20283a}h1{margin-bottom:8px}#search{width:100%;box-sizing:border-box;padding:11px;border:1px solid #ccd3df;border-radius:8px;margin:12px 0 18px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}article{background:white;border:1px solid #dce1e9;border-radius:10px;padding:14px}h2{font-size:16px;margin:0 0 7px;overflow-wrap:anywhere}p{color:#5a6578;margin:5px 0;overflow-wrap:anywhere}details{font-size:12px;color:#667085;margin-top:10px}code{overflow-wrap:anywhere}</style><h1>Session archive</h1><p>Search by display name, provider or original workspace. Session IDs are kept inside each card\'s details.</p><input id="search" placeholder="Search session name or workspace"><main>'+''.join(cards)+'</main><script>document.getElementById("search").addEventListener("input",e=>{const q=e.target.value.toLowerCase();for(const card of document.querySelectorAll("article"))card.hidden=!card.textContent.toLowerCase().includes(q)})</script></html>'
 atomic_write(folder/'index.html',page.encode())

def remap(v,maps):
 if ntpath.splitdrive(v)[0] or '\\' in v:
  normalized=ntpath.normpath(v);folded=ntpath.normcase(normalized)
  for old,new in sorted(maps,key=lambda x:-len(x[0])):
   if not (ntpath.splitdrive(old)[0] or '\\' in old):continue
   old_normalized=ntpath.normpath(old);old_folded=ntpath.normcase(old_normalized)
   if folded==old_folded or folded.startswith(old_folded.rstrip('\\')+'\\'):
    return ntpath.normpath(new.rstrip('\\/')+normalized[len(old_normalized):])
 for old,new in sorted(maps,key=lambda x:-len(x[0])):
  if ntpath.splitdrive(old)[0] or '\\' in old:continue
  if v==old or v.startswith(old.rstrip('/')+'/'):return new.rstrip('/')+v[len(old.rstrip('/')):]
 return v

def absolute_path(value):return Path(value).is_absolute() or ntpath.isabs(value)
PATH_KEYS={'cwd','working_directory','workdir','projectPath','project_path','workspace_path','path','rollout_path'}
def rewrite(obj,maps):
 if isinstance(obj,list):return [rewrite(x,maps) for x in obj]
 if isinstance(obj,dict):return {k:remap(v,maps) if k in PATH_KEYS and isinstance(v,str) else rewrite(v,maps) if k not in ['content','text','message','arguments','output'] else v for k,v in obj.items()}
 return obj

def parse_maps(values):
 maps=[x.split('=',1) for x in values]
 if any(len(x)!=2 or not x[0] or not x[1] for x in maps):raise ValueError('Use --map OLD=NEW')
 return maps

def restore_ui(a):
 root=Path(a.vault).expanduser().resolve();p=resolve_snapshot(root,a.snapshot,getattr(a,'host',None))
 m=json.loads((p/'manifest.json').read_text());maps=parse_maps(a.map)
 sessions=[]
 for s in m.get('sessions',[]):
  target=remap(s.get('cwd') or '',maps)
  if s['provider']=='codebuddy-cn' and not (s.get('cwd') or ''):target=str(Path(getattr(a,'codebuddy_cn_home',Path.home()/'Documents'/'CodeBuddy CN Imports')).expanduser().resolve())
  sessions.append(dict(id=s['id'],provider=s['provider'],title=s.get('title') or s['id'],title_source=session_title_source(s),source_cwd=s.get('cwd') or '',target_cwd=target,group=s.get('group') or ''))
 data=dict(vault=str(root),snapshot=str(p),snapshot_rel=p.relative_to(root).as_posix(),manifest_sha256=sha((p/'manifest.json').read_bytes()),name_prefix=a.name_prefix,sessions=sessions)
 encoded=json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
 template=Path(__file__).resolve().parent.parent/'assets'/'restore-ui.html'
 page=template.read_text().replace('__SESSION_DATA_URI__',quote(encoded,safe=''))
 output=Path(a.output).expanduser().resolve();output.parent.mkdir(parents=True,exist_ok=True);output.write_text(page.replace('__SESSION_VAULT_PICKER_TOKEN__',''))
 print(dump(dict(output=str(output),sessions=len(sessions),snapshot=str(p))))
 if not a.no_web:serve_restore_ui(page)

def serve_restore_ui(page):
 has_picker=sys.platform=='darwin' and bool(shutil.which('osascript'))
 marker='__SESSION_VAULT_PICKER_TOKEN__'
 if marker not in page:raise ValueError('Restore planner is missing the folder-picker token slot')
 token=secrets.token_urlsafe(24)
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def reply(self,code,payload,content_type='application/json; charset=utf-8'):
   body=payload.encode() if isinstance(payload,str) else json.dumps(payload,ensure_ascii=False).encode()
   self.send_response(code);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
  def authorized(self,parsed):
   origin='http://127.0.0.1:'+str(server.server_port)
   return (self.headers.get('Host')==origin.removeprefix('http://') and
           self.headers.get('Origin')==origin and
           parse_qs(parsed.query).get('token',[''])[0]==token and
           self.headers.get('X-Session-Vault-Token')==token)
  def do_GET(self):
   parsed=urlparse(self.path)
   origin='http://127.0.0.1:'+str(server.server_port)
   if parsed.path not in ('/','/index.html') or parse_qs(parsed.query).get('token',[''])[0]!=token or self.headers.get('Host')!=origin.removeprefix('http://'):
    self.reply(404,'Not found','text/plain; charset=utf-8');return
   self.reply(200,page.replace(marker,token if has_picker else ''),'text/html; charset=utf-8')
  def do_POST(self):
   parsed=urlparse(self.path)
   if not has_picker or parsed.path!='/choose-folder' or not self.authorized(parsed):
    self.reply(403,{'error':'目录选择请求未通过本机校验。'});return
   script='POSIX path of (choose folder with prompt "选择恢复后使用的工作目录")'
   try:
    result=subprocess.run(['osascript','-e',script],capture_output=True,text=True,timeout=300,check=True)
   except subprocess.TimeoutExpired:
    self.reply(408,{'error':'目录选择等待超时。'});return
   except subprocess.CalledProcessError:
    self.reply(400,{'error':'目录选择已取消或未能完成。'});return
   path=result.stdout.rstrip('\r\n').rstrip('/') or '/'
   if not path.startswith('/'):
    self.reply(500,{'error':'macOS 返回的目录路径无效。'});return
   self.reply(200,{'path':path})
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
 url='http://127.0.0.1:'+str(server.server_port)+'/?token='+token
 if has_picker:print('已启动仅监听本机的恢复规划服务；页面提供“选择目录”按钮。结束时回到终端按 Ctrl+C。',flush=True)
 else:print('已启动仅监听本机的恢复规划服务；当前系统无原生目录选择器，请直接编辑路径。结束时回到终端按 Ctrl+C。',flush=True)
 print('恢复规划页：'+url,flush=True)
 webbrowser.open(url)
 try:server.serve_forever(poll_interval=.5)
 except KeyboardInterrupt:print('\n目录选择服务已关闭。')
 finally:server.server_close()

def prefixed(value,prefix):
 if not isinstance(value,str) or not value:return value
 return value if not prefix or value.startswith(prefix) else prefix+value

def apply_codex_display_name(record,session,prefix):
 for row in (record or {}).get('tables',{}).get('threads',[]):
  if 'name' not in row:continue
  source_name=row.get('name')
  if not isinstance(source_name,str) or not source_name.strip():
   source_name=session.get('title') or row.get('title') or row.get('preview') or row.get('first_user_message') or row.get('id')
  if isinstance(source_name,str) and source_name.strip():row['name']=prefixed(source_name,prefix)

def read_restore_plan(plan_path,root_override,snapshot_override):
 plan=json.loads(Path(plan_path).expanduser().read_text())
 if plan.get('version')!=1:raise ValueError('Unsupported restore plan version')
 root_value=root_override or plan.get('vault')
 if not root_value:raise ValueError('Restore plan vault is missing; pass --vault')
 root=Path(root_value).expanduser().resolve()
 if not root.exists():raise ValueError('Restore plan vault does not exist; pass --vault')
 if snapshot_override:snapshot=Path(snapshot_override).expanduser().resolve()
 elif root_override and plan.get('snapshot_rel'):snapshot=(root/plan['snapshot_rel']).resolve()
 else:snapshot=Path(plan.get('snapshot') or '').expanduser().resolve()
 try:snapshot.relative_to(root)
 except ValueError:raise ValueError('Restore plan snapshot must be inside the selected vault')
 if not (snapshot/'manifest.json').is_file():raise ValueError('Restore plan snapshot is missing; pass --snapshot')
 manifest_bytes=(snapshot/'manifest.json').read_bytes()
 if plan.get('manifest_sha256') and sha(manifest_bytes)!=plan['manifest_sha256']:raise ValueError('Restore plan belongs to a different snapshot manifest')
 return plan,root,snapshot,json.loads(manifest_bytes)

def profile_restore_targets(manifest,homes):
 targets=[]
 for item in manifest.get('profile_files',[]):
  provider=item.get('root_key') or item.get('provider')
  if provider not in homes:raise ValueError('Unknown profile root: '+str(provider))
  rel=Path(item.get('path',''))
  if not item.get('path') or rel.is_absolute() or '..' in rel.parts:raise ValueError('Unsafe profile path')
  home=Path(homes[provider]).expanduser().resolve();dest=home/rel
  if dest.is_symlink() or not dest.resolve().is_relative_to(home):raise ValueError('Profile path escapes its target root or is a symbolic link: '+str(dest))
  targets.append((provider,rel,dest,item))
 return targets

def restore(a):
 plan_path=getattr(a,'plan',None)
 if plan_path:
  if getattr(a,'map',[]) or getattr(a,'session',[]) or getattr(a,'project',None) or getattr(a,'provider',None) or getattr(a,'restore_extras',False):raise ValueError('--plan cannot be combined with --map, --session, --project, --provider or --restore-extras')
  plan,root,p,m=read_restore_plan(plan_path,getattr(a,'vault',None),getattr(a,'snapshot',None))
  plan_rows=plan.get('sessions')
  if not isinstance(plan_rows,list) or not plan_rows:raise ValueError('Restore plan has no selected sessions')
  lookup={(s['provider'],s['id']):s for s in m.get('sessions',[])}
  selected=[];maps_by_session={};targets={};seen=set()
  for item in plan_rows:
   key=(item.get('provider'),item.get('id'))
   if key in seen:raise ValueError('Duplicate session in restore plan')
   seen.add(key)
   s=lookup.get(key)
   if not s:raise ValueError('Session in restore plan not found in snapshot')
   if item.get('source_cwd','')!=(s.get('cwd') or ''):raise ValueError('Source workspace changed for '+str(s.get('title') or s['id']))
   if item.get('title') and item['title']!=(s.get('title') or s['id']):raise ValueError('Source title changed for '+str(s.get('title') or s['id']))
   target=item.get('target_cwd','')
   if not isinstance(target,str) or (target and not absolute_path(target)):raise ValueError('Target workspace must be an absolute path')
   source=s.get('cwd') or ''
   if source and not target:raise ValueError('Target workspace is required for '+str(s.get('title') or s['id']))
   maps_by_session[key]=[[source,target]] if source and target and source!=target else []
   targets[key]=target
   selected.append(s)
  name_prefix=getattr(a,'name_prefix',None)
  if name_prefix is None:name_prefix=plan.get('name_prefix') or ''
  if name_prefix and any(s['provider']!='codex' for s in selected):raise ValueError('--name-prefix currently applies to Codex sessions only')
 else:
  if not getattr(a,'vault',None) or not getattr(a,'snapshot',None):raise ValueError('Use --vault and --snapshot, or provide --plan')
  root=Path(a.vault).expanduser().resolve();p=resolve_snapshot(root,a.snapshot,getattr(a,'host',None))
  try:p.relative_to(root)
  except ValueError:raise ValueError('Snapshot must be inside the selected vault')
  m=json.loads((p/'manifest.json').read_text());maps=parse_maps(a.map)
  selected=[s for s in m['sessions'] if (not a.provider or s['provider']==a.provider) and (not a.session or s['id'] in a.session) and (not a.project or s['cwd']==a.project)]
  if a.session and set(a.session)-{s['id'] for s in selected}:raise ValueError('Requested session not found')
  maps_by_session={(s['provider'],s['id']):maps for s in selected};targets={(s['provider'],s['id']):remap(s.get('cwd') or '',maps) for s in selected}
  name_prefix=getattr(a,'name_prefix',None) or ''
  if name_prefix and any(s['provider']!='codex' for s in selected):raise ValueError('--name-prefix currently applies to Codex sessions only')
 homes={name:getattr(a,name+'_home') for name in ('codex','claude','hermes','pi','codebuddy','zcode')};homes['codebuddy-cn']=getattr(a,'codebuddy_cn_home',str(Path.home()/'Documents'/'CodeBuddy CN Imports'));homes['agents']=getattr(a,'agents_home','') or str(Path.home()/'.agents')
 profile_targets=profile_restore_targets(m,homes) if getattr(a,'restore_profile',False) else []
 preview=[]
 for s in selected:
  key=(s['provider'],s['id']);source=s.get('cwd') or ''
  display_name=s.get('title') or s['id']
  if s['provider']=='codex' and name_prefix:display_name=prefixed(display_name,name_prefix)
  preview.append(dict(provider=s['provider'],title=display_name,title_source=session_title_source(s),source_cwd=source,target_cwd=targets.get(key,remap(source,maps_by_session.get(key,[])))))
 profile_preview=[dict(provider=provider,path=rel.as_posix(),destination=str(dest),exists=dest.exists()) for provider,rel,dest,item in profile_targets]
 print(dump({'apply':a.apply,'sessions':preview,'profile_files':profile_preview}))
 if not a.apply:return
 report=verify_snapshot(root,p)
 if not report['complete']:raise ValueError('Snapshot failed full integrity verification; restore was not started: '+dump(report))
 if not a.agents_stopped:raise ValueError('Close target agents, then pass --agents-stopped')
 prepared_profile=[]
 for provider,rel,dest,item in profile_targets:
  b=get(root,item.get('hash',''))
  if SENSITIVE_FILENAME.match(rel.name) or sensitive_content(b):raise ValueError('Refusing to restore a credential-like profile file: '+str(rel))
  if dest.exists() and dest.read_bytes()!=b:raise ValueError('Profile conflict, refusing overwrite: '+str(dest))
  prepared_profile.append((dest,b))
 # Validate every object before any target write.
 for s in selected:
  for f in s['files']:get(root,f['hash'])
 for s in selected:
  key=(s['provider'],s['id']);session_maps=maps_by_session.get(key,[])
  home_attr='codebuddy_cn_home' if s['provider']=='codebuddy-cn' else s['provider']+'_home'
  home_value=getattr(a,home_attr)
  if s['provider']=='codebuddy-cn' and plan_path and not (s.get('cwd') or '') and targets.get(key):home_value=targets[key]
  home=Path(home_value).expanduser().resolve();home.mkdir(parents=True,exist_ok=True)
  files=[]; rec=rewrite(s.get('record'),session_maps)
  if s['provider']=='codex' and rec:apply_codex_display_name(rec,s,name_prefix)
  if plan_path and rec and targets.get(key) and not (s.get('cwd') or ''):
   for table in ('threads','sessions'):
    for row in rec.get('tables',{}).get(table,[]):
     if not row.get('cwd'):row['cwd']=targets[key]
  for f in s['files']:
   rel=Path(f['path'])
   if rel.is_absolute() or '..' in rel.parts:raise ValueError('Unsafe archive path')
   if s['provider']=='claude' and session_maps and s['cwd']:
    newcwd=remap(s['cwd'],session_maps);parts=list(rel.parts);parts[1]=re.sub(r'[^a-zA-Z0-9]','-',newcwd);rel=Path(*parts)
   if s['provider']=='pi' and session_maps and s['cwd'] and len(rel.parts)>=3 and rel.parts[0]=='sessions':
    rel=Path('sessions')/pi_session_directory(remap(s['cwd'],session_maps))/rel.name
   dest=home/rel
   if not dest.resolve().is_relative_to(home):raise ValueError('Symlink escape')
   b=get(root,f['hash'])
   if session_maps and s['provider']=='codebuddy-cn':
    b=dump(rewrite(json.loads(b.decode('utf-8')),session_maps)).encode('utf-8')
   elif session_maps:
    b=('\n'.join(json.dumps(rewrite(json.loads(x),session_maps),ensure_ascii=False) for x in b.decode().splitlines() if x.strip())+'\n').encode()
   if dest.exists() and dest.read_bytes()!=b:raise ValueError('Conflict, refusing overwrite: '+str(dest))
   files.append((dest,b))
  db=None
  if rec:
   rel=Path(rec['db'])
   if rel.is_absolute() or '..' in rel.parts:raise ValueError('Unsafe DB path')
   dbpath=home/rel
   if not dbpath.resolve().is_relative_to(home):raise ValueError('DB symlink escape')
   if not dbpath.exists():raise ValueError('Initialize target agent first; missing DB '+str(dbpath))
   db=connect(dbpath); db.execute('PRAGMA foreign_keys=OFF')
   backup_path=root/'pre-restore'/s['provider']/(str(time.time_ns())+'-'+dbpath.name)
   atomic_write(backup_path,sqlite_bytes(db))
   try:
    db.execute('BEGIN IMMEDIATE')
    for t,rs in rec['tables'].items():
     if t not in tables(db):raise ValueError('Target schema missing table '+t)
     for row in rs:
      row={k:dec(v) for k,v in row.items()}
      if t=='threads':row['rollout_path']=str(files[0][0])
      targetcols=cols(db,t)
      if set(row)-set(targetcols):raise ValueError('Schema mismatch in '+t)
      if t in ['threads','sessions'] and db.execute('SELECT 1 FROM "'+t+'" WHERE id=?',(row['id'],)).fetchone():raise ValueError('Session ID already exists; refusing merge '+row['id'])
      keys=list(row);q='INSERT '+('OR IGNORE ' if t in ['projects','thread_sections'] else '')+'INTO "'+t+'" ('+','.join('"'+k+'"' for k in keys)+') VALUES ('+','.join('?' for _ in keys)+')'
      db.execute(q,[row[k] for k in keys])
    for dest,b in files:
     dest.parent.mkdir(parents=True,exist_ok=True)
     if not dest.exists():atomic_write(dest,b)
    db.commit()
   except Exception:db.rollback();raise
   finally:db.close()
  else:
   for dest,b in files:
    dest.parent.mkdir(parents=True,exist_ok=True)
    if not dest.exists():atomic_write(dest,b)
 for dest,b in prepared_profile:
  if not dest.exists():atomic_write(dest,b)
 if a.restore_extras:
  for f in m.get('extras',[]):
   dest=Path(remap(f['source'],maps)).expanduser().resolve()
   if str(dest)==f['source']:raise ValueError('Extra file requires an explicit different destination mapping')
   b=get(root,f['hash'])
   if dest.exists() and dest.read_bytes()!=b:raise ValueError('Extra file conflict: '+str(dest))
   dest.parent.mkdir(parents=True,exist_ok=True);atomic_write(dest,b)
 codebuddy_outputs={}
 for s in selected:
  if s['provider']!='codebuddy-cn':continue
  key=(s['provider'],s['id']);home_value=getattr(a,'codebuddy_cn_home')
  if plan_path and not (s.get('cwd') or '') and targets.get(key):home_value=targets[key]
  home=Path(home_value).expanduser().resolve()
  file_entry=s['files'][0];rel=Path(file_entry['path']);b=get(root,file_entry['hash'])
  session_maps=maps_by_session.get(key,[])
  if session_maps:b=dump(rewrite(json.loads(b.decode('utf-8')),session_maps)).encode('utf-8')
  codebuddy_outputs.setdefault(home,[]).append((rel.as_posix(),b))
 bundle_paths=[]
 for home,entries in codebuddy_outputs.items():
  buffer=io.BytesIO()
  with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as zf:
   for rel,b in entries:zf.writestr(rel,b)
  bundle=buffer.getvalue();name='CodeBuddy-CN-Import-'+sha(bundle)[:16]+'.zip';dest=home/name
  if dest.exists() and dest.read_bytes()!=bundle:raise ValueError('CodeBuddy CN import bundle conflict: '+str(dest))
  if not dest.exists():atomic_write(dest,bundle)
  bundle_paths.append(str(dest))
 if bundle_paths:print('CodeBuddy CN native import bundle(s): '+', '.join(bundle_paths)+' (in CodeBuddy CN, open History and import the ZIP).')
 print('Restore complete. Restart agent; verify native session list and resume before discarding archive.')

def schedule_command(a):
 operation=a.operation;host=a.host
 if operation=='status':
  if sys.platform=='darwin':
   label='local.session-vault.backup';path=Path.home()/'Library'/'LaunchAgents'/(label+'.plist');loaded=False
   if path.exists():loaded=subprocess.run(['launchctl','print','gui/'+str(os.getuid())+'/'+label],capture_output=True).returncode==0
   print(dump({'platform':'macOS','installed':path.exists(),'loaded':loaded,'definition':str(path)}));return
  if os.name=='nt':
   name='SessionVaultBackup-'+safe_part(host);r=subprocess.run(['schtasks','/Query','/TN',name],capture_output=True,text=True)
   print(dump({'platform':'Windows','installed':r.returncode==0,'task':name,'details':r.stdout.strip()}));return
  raise ValueError('Scheduled backups are supported on macOS and Windows')
 if operation=='remove':
  if sys.platform=='darwin':
   label='local.session-vault.backup';path=Path.home()/'Library'/'LaunchAgents'/(label+'.plist')
   subprocess.run(['launchctl','bootout','gui/'+str(os.getuid())+'/'+label],capture_output=True)
   if path.exists():path.unlink()
   print(dump({'removed':True,'definition':str(path)}));return
  if os.name=='nt':
   name='SessionVaultBackup-'+safe_part(host);r=subprocess.run(['schtasks','/Delete','/TN',name,'/F'],capture_output=True,text=True)
   if r.returncode:raise ValueError(r.stderr.strip() or r.stdout.strip() or 'Task Scheduler could not remove the task')
   print(dump({'removed':True,'task':name}));return
  raise ValueError('Scheduled backups are supported on macOS and Windows')
 if operation!='install':raise ValueError('Unknown schedule operation')
 if not a.vault:raise ValueError('schedule install requires --vault')
 if a.minutes<1 or a.minutes>1440:raise ValueError('--minutes must be between 1 and 1440')
 script=str(Path(__file__).resolve());root=Path(a.vault).expanduser().resolve();root.mkdir(parents=True,exist_ok=True)
 args=[sys.executable,script,'backup','--vault',str(root),'--host',host]
 for name in ('codex','claude','hermes','pi','codebuddy','zcode'):args += ['--'+name+'-home',str(Path(getattr(a,name+'_home')).expanduser().resolve())]
 if getattr(a,'codebuddy_cn_exports',None):args += ['--codebuddy-cn-exports',str(Path(a.codebuddy_cn_exports).expanduser().resolve())]
 log_dir=root/'logs';log_dir.mkdir(parents=True,exist_ok=True)
 args += ['--agents-home',str(Path(a.agents_home).expanduser().resolve()),'--log-file',str(log_dir/'scheduled.log')]
 if sys.platform=='darwin':
  label='local.session-vault.backup';launch_dir=Path.home()/'Library'/'LaunchAgents';launch_dir.mkdir(parents=True,exist_ok=True)
  path=launch_dir/(label+'.plist')
  payload={'Label':label,'ProgramArguments':args,'StartInterval':a.minutes*60,'RunAtLoad':True,'StandardOutPath':str(log_dir/'scheduled.log'),'StandardErrorPath':str(log_dir/'scheduled-error.log'),'ProcessType':'Background'}
  atomic_write(path,plistlib.dumps(payload));subprocess.run(['launchctl','bootout','gui/'+str(os.getuid())+'/'+label],capture_output=True)
  r=subprocess.run(['launchctl','bootstrap','gui/'+str(os.getuid()),str(path)],capture_output=True,text=True)
  if r.returncode:raise ValueError(r.stderr.strip() or 'launchd could not load the backup task')
  print(dump({'installed':True,'platform':'macOS','interval_minutes':a.minutes,'definition':str(path),'log':str(log_dir/'scheduled.log')}));return
 if os.name=='nt':
  name='SessionVaultBackup-'+safe_part(host);ns='http://schemas.microsoft.com/windows/2004/02/mit/task';ET.register_namespace('',ns)
  tag=lambda value:'{'+ns+'}'+value
  task=ET.Element(tag('Task'),{'version':'1.2'});ET.SubElement(task,tag('RegistrationInfo'));triggers=ET.SubElement(task,tag('Triggers'))
  trigger=ET.SubElement(triggers,tag('CalendarTrigger'));repetition=ET.SubElement(trigger,tag('Repetition'));ET.SubElement(repetition,tag('Interval')).text='PT'+str(a.minutes)+'M';ET.SubElement(repetition,tag('Duration')).text='P1D';ET.SubElement(repetition,tag('StopAtDurationEnd')).text='false'
  ET.SubElement(trigger,tag('StartBoundary')).text=datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S');ET.SubElement(trigger,tag('Enabled')).text='true'
  schedule=ET.SubElement(trigger,tag('ScheduleByDay'));ET.SubElement(schedule,tag('DaysInterval')).text='1'
  principals=ET.SubElement(task,tag('Principals'));principal=ET.SubElement(principals,tag('Principal'),{'id':'Author'});ET.SubElement(principal,tag('UserId')).text=subprocess.check_output(['whoami'],text=True).strip();ET.SubElement(principal,tag('LogonType')).text='InteractiveToken';ET.SubElement(principal,tag('RunLevel')).text='LeastPrivilege'
  settings=ET.SubElement(task,tag('Settings'));ET.SubElement(settings,tag('MultipleInstancesPolicy')).text='IgnoreNew';ET.SubElement(settings,tag('DisallowStartIfOnBatteries')).text='false';ET.SubElement(settings,tag('StopIfGoingOnBatteries')).text='false';ET.SubElement(settings,tag('StartWhenAvailable')).text='true';ET.SubElement(settings,tag('Enabled')).text='true';ET.SubElement(settings,tag('ExecutionTimeLimit')).text='PT0S'
  actions=ET.SubElement(task,tag('Actions'),{'Context':'Author'});action=ET.SubElement(actions,tag('Exec'));ET.SubElement(action,tag('Command')).text=sys.executable;ET.SubElement(action,tag('Arguments')).text=subprocess.list2cmdline(args[1:]);ET.SubElement(action,tag('WorkingDirectory')).text=str(Path(script).parent)
  fd,xml_path=tempfile.mkstemp(prefix='session-vault-task-',suffix='.xml');os.close(fd)
  try:
   atomic_write(xml_path,ET.tostring(task,encoding='utf-8',xml_declaration=True));r=subprocess.run(['schtasks','/Create','/TN',name,'/XML',xml_path,'/F'],capture_output=True,text=True)
  finally:
   try:os.unlink(xml_path)
   except OSError:pass
  if r.returncode:raise ValueError(r.stderr.strip() or r.stdout.strip() or 'Task Scheduler could not create the task')
  print(dump({'installed':True,'platform':'Windows','interval_minutes':a.minutes,'task':name,'command':[sys.executable,*args[1:]]}));return
 raise ValueError('Scheduled backups are supported on macOS and Windows')

def main():
 p=argparse.ArgumentParser();sub=p.add_subparsers(dest='cmd',required=True)
 for cmd in ['backup','restore']:
  q=sub.add_parser(cmd);q.add_argument('--vault',required=cmd=='backup')
  for n,env,default in [('codex','CODEX_HOME','~/.codex'),('claude','CLAUDE_CONFIG_DIR','~/.claude'),('hermes','HERMES_HOME','~/.hermes'),('pi','PI_CODING_AGENT_DIR','~/.pi/agent'),('codebuddy','CODEBUDDY_CONFIG_DIR','~/.codebuddy'),('zcode','ZCODE_HOME','~/.zcode')]:q.add_argument('--'+n+'-home',default=os.environ.get(env,default))
  q.add_argument('--agents-home',default=os.environ.get('AGENTS_HOME','~/.agents'))
  if cmd=='backup':
   q.add_argument('--codebuddy-cn-exports',default=os.environ.get('CODEBUDDY_CN_EXPORTS'),help='folder containing CodeBuddy CN JSON/ZIP conversation exports')
   q.add_argument('--host',default=__import__('socket').gethostname());q.add_argument('--include',action='append',default=[]);q.add_argument('--log-file')
  else:
   q.add_argument('--codebuddy-cn-home',default=os.environ.get('CODEBUDDY_CN_HOME',str(Path.home()/'Documents'/'CodeBuddy CN Imports')),help='destination folder for CodeBuddy CN import bundles')
   q.add_argument('--snapshot');q.add_argument('--host');q.add_argument('--plan');q.add_argument('--map',action='append',default=[]);q.add_argument('--session',action='append',default=[]);q.add_argument('--project');q.add_argument('--provider',choices=['codex','claude','hermes','pi','codebuddy','codebuddy-cn']);q.add_argument('--restore-extras',action='store_true');q.add_argument('--restore-profile',action='store_true',help='restore archived memories, rules, skills and non-sensitive settings');q.add_argument('--name-prefix');q.add_argument('--apply',action='store_true');q.add_argument('--agents-stopped',action='store_true')
 q=sub.add_parser('verify');q.add_argument('--vault',required=True);q.add_argument('--snapshot',required=True);q.add_argument('--host');q.add_argument('--ack',action='store_true',help='write a peer-verification receipt for cloud sync');q.add_argument('--receiver')
 q=sub.add_parser('latest');q.add_argument('--vault',required=True);q.add_argument('--host')
 q=sub.add_parser('schedule');q.add_argument('operation',choices=['install','status','remove']);q.add_argument('--vault');q.add_argument('--host',default=__import__('socket').gethostname());q.add_argument('--minutes',type=int,default=15);q.add_argument('--codebuddy-cn-exports',default=os.environ.get('CODEBUDDY_CN_EXPORTS'),help='folder containing CodeBuddy CN JSON/ZIP conversation exports')
 for n,env,default in [('codex','CODEX_HOME','~/.codex'),('claude','CLAUDE_CONFIG_DIR','~/.claude'),('hermes','HERMES_HOME','~/.hermes'),('pi','PI_CODING_AGENT_DIR','~/.pi/agent'),('codebuddy','CODEBUDDY_CONFIG_DIR','~/.codebuddy'),('zcode','ZCODE_HOME','~/.zcode')]:q.add_argument('--'+n+'-home',default=os.environ.get(env,default))
 q.add_argument('--agents-home',default=os.environ.get('AGENTS_HOME','~/.agents'))
 q=sub.add_parser('restore-ui');q.add_argument('--vault',required=True);q.add_argument('--snapshot',required=True,help='snapshot path or latest');q.add_argument('--host');q.add_argument('--output',required=True);q.add_argument('--map',action='append',default=[]);q.add_argument('--name-prefix',default='');q.add_argument('--codebuddy-cn-home',default=os.environ.get('CODEBUDDY_CN_HOME',str(Path.home()/'Documents'/'CodeBuddy CN Imports')),help='default destination folder for CodeBuddy CN import bundles');q.add_argument('--serve',action='store_true',help='(legacy) open the browser planner; now the default');q.add_argument('--no-web',action='store_true',help='write the planner without starting a browser or local server')
 a=p.parse_args()
 if getattr(a,'serve',False) and getattr(a,'no_web',False):p.error('--serve and --no-web cannot be used together')
 if getattr(a,'host',None) and (a.host in {'.','..'} or not re.fullmatch(r'[\w.-]+',a.host)):p.error('Unsafe host name')
 def invoke():
  try:
   if a.cmd=='restore-ui':restore_ui(a)
   elif a.cmd=='schedule':schedule_command(a)
   elif a.cmd=='verify':verify_command(a)
   elif a.cmd=='latest':latest_command(a)
   else:globals()[a.cmd](a)
  except Exception as e:p.exit(1,'ERROR: '+str(e)+'\n')
 log_file=getattr(a,'log_file',None)
 if log_file:
  log_path=Path(log_file).expanduser();log_path.parent.mkdir(parents=True,exist_ok=True)
  if log_path.exists() and log_path.stat().st_size>2*1024*1024:
   previous=log_path.with_suffix(log_path.suffix+'.1')
   if previous.exists():previous.unlink()
   os.replace(log_path,previous)
  with open(log_path,'a',encoding='utf-8',buffering=1) as log:
   with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):invoke()
 else:invoke()
if __name__=='__main__':main()
