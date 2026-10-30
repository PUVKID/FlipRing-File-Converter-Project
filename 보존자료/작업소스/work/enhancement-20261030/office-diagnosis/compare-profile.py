import datetime,hashlib,json,os,shutil,subprocess,time
from pathlib import Path
root=Path(__file__).resolve().parent
source=root.parent/'matrix-test/run-cd6dd5dc-fc33-4d86-9c22-9cfb469e5f87/fixtures/한글 입력 공백.docx'
expected='52772517f88f48d2c6bc41052d58b79e69bd48970fe9fd37deb5d0f08929fb5b'
assert hashlib.sha256(source.read_bytes()).hexdigest()==expected
results=[]
for extension,unicode_path in [('exe',False),('exe',True)]:
    name='profile-'+('long' if unicode_path else 'short')
    folder=root/name; folder.mkdir(exist_ok=False)
    work=folder/'work'; work.mkdir()
    input_path=work/'input.docx'
    shutil.copyfile(source,input_path)
    output=work/'out'; output.mkdir()
    profile_path=work/('p'*90 if unicode_path else 'p')/'profile'
    profile=profile_path.as_uri()
    argv=[f'C:/Program Files/LibreOffice/program/soffice.{extension}',f'-env:UserInstallation={profile}','--headless','--norestore','--convert-to','pdf','--outdir',str(output),str(input_path)]
    entry={'time_kst':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(),'condition':name,'argv':argv,'cwd':str(work),'timeout_seconds':25,'repair_used':12,'input_fix_used':1,'product_changed':False,'profile_chars':len(str(profile_path))}
    started=time.monotonic()
    process=subprocess.Popen(argv,cwd=work,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    entry['pid']=process.pid
    try:
        stdout,stderr=process.communicate(timeout=25)
        entry['timeout']=False
    except subprocess.TimeoutExpired:
        kill=subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=10)
        entry['timeout']=True; entry['termination_exit']=kill.returncode
        stdout,stderr=process.communicate(timeout=5)
    (folder/'stdout.bin').write_bytes(stdout); (folder/'stderr.bin').write_bytes(stderr)
    entry.update(exit_code=process.returncode,exit_hex=hex(process.returncode&0xffffffff),elapsed=time.monotonic()-started,stdout=stdout.decode('utf-8','replace')[:4000],stderr=stderr.decode('utf-8','replace')[:4000],outputs=[{'name':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in output.iterdir()],source_preserved=hashlib.sha256(source.read_bytes()).hexdigest()==expected,input_preserved=hashlib.sha256(input_path.read_bytes()).hexdigest()==expected)
    results.append(entry)
    (root/'comparison-profile.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(entry,ensure_ascii=False),flush=True)
