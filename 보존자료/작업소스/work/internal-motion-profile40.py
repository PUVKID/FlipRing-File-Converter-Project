"""기존 PDF 오류 양방향 회귀의 실제 함수별 비용을 측정한다."""
import sys,os,time,json,cProfile,pstats,io,unittest
from pathlib import Path
from datetime import datetime
root=Path(__file__).resolve().parents[1];out=root/'work/internal-motion-profile40';out.mkdir(exist_ok=True)
argv=[sys.executable,'-B','-X','utf8']+sys.argv;sys.argv=['소스/test_gui.py',str(out/'gui')];sys.path.insert(0,str(root/'소스'));os.environ['QT_QPA_PLATFORM']='offscreen'
import test_gui as t
p=cProfile.Profile();started=datetime.now().astimezone().isoformat();start=time.monotonic()
with (out/'출력.log').open('w',encoding='utf-8') as log:
    r=p.runcall(unittest.TextTestRunner(verbosity=2,stream=log).run,unittest.TestSuite([t.GuiTests('test_40_pdf_error_history_status_and_notifications_switch_both_ways')]))
p.dump_stats(str(out/'profile.pstats'));s=io.StringIO();pstats.Stats(p,stream=s).strip_dirs().sort_stats('cumtime').print_stats(25);(out/'함수비용.txt').write_text(s.getvalue(),encoding='utf-8')
report={'started_kst':started,'argv':argv,'cwd':str(root),'repair_used':14,'input_fix_used':9,'elapsed':time.monotonic()-start,'success':r.wasSuccessful(),'tests':r.testsRun,'diagnostic_only':True,'source_changed':False}
(out/'실행기록.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False));print(s.getvalue());sys.exit(not r.wasSuccessful())
