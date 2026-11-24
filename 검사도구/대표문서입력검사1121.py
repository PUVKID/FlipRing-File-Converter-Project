"""합성 템플릿과 HWP 출력을 실제 LibreOffice로 읽어 내용 보존을 확인합니다."""
from pathlib import Path
import hashlib
import json
import sys
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '소스'
sys.path.insert(0, str(SOURCE))
MARKER = 'FlipRing template 1121'

LEGACY = {'dot': ('문서', 'MS Word 97 Vorlage'),
          'pot': ('프레젠테이션', 'MS PowerPoint 97 Vorlage'),
          'pps': ('프레젠테이션', 'MS PowerPoint 97 AutoPlay'),
          'xlt': ('스프레드시트', 'MS Excel 97 Vorlage/Template')}
OPENXML = {'dotm': ('docx', 'application/vnd.ms-word.template.macroEnabledTemplate.main+xml'),
           'potx': ('pptx', 'application/vnd.openxmlformats-officedocument.presentationml.template.main+xml'),
           'potm': ('pptx', 'application/vnd.ms-powerpoint.template.macroEnabled.main+xml'),
           'ppsm': ('pptx', 'application/vnd.ms-powerpoint.slideshow.macroEnabled.main+xml'),
           'xltm': ('xlsx', 'application/vnd.ms-excel.template.macroEnabled.main+xml')}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def make_base(directory, extension):
    path = directory / ('입력.' + extension)
    if extension == 'docx':
        from docx import Document
        d = Document()
        d.add_paragraph(MARKER)
        d.save(path)
    elif extension == 'pptx':
        from pptx import Presentation
        d = Presentation()
        d.slides.add_slide(d.slide_layouts[1]).shapes.title.text = MARKER
        d.save(path)
    else:
        from openpyxl import Workbook
        d = Workbook()
        d.active.append([MARKER, 123])
        d.save(path)
    return path

def output_text(path):
    if path.suffix == '.docx':
        from docx import Document
        d = Document(path)
        return '\n'.join(p.text for p in d.paragraphs) + '\n'.join(c.text for t in d.tables for row in t.rows for c in row.cells)
    if path.suffix == '.pptx':
        from pptx import Presentation
        return '\n'.join(s.text for slide in Presentation(path).slides for s in slide.shapes if s.has_text_frame)
    from openpyxl import load_workbook
    d = load_workbook(path, read_only=True, data_only=False)
    try:
        return '\n'.join(str(v) for sheet in d for row in sheet.values for v in row if v is not None)
    finally:
        d.close()

def office_export(source, target, profile, family, filter_name):
    import engine
    import document_formats as formats
    import document_process
    profile.mkdir()
    formats.write_secure_profile(profile)
    # 이 추가 필터는 합성 시험 입력 생성에만 쓰며 제품 지원표는 변경하지 않습니다.
    helper = profile / 'create_fixture.py'
    helper.write_text('import sys\nfrom pathlib import Path\nsys.path.insert(0,' + repr(str(SOURCE)) + ')\nimport document_bridge as b\nb.EXPORT_FILTERS={k:dict(v) for k,v in b.EXPORT_FILTERS.items()}\nb.EXPORT_FILTERS[' + repr(family) + '][' + repr(target.suffix[1:]) + ']=' + repr(filter_name) + '\nraise SystemExit(b.main())\n', encoding='utf-8')
    request = dict(source=str(source),output=str(target),profile=str(profile),office=engine.tool('soffice'),family=family,extension=source.suffix[1:],target=target.suffix[1:])
    manifest = profile / 'request.json'
    manifest.write_text(json.dumps(request,ensure_ascii=False),encoding='utf-8')
    document_process.run_bridge([formats.office_python(request['office']),'-B','-X','utf8',helper,manifest],profile,None,lambda:None,timeout=90)

