from datetime import datetime
import ast
import hashlib
import json
from pathlib import Path
import shutil

root = Path(r'D:\2026\FilpRing Project')
out = root/'work/d-migration/package-preparation'
out.mkdir(parents=True,exist_ok=True)
path = root/'소스/package.py'
old = path.read_bytes()
backup = out/'package-before.py'
assert not backup.exists()
backup.write_bytes(old)
text = old.decode('utf-8')
before = ast.parse(text)
needle = '"app.py", "i18n.py", "studio_ui.py", "engine.py",'
assert text.count(needle)==1
updated = text.replace(needle,'"app.py", "i18n.py", "studio_ui.py", "ui_motion.py", "engine.py",',1)
after = ast.parse(updated)
# 단일 필수 모듈 삽입 외에는 원본 문자와 모든 필수 요건을 유지한다.
assert updated.replace('"ui_motion.py", ', '', 1)==text
assert (root/'소스/ui_motion.py').is_file()
path.write_text(updated,encoding='utf-8')
assert path.read_text(encoding='utf-8')==updated
assert '\ufffd' not in updated
planned = {'schema_version':1,'time_kst':datetime.now().astimezone().isoformat(),'session':'01a15519-c86d-7880-a2e6-c9070f59067d','task':'studio-redesign-20261021','role':'build','requested_model':'gpt-6.1-sol','requested_effort':'medium','repair_used':9,'input_fix_used':7,'grant_scope':'이번 child turn의 Droot file_system.write 승인','package_before_sha256':hashlib.sha256(old).hexdigest(),'package_after_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'checks':{'syntax_passed':True,'strict_utf8_passed':True,'single_required_module_insertion_only':True,'module_exists':True,'package_executed':False,'build_executed':False,'shipping_replaced':False},'source_freeze':'부모 후속 배정 대기','build_plan':{'cwd':str(root/'소스'),'pyinstaller_argv':[str(root/'work/venv/Scripts/python.exe'),'-B','-X','utf8','-m','PyInstaller','--noconfirm','--clean','--distpath',str(out/'dist'),'--workpath',str(root/'소스/build-cache'),str(out/'FlipRing.spec')],'inno_argv':[r'C:\Users\PUVKID\AppData\Local\Programs\Inno Setup 6\ISCC.exe','/O'+str(out/'installer'),str(root/'소스/installer.iss')],'package_argv':[str(root/'work/venv/Scripts/python.exe'),'-B','-X','utf8',str(root/'소스/package.py')],'package_phase':'새 생성물 검증·적용 이후에만 실행','pyinstaller_phase':'소스 동결 이후에만 실행','inno_phase':'새 EXE 및 모든 runtime 대조 통과 이후에만 실행'},'timing':{'prior_release_cached_pyinstaller_seconds':29.601812500011874,'prior_inno_seconds':77.61777059998713,'current_clean_analysis_seconds':'미실행·확인 불가','current_estimated_completion':'근거 없음'},'previous_shipping_preserved':True}
(out/'준비기록.json').write_text(json.dumps(planned,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
# 새 Analysis와 EXE만 만들 준비 명세다. COLLECT로 전체 런타임 중복을 생성하지 않는다.
spec=(root/'소스/FlipRing.spec').read_text(encoding='utf-8')
last="coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='FlipRing')"
assert spec.count(last)==1
spec=spec.replace(last,'# 런타임은 Analysis 결과·기존 출하 해시와 대조한 후에만 별도 적용한다.')
ast.parse(spec)
(out/'FlipRing.spec').write_text(spec,encoding='utf-8')
print(json.dumps({'package_after_sha256':planned['package_after_sha256'],'single_insertion_only':True,'syntax_files':2,'build_executed':False,'output':str(out)},ensure_ascii=False))
