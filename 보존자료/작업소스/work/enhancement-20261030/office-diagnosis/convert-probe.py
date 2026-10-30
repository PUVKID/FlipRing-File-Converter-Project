import sys,ctypes,json,hashlib,tempfile,datetime
from pathlib import Path
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root.parents[2]/'소스'))
import engine
source=root.parent/'matrix-test/run-cd6dd5dc-fc33-4d86-9c22-9cfb469e5f87/fixtures/한글 입력 공백.docx'
original=engine.run
records=[]
for fixed in (False,True):
    entry={'time_kst':datetime.datetime.now().astimezone().isoformat(),'fixed_profile_only':fixed,'repair_used':12,'input_fix_used':1,'product_changed':False,'source_hash':hashlib.sha256(source.read_bytes()).hexdigest()}
    with tempfile.TemporaryDirectory(prefix='fr-lo-diag-',dir=root.parents[2]/'work') as short:
        def observed(exe,args,cwd=None):
            args=list(args)
            entry['original_argv']=[str(exe),*map(str,args)]
            if fixed: args[0]='-env:UserInstallation='+Path(short).as_uri()
            entry['actual_argv']=[str(exe),*map(str,args)]
            entry['cwd']=str(Path.cwd()) if cwd is None else str(cwd)
            (root/'convert-active.json').write_text(json.dumps(entry,ensure_ascii=False,indent=2),encoding='utf-8')
            return original(exe,args,cwd)
        engine.run=observed
        try:
            result=Path(engine.convert(source,'pdf'))
            entry['output']=str(result); entry['bytes']=result.stat().st_size
            import pypdfium2 as pdfium
            doc=pdfium.PdfDocument(str(result))
            try:
                page=doc[0]; textpage=page.get_textpage()
                try: entry['text']=textpage.get_text_range()
                finally: textpage.close(); page.close()
                entry['pages']=len(doc)
            finally: doc.close()
        except Exception as exc: entry['error']=repr(exc)
        finally: engine.run=original
    entry['source_preserved']=hashlib.sha256(source.read_bytes()).hexdigest()==entry['source_hash']
    records.append(entry)
    (root/'convert-comparison.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(entry,ensure_ascii=False),flush=True)