def create_input(directory, extension):
    target = directory / ('실제입력.' + extension)
    if extension in LEGACY:
        family, name = LEGACY[extension]
        source = make_base(directory, {'문서':'docx','프레젠테이션':'pptx','스프레드시트':'xlsx'}[family])
        office_export(source,target,directory/'profile',family,name)
    elif extension in OPENXML:
        base, content_type = OPENXML[extension]
        source = make_base(directory,base)
        main = {'docx':'/word/document.xml','pptx':'/ppt/presentation.xml','xlsx':'/xl/workbook.xml'}[base]
        with zipfile.ZipFile(source) as package, zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as output:
            for entry in package.infolist():
                data = package.read(entry)
                if entry.filename == '[Content_Types].xml':
                    root = ET.fromstring(data)
                    item = next(x for x in root if x.get('PartName') == main)
                    # 형식 탐지기가 기본 네임스페이스 선언을 그대로 읽도록 원본 XML 표현을 보존한다.
                    original = item.get('ContentType').encode('utf-8')
                    assert data.count(original) == 1
                    data = data.replace(original, content_type.encode('utf-8'))
                output.writestr(entry,data)
    elif extension in ('sxw','stw'):
        mimetype = 'application/vnd.sun.xml.writer' + ('.template' if extension == 'stw' else '')
        body = '<?xml version="1.0" encoding="UTF-8"?><office:document-content xmlns:office="http://openoffice.org/2000/office" xmlns:text="http://openoffice.org/2000/text" office:class="text" office:version="1.0"><office:body><text:p>' + MARKER + '</text:p></office:body></office:document-content>'
        manifest = '<?xml version="1.0"?><manifest:manifest xmlns:manifest="http://openoffice.org/2001/manifest"><manifest:file-entry manifest:media-type="' + mimetype + '" manifest:full-path="/"/><manifest:file-entry manifest:media-type="text/xml" manifest:full-path="content.xml"/></manifest:manifest>'
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as package:
            package.writestr('mimetype',mimetype)
            package.writestr('content.xml',body)
            package.writestr('META-INF/manifest.xml',manifest)
    elif extension == 'slk':
        target.write_text('ID;PFlipRing\nC;X1;Y1;K"' + MARKER + '"\nC;X2;Y1;K123\nE\n',encoding='ascii')
    return target

def check_case(directory, extension):
    import engine
    directory.mkdir(parents=True,exist_ok=False)
    if extension == 'hwp_roundtrip':
        return check_hwp_roundtrip(directory)
    source = create_input(directory,extension)
    before = sha(source)
    family = engine.classify(source)[0]
    output = Path(engine.convert(source,{'문서':'docx','프레젠테이션':'pptx','스프레드시트':'xlsx'}[family]))
    assert MARKER in output_text(output), '합성 입력의 실제 본문 누락'
    assert before == sha(source), '원본 변경'
    return dict(extension=extension,result='passed',source_sha256=before,output_sha256=sha(output),source_preserved=True)

def check_hwp_roundtrip(directory):
    import engine
    from docx import Document
    from docx.shared import Inches
    from PIL import Image
    source = directory / '한글표그림.docx'
    picture = directory / '그림.png'
    Image.new('RGB',(100,60),(30,80,150)).save(picture)
    document = Document()
    document.add_paragraph(MARKER)
    run = document.add_paragraph().add_run('한글 보존 PUVKID')
    run.bold = True
    run.italic = True
    table = document.add_table(rows=2,cols=2)
    for cell,value in zip([c for row in table.rows for c in row.cells],['항목','값','변환','123']):
        cell.text = value
    document.add_picture(str(picture),width=Inches(1))
    document.save(source)
    before = sha(source)
    results = []
    for extension in ('hwp','hwpx'):
        native = Path(engine.convert(source,extension))
        native_before = sha(native)
        returned = Path(engine.convert(native,'docx'))
        text = output_text(returned)
        assert MARKER in text and '한글 보존 PUVKID' in text
        result_document = Document(returned)
        assert any(len(t.rows)>=2 and len(t.columns)>=2 and t.cell(1,0).text=='변환' and t.cell(1,1).text=='123' for t in result_document.tables), '표 내용 누락'
        with zipfile.ZipFile(returned) as package:
            assert any(name.startswith('word/media/') for name in package.namelist()), '포함 그림 누락'
        assert sha(native) == native_before
        results.append(dict(extension=extension,native_sha256=native_before,returned_sha256=sha(returned),text=True,table=True,image=True))
    assert sha(source) == before
    return dict(result='passed',source_preserved=True,source_sha256=before,reader='LibreOffice/H2Orestart',results=results)

def main():
    base = Path(sys.argv[1]).resolve()
    if len(sys.argv) > 2:
        print(json.dumps(check_case(base/sys.argv[2],sys.argv[2]),ensure_ascii=False))
        return
    sys.path.insert(0,str(ROOT/'검사도구'))
    from release_capture import run_check
    results = []
    for extension in [*LEGACY,*OPENXML,'sxw','stw','slk']:
        result = run_check(dict(id=extension,argv=[sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),str(base),extension],cwd=str(SOURCE),timeout_seconds=180))
        results.append(result)
        (base.parent/'문서템플릿_검사결과1121.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:result.get(k) for k in ('id','status','exit_code','duration_seconds')},ensure_ascii=False),flush=True)

if __name__ == '__main__':
    main()
