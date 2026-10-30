from datetime import datetime
import ast
import hashlib
import json
from pathlib import Path

root = Path(r'D:\2026\FilpRing Project')
out = root/'work/d-migration/package-preparation'
source = root/'소스/package.py'
original = (out/'package-before.py').read_bytes()
needle = b'"app.py", "i18n.py", "studio_ui.py", "engine.py",'
replacement = b'"app.py", "i18n.py", "studio_ui.py", "ui_motion.py", "engine.py",'
assert original.count(needle)==1
updated=original.replace(needle,replacement,1)
assert updated.replace(replacement,needle,1)==original
assert original.count(b'\r\r\n')==0
assert updated.count(b'\r\n')==original.count(b'\r\n')==119
assert updated.count(b'\r\r\n')==0
source.write_bytes(updated)
assert source.read_bytes()==updated
ast.parse(updated.decode('utf-8'))
assert '\ufffd' not in updated.decode('utf-8')
# 실제 Analysis와 EXE만 새로 생성할 준비 명세이며 아직 실행하지 않는다.
spec=(root/'소스/FlipRing.spec').read_text(encoding='utf-8')
last="coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='FlipRing')"
assert spec.count(last)==1
spec=spec.replace(last,'# 런타임은 새 Analysis 결과와 기존 출하 해시 대조 후에만 별도 적용한다.')
ast.parse(spec)
(out/'FlipRing.spec').write_bytes(spec.encode('utf-8'))
temp=out/'temp'
base={'time_kst':datetime.now().astimezone().isoformat(),'session':'01a15519-c86d-7880-a2e6-c9070f59067d','task':'studio-redesign-20261021','role':'build','requested_model':'gpt-6.1-sol','requested_effort':'medium','server_runtime_identity':'확인 불가','assigned_repair':10,'current_repair_used':11,'input_fix_used':7,'global_sha256':hashlib.sha256(Path(r'C:\Users\PUVKID\.codex\AGENTS.md').read_bytes()).hexdigest(),'permission_grant':'본 child의 Droot write scope=session 승인','original_sha256':hashlib.sha256(original).hexdigest(),'after_sha256':hashlib.sha256(updated).hexdigest(),'checks':{'single_module_insertion_only':True,'crlf_preserved':119,'double_cr_absent':True,'strict_utf8':True,'ast_syntax':True,'required_module_exists':(root/'소스/ui_motion.py').is_file()},'executed':{'package':False,'pyinstaller':False,'iscc':False,'shipping_replacement':False},'build_plan':{'cwd':str(root/'소스'),'environment':{'TEMP':str(temp),'TMP':str(temp),'PATH_policy':'현재 venv Scripts, 실존 공용Python, Windows System32, Windows만 사용해 외부 개발DLL 혼입 방지'},'pyinstaller_argv':[str(root/'work/venv/Scripts/python.exe'),'-B','-X','utf8','-m','PyInstaller','--noconfirm','--clean','--distpath',str(out/'dist'),'--workpath',str(root/'소스/build-cache'),str(out/'FlipRing.spec')],'inno_argv':[r'C:\Users\PUVKID\AppData\Local\Programs\Inno Setup 6\ISCC.exe','/O'+str(out/'installer'),str(root/'소스/installer.iss')],'package_argv':[str(root/'work/venv/Scripts/python.exe'),'-B','-X','utf8',str(root/'소스/package.py')]},'time_evidence':{'previous_cached_pyinstaller_seconds':29.601812500011874,'previous_iscc_seconds':77.61777059998713,'current_clean_analysis_seconds':'미실행·확인 불가','cost':'확인 불가'},'conditions':['부모 UI 소스 동결 및 새 빌드 후속 배정 전 실행 금지','기존 정상 EXE/setup을 새 생성물 검증 전 보존','새 Analysis의 app/studio_ui/pdf_panel/i18n/ui_motion 모듈 경로와 PYZ 코드객체를 현재 소스 compile 결과와 대조','Analysis 바이너리·데이터 상대 경로 집합과 기존 런타임356개를 전수 크기·SHA 대조','base_library.zip 전체 SHA가 달라지면 내부 이름155개와 비압축SHA 동등성 별도 대조 후에만 기존 ZIP 보존 판단','새 DLL/누락/의도 밖 차이가 있으면 무조건 재사용하지 않고 부모 판정 반환','전체 런타임 COLLECT 중복 납품 없이 검증된 새 EXE와 변경 자료만 검토후 적용','검증된 임시 setup은 최종파일과 같은 D볼륨에서 원자 교체하며 임시중복1개만 허용','최종 source 변화 없는지 해시 재대조 후 package 및 새manifest; 실제 설치·실행은 부모가 별도 확인']}
(out/'수리10-준비결과.json').write_bytes((json.dumps(base,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
lessons=root/'ROUTING-LESSONS.md'
raw=lessons.read_bytes()
addition='\n## 포장 필수 목록의 개행 보존 (2026-10-24)\n- package.py의 필수 소스 목록에 ui_motion.py를 넣을 때 원본 bytes를 UTF-8로 해석한 CRLF 문자열을 Windows write_text 기본 개행 변환으로 기록해 CRCRLF 119개가 생겼다. 기록 직후 원문 대조가 실패하여 실제 포장과 빌드는 실행하지 않았다. 부모가 수리9→10을 누적한 뒤 보존 원본 bytes에서 해당 문자열 한 곳만 바꿔 write_bytes로 기록했다. 삽입을 되돌린 바이트가 원본과 완전히 같고 CRLF119개·중복CR0·엄격 UTF-8·AST를 확인했다. 이후 다른 UI 수리로 현재 누적은11/7이며 이 포장 수리의 배정 번호10과 구분한다. 출처: work/d-migration/package-preparation/필수목록수정-실패.json, package-before.py 및 수리10-준비결과.json. 이전 실패와 원본은 보존한다.\n'
assert '## 포장 필수 목록의 개행 보존 (2026-10-24)' not in raw.decode('utf-8')
lessons.write_bytes(raw+addition.encode('utf-8'))
print(json.dumps({'package_sha256':base['after_sha256'],'CRLF':119,'double_CR':0,'single_insertion_only':True,'syntax_files':2,'build_executed':False,'current_counters':[11,7],'plan':str(out/'수리10-준비결과.json')},ensure_ascii=False))
