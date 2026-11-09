import importlib.util,tempfile,sqlite3,json,argparse
import io,zipfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('sv',str(Path(__file__).with_name('session_vault.py')));sv=importlib.util.module_from_spec(spec);spec.loader.exec_module(sv)

def codebuddy_cn_archive(sid,name,cwd=''):
 conv={'id':sid,'type':'chat','name':name,'createdAt':'2026-11-01T00:00:00Z','lastMessageAt':'2026-11-01T00:01:00Z','requests':[{'id':'req-'+sid,'type':'chat','state':'complete','messages':[{'id':'user-'+sid,'role':'user','message':'Synthetic first prompt'},{'id':'assistant-'+sid,'role':'assistant','message':'Synthetic response'}]}]}
 if cwd:conv['cwd']=cwd
 return json.dumps({'schema':'codebuddy.conversation','schemaVersion':1,'exportedAt':'2026-11-01T00:02:00Z','data':{'lastMessageAt':conv['lastMessageAt'],'conversations':[conv]}},ensure_ascii=False).encode()

with tempfile.TemporaryDirectory() as tmp:
 r=Path(tmp); homes={p:r/p for p in ['codex','claude','hermes','pi','codebuddy','zcode']}
 for h in homes.values():h.mkdir()
 c=sqlite3.connect(homes['codex']/'state_5.sqlite');c.execute('create table threads(id text primary key,rollout_path text,cwd text,title text,thread_section_id text)');c.execute('create table thread_sections(id text primary key,name text)');c.execute("insert into thread_sections values('group','Original folder')")
 f=homes['codex']/'sessions/2026/10/29/rollout-one.jsonl';f.parent.mkdir(parents=True);f.write_text(json.dumps({'type':'session_meta','payload':{'id':'one','cwd':'/old/project'}})+'\n'+json.dumps({'type':'message','content':'Do not rewrite /old/project in message text'})+'\n');c.execute('insert into threads values(?,?,?,?,?)',('one',str(f),'/old/project','Test title','group'));c.commit();c.close()
 f=homes['claude']/'projects/-old-project/two.jsonl';f.parent.mkdir(parents=True);f.write_text(json.dumps({'sessionId':'two','cwd':'/old/project','customTitle':'Claude title'})+'\n');sub=f.parent/'two/subagents/a.jsonl';sub.parent.mkdir(parents=True);sub.write_text('{"cwd":"/old/project"}\n')
 c=sqlite3.connect(homes['hermes']/'state.db');c.executescript('create table sessions(id text primary key,title text,cwd text,parent_session_id text);create table messages(id integer primary key,session_id text,role text,content text);');c.execute("insert into sessions values('three','Hermes title','/old/project',NULL)");c.execute("insert into messages values(1,'three','user','remember sentinel')");c.commit();c.close()
 f=homes['pi']/'sessions/--old-project--/pi-four.jsonl';f.parent.mkdir(parents=True);f.write_text('\n'.join([json.dumps({'type':'session','version':3,'id':'four','timestamp':'2026-11-06T00:00:00Z','cwd':'/old/project'}),json.dumps({'type':'session_info','name':'Pi named session'}),json.dumps({'type':'message','id':'m1','parentId':None,'timestamp':'2026-11-06T00:01:00Z','message':{'role':'user','content':[{'type':'text','text':'Pi first prompt'}]}})])+'\n')
 (homes['pi']/'skills/demo').mkdir(parents=True);(homes['pi']/'skills/demo/SKILL.md').write_text('Pi skill')
 (homes['pi']/'settings.json').write_text('{"apiKey":"secret-pi-key"}')
 f=homes['codebuddy']/'projects/opaque-project/cb-five.jsonl';f.parent.mkdir(parents=True);f.write_text('\n'.join([json.dumps({'type':'session','sessionId':'five','cwd':'/old/project'}),json.dumps({'type':'user','content':'CodeBuddy first prompt'})])+'\n')
 (homes['codebuddy']/'skills/demo').mkdir(parents=True);(homes['codebuddy']/'skills/demo/SKILL.md').write_text('CodeBuddy skill')
 (homes['codebuddy']/'CODEBUDDY.md').write_text('Remember my preferences')
 (homes['codebuddy']/'settings.local.json').write_text('{"apiKey":"secret-codebuddy-key"}')
 (homes['codebuddy']/'mcp.json').write_text('{"token":"must not copy"}')
 (homes['zcode']/'AGENTS.md').write_text('ZCode global rules')
 (homes['zcode']/'cli/config.json').parent.mkdir(parents=True);(homes['zcode']/'cli/config.json').write_text('{"hooks":[]}')
 (homes['zcode']/'v2').mkdir();(homes['zcode']/'v2/config.json').write_text('{"api_key":"sk-test-placeholder-not-a-real-key-0000000000000000"}')
 (homes['zcode']/'v2/credentials.json').write_text('{"credential":"device secret"}')
 (homes['zcode']/'v2/telemetry-state.json').write_text('{"deviceId":"do not migrate"}')
 (homes['zcode']/'agents/reviewer').mkdir(parents=True);(homes['zcode']/'agents/reviewer/AGENT.md').write_text('ZCode custom agent')
 (homes['zcode']/'skills/demo').mkdir(parents=True);(homes['zcode']/'skills/demo/SKILL.md').write_text('ZCode skill')
 (homes['zcode']/'commands').mkdir();(homes['zcode']/'commands/review.md').write_text('ZCode command')
 cb_exports=r/'codebuddy-cn-exports';cb_exports.mkdir()
 (cb_exports/'named-session.json').write_bytes(codebuddy_cn_archive('cn-one','CodeBuddy CN named session'))
 zbuffer=io.BytesIO()
 with zipfile.ZipFile(zbuffer,'w',compression=zipfile.ZIP_DEFLATED) as zf:zf.writestr('second-session.json',codebuddy_cn_archive('cn-two','', '/old/project'))
 (cb_exports/'batch-export.zip').write_bytes(zbuffer.getvalue())
 for h in homes.values():(h/'auth.json').write_text('NEVER BACK UP')
 extra=r/'artifact.txt';extra.write_text('explicit artifact')
 a=argparse.Namespace(vault=str(r/'vault'),host='fixture',include=[str(extra)],codebuddy_cn_exports=str(cb_exports),**{p+'_home':str(h) for p,h in homes.items()});sv.backup(a)
 snap=next((r/'vault/snapshots/fixture').iterdir());m=json.loads((snap/'manifest.json').read_text());assert len(m['sessions'])==7
 report=sv.verify_snapshot(r/'vault',snap);assert report['complete'] and report['session_count']==7
 head_path=sv.head_path(r/'vault','fixture');verified_head=head_path.read_bytes();(cb_exports/'corrupt.json').write_text('{"schema":"wrong"}',encoding='utf-8')
 try:sv.backup(a)
 except ValueError as e:assert 'unsupported archive schema' in str(e)
 else:raise AssertionError('invalid CodeBuddy CN export should fail backup')
 assert head_path.read_bytes()==verified_head;(cb_exports/'corrupt.json').unlink()
 labels={(s['provider'],s['id']):s['title'] for s in m['sessions']};assert labels[('pi','four')]=='Pi named session';assert labels[('codebuddy','five')]=='CodeBuddy first prompt'
 assert labels[('codebuddy-cn','cn-one')]=='CodeBuddy CN named session';assert labels[('codebuddy-cn','cn-two')]=='Synthetic first prompt'
 planner=r/'restore.html';sv.restore_ui(argparse.Namespace(vault=str(r/'vault'),snapshot=str(snap),host=None,map=[],name_prefix='',output=str(planner),no_web=True));page=planner.read_text();assert 'Pi%20named%20session' in page and 'CodeBuddy%20first%20prompt' in page
 assert 'Original folder' in (snap/'TREE.md').read_text()
 assert all('auth.json' not in f['path'] for s in m['sessions'] for f in s['files'])
 assert not any(f['provider']=='codebuddy' and f['path']=='mcp.json' for f in m['profile_files'])
 assert not any(f['provider']=='pi' and f['path']=='settings.json' for f in m['profile_files'])
 assert not any(f['provider']=='codebuddy' and f['path']=='settings.local.json' for f in m['profile_files'])
 assert {f['path'] for f in m['profile_files'] if f['provider']=='zcode'}=={'AGENTS.md','cli/config.json','agents/reviewer/AGENT.md','skills/demo/SKILL.md','commands/review.md'}
 zcode_exclusions={f['path']:f['reason'] for f in m['profile_exclusions'] if f['root_key']=='zcode'}
 assert zcode_exclusions['v2/config.json']=='credential-like value' and zcode_exclusions['v2/credentials.json']=='credential filename' and zcode_exclusions['v2/telemetry-state.json'].startswith('device identity')
 targets={p:r/('target-'+p) for p in homes};cb_target=r/'codebuddy-cn-import-target'
 for p,h in targets.items():
  h.mkdir()
  if p in ('codex','hermes'):
   source=sqlite3.connect(homes[p]/('state_5.sqlite' if p=='codex' else 'state.db')); dest=sqlite3.connect(h/('state_5.sqlite' if p=='codex' else 'state.db'))
   for (sql,) in source.execute("select sql from sqlite_master where type='table'"):dest.execute(sql)
   dest.commit();dest.close();source.close()
 b=argparse.Namespace(vault=a.vault,snapshot=str(snap),map=['/old=/new'],session=[],project='/old/project',provider=None,apply=False,agents_stopped=True,restore_extras=False,restore_profile=False,codebuddy_cn_home=str(cb_target),**{p+'_home':str(h) for p,h in targets.items()})
 sv.restore(b);assert not (targets['codex']/'sessions').exists()
 b.apply=True;sv.restore(b)
 c=sqlite3.connect(targets['codex']/'state_5.sqlite');row=c.execute('select cwd,rollout_path from threads').fetchone();assert row[0]=='/new/project';assert Path(row[1]).exists();assert '/old/project in message text' in Path(row[1]).read_text();c.close()
 assert (targets['claude']/'projects/-new-project/two.jsonl').exists()
 pi_file=targets['pi']/'sessions/--new-project--/pi-four.jsonl';assert pi_file.exists();pi_rows=[json.loads(x) for x in pi_file.read_text().splitlines()];assert pi_rows[0]['cwd']=='/new/project';assert pi_rows[1]['name']=='Pi named session'
 cb_file=targets['codebuddy']/'projects/opaque-project/cb-five.jsonl';assert cb_file.exists();cb_rows=[json.loads(x) for x in cb_file.read_text().splitlines()];assert cb_rows[0]['cwd']=='/new/project';assert cb_rows[1]['content']=='CodeBuddy first prompt'
 cb_bundles=list(cb_target.glob('CodeBuddy-CN-Import-*.zip'));assert len(cb_bundles)==1
 with zipfile.ZipFile(cb_bundles[0]) as zf:
  cb_entries={Path(n).stem:sv.validate_codebuddy_cn_archive(zf.read(n))[1] for n in zf.namelist()}
 assert set(cb_entries)=={'cn-two'} and cb_entries['cn-two']['cwd']=='/new/project'
 plan_target=r/'selected-CodeBuddy-CN-imports';plan_path=r/'restore-plan.json'
 plan={'version':1,'vault':str(r/'vault'),'snapshot':str(snap),'snapshot_rel':snap.relative_to(r/'vault').as_posix(),'manifest_sha256':sv.sha((snap/'manifest.json').read_bytes()),'sessions':[{'id':'cn-one','provider':'codebuddy-cn','title':'CodeBuddy CN named session','source_cwd':'','target_cwd':str(plan_target)}]}
 plan_path.write_text(json.dumps(plan),encoding='utf-8');b.plan=str(plan_path);b.map=[];b.project=None;b.apply=True;sv.restore(b)
 assert len(list(plan_target.glob('CodeBuddy-CN-Import-*.zip')))==1 and (plan_target/'exports/cn-one.json').is_file();b.plan=None
 b.restore_profile=True;b.project='/no-session';sv.restore(b);assert (targets['pi']/'skills/demo/SKILL.md').read_text()=='Pi skill';assert (targets['codebuddy']/'CODEBUDDY.md').read_text()=='Remember my preferences';assert not (targets['codebuddy']/'mcp.json').exists();assert (targets['zcode']/'AGENTS.md').read_text()=='ZCode global rules';assert (targets['zcode']/'skills/demo/SKILL.md').read_text()=='ZCode skill';assert not (targets['zcode']/'v2/credentials.json').exists() and not (targets['zcode']/'v2/telemetry-state.json').exists();b.restore_profile=False;b.project='/old/project';b.map=['/old=/new']
 c=sqlite3.connect(targets['hermes']/'state.db');assert c.execute('select content from messages').fetchone()[0]=='remember sentinel';c.close()
 try:sv.restore(b)
 except ValueError as e:assert 'already exists' in str(e)
 else:raise AssertionError('duplicate not refused')
 print('PASS: six session providers, ZCode profile-only backup, CodeBuddy CN JSON/ZIP validation and import bundle, Pi and CodeBuddy JSONL, path remap, credential/device/MCP exclusions, directory mapping, subagents, dry-run, conflict refusal, DB merge, literal transcript preservation')
