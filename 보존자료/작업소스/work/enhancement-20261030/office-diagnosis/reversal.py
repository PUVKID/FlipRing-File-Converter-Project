import json,subprocess,time,hashlib
from pathlib import Path
import pypdfium2 as pdfium
root=Path(__file__).resolve().parent
previous=json.loads((root/'comparison-profile.json').read_text(encoding='utf-8'))[-1]
args=previous['argv'].copy()
short=Path(previous['cwd'])/'p'/'profile'
args[1]='-env:UserInstallation='+short.as_uri()
process=subprocess.Popen(args,cwd=previous['cwd'],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
try: out,err=process.communicate(timeout=25)
except subprocess.TimeoutExpired:
    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=10)
    out,err=process.communicate(timeout=5)
report={'argv':args,'cwd':previous['cwd'],'only_changed_argument_index':1,'profile_chars':len(str(short)),'exit_code':process.returncode,'stdout':out.decode('utf-8','replace'),'stderr':err.decode('utf-8','replace'),'outputs':[]}
(root/'profile-reversal.stdout.bin').write_bytes(out); (root/'profile-reversal.stderr.bin').write_bytes(err)
for p in (Path(previous['cwd'])/'out').glob('*.pdf'):
    doc=pdfium.PdfDocument(str(p))
    try:
        page=doc[0]; textpage=page.get_textpage()
        try: content=textpage.get_text_range()
        finally: textpage.close(); page.close()
        report['outputs'].append({'name':p.name,'pages':len(doc),'text':content,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    finally: doc.close()
(root/'profile-reversal.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
