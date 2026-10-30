"""변경하지 않은 기존 언어·대화상자 회귀의 구간별 실행 시간을 읽기 측정한다."""
from pathlib import Path
from datetime import datetime
import os,sys,json,time,unittest
os.environ['QT_QPA_PLATFORM']='offscreen';root=Path(__file__).resolve().parents[1]
mode=sys.argv[1];argv=list(sys.argv);out=root/'work'/('internal-motion-profile-'+mode);out.mkdir(exist_ok=True)
sys.argv=['소스/test_gui.py',str(out/'gui')];sys.path.insert(0,str(root/'소스'))
import test_gui as t
if mode=='without-global-filter':t.APPLICATION.removeEventFilter(t.APPLICATION._flipring_motion_system)
class Timed(unittest.TextTestResult):
    def startTest(self,test):
        self.start=time.monotonic();super().startTest(test)
    def stopTest(self,test):
        rows.append({'test':str(test),'seconds':time.monotonic()-self.start});super().stopTest(test)
rows=[];suite=unittest.TestSuite(t.GuiTests(name) for name in ('test_24_language_persists_when_window_recreated','test_29_dialog_labels_and_standard_buttons_follow_language','test_54_live_common_dialog_buttons_have_one_motion_and_keep_native_input','test_55_common_dialog_deferred_deletion_releases_button_owned_motions'))
if mode=='all-profile':suite=unittest.defaultTestLoader.loadTestsFromTestCase(t.GuiTests)
started=datetime.now().astimezone().isoformat();start=time.monotonic()
with (out/'검사출력.log').open('w',encoding='utf-8') as stream:r=unittest.TextTestRunner(verbosity=2,resultclass=Timed,stream=stream,failfast=True).run(suite)
report={'started_kst':started,'argv':[sys.executable,'-B','-X','utf8']+argv,'cwd':str(root),'mode':mode,'diagnostic_only':True,'source_change':False,'elapsed':time.monotonic()-start,'tests':r.testsRun,'success':r.wasSuccessful(),'rows':rows}
(out/'구간시간.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k!='rows'},ensure_ascii=False));print(json.dumps(sorted(rows,key=lambda x:x['seconds'],reverse=True)[:12],ensure_ascii=False));sys.exit(not r.wasSuccessful())

