"""자체 합성 문서로 매크로 차단과 외부 연결 미갱신을 실제 검사한다."""
from pathlib import Path
from html import escape
import json
import tempfile
import unittest
import zipfile

import document_formats
import document_process
import engine


def content_xml(body, scripts=''):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
            'xmlns:script="urn:oasis:names:tc:opendocument:xmlns:script:1.0" '
            'xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:dom="http://www.w3.org/2001/xml-events" '
            'xmlns:ooo="http://openoffice.org/2004/office" office:version="1.2">'
            '<office:scripts>' + scripts + '</office:scripts><office:automatic-styles/>'
            '<office:body><office:text>' + body + '</office:text></office:body></office:document-content>')


def macro_document(path, sentinel):
    event = ('<office:event-listeners><script:event-listener script:language="ooo:script" '
             'script:event-name="dom:load" xlink:type="simple" '
             'xlink:href="vnd.sun.star.script:Standard.Module1.Main?language=Basic&amp;location=document"/>'
             '</office:event-listeners>')
    code = ('Sub Main\nOpen "' + str(sentinel) + '" For Output As #1\n'
            'Print #1, "자체 매크로 양성 대조"\nClose #1\nEnd Sub')
    library_ns = 'xmlns:library="http://openoffice.org/2000/library"'
    files = {
        'content.xml': content_xml('<text:p>매크로 차단 시험 본문 PUVKID</text:p>', event),
        'Basic/script-lc.xml': '<library:libraries ' + library_ns + '><library:library library:name="Standard" library:link="false"/></library:libraries>',
        'Basic/Standard/script-lb.xml': '<library:library ' + library_ns + ' library:name="Standard" library:readonly="false" library:passwordprotected="false"><library:element library:name="Module1"/></library:library>',
        'Basic/Standard/Module1.xml': '<script:module xmlns:script="http://openoffice.org/2000/script" script:name="Module1" script:language="StarBasic"><![CDATA[' + code + ']]></script:module>',
    }
    manifest = ('<?xml version="1.0" encoding="UTF-8"?>'
                '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">'
                '<manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/>')
    manifest += ''.join('<manifest:file-entry manifest:full-path="' + name + '" manifest:media-type="text/xml"/>' for name in files)
    manifest += '</manifest:manifest>'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('mimetype', 'application/vnd.oasis.opendocument.text', compress_type=zipfile.ZIP_STORED)
        for name, value in files.items():
            archive.writestr(name, value.encode('utf-8'))
        archive.writestr('META-INF/manifest.xml', manifest.encode('utf-8'))


class ActualDocumentSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='fr-security110-')
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_01_macro_positive_control_runs_only_in_private_profile_and_product_blocks_it(self):
        sentinel = self.root / 'macro-sentinel.txt'
        source = self.root / '자동 매크로.odt'
        macro_document(source, sentinel)
        profile = self.root / 'positive-profile'
        document_formats.write_secure_profile(profile)
        settings = profile / 'user/registrymodifications.xcu'
        raw = settings.read_text(encoding='utf-8')
        raw = raw.replace('oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value>',
                          'oor:name="DisableMacrosExecution" oor:op="fuse"><value>false</value>')
        raw = raw.replace('<value>3</value>', '<value>0</value>')
        raw = raw.replace('oor:name="DisableActiveContent" oor:op="fuse"><value>true</value>',
                          'oor:name="DisableActiveContent" oor:op="fuse"><value>false</value>')
        raw = raw.replace('oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value>',
                          'oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>false</value>')
        settings.write_bytes(raw.encode('utf-8'))
        helper = self.root / 'positive_control.py'
        helper.write_bytes(('import sys\nfrom pathlib import Path\n'
                            'sys.path.insert(0, ' + repr(str(Path(engine.__file__).parent)) + ')\n'
                            'import document_bridge\noriginal = document_bridge.load_options\n'
                            'def controlled(handler, extension):\n'
                            '    options = original(handler, extension)\n'
                            '    options["MacroExecutionMode"] = 4\n'
                            '    options["Hidden"] = False\n'
                            '    options["ReadOnly"] = False\n'
                            '    return options\n'
                            'document_bridge.load_options = controlled\n'
                            'raise SystemExit(document_bridge.main())\n').encode('utf-8'))
        office = engine.tool('soffice')
        self.assertIsNotNone(office)
        request = {'source': str(source), 'output': str(self.root / 'positive.txt'), 'profile': str(profile),
                   'office': office, 'family': '문서', 'extension': 'odt', 'target': 'txt'}
        manifest = profile / 'request.json'
        manifest.write_bytes(json.dumps(request, ensure_ascii=False).encode('utf-8'))
        document_process.run_bridge([document_formats.office_python(office), '-X', 'utf8', helper, manifest],
                                    profile, None, lambda: None, timeout=60)
        self.assertTrue(sentinel.is_file(), '실제로 실행되는 자동 매크로 양성 대조가 필요합니다.')
        sentinel.unlink()
        output = Path(engine.convert(source, 'txt'))
        self.assertIn('매크로 차단 시험 본문', output.read_text(encoding='utf-8-sig'))
        self.assertFalse(sentinel.exists(), '제품 변환에서 문서 매크로가 실행됐습니다.')

    def test_02_external_local_section_keeps_cached_text_without_reading_new_content(self):
        external = self.root / 'external.txt'
        external.write_text('외부에서 새로 읽으면 안 되는 비밀표식 EXTERNAL_NEW_CONTENT', encoding='utf-8')
        source = self.root / '연결 구역.fodt'
        body = ('<text:p>플립링 연결 구역 시험</text:p><text:section text:name="Linked">'
                '<text:section-source xlink:href="' + escape(external.as_uri(), quote=True) + '" '
                'xlink:type="simple" text:filter-name="Text"/>'
                '<text:p>고정 캐시 내용 CACHED_ORIGINAL_CONTENT</text:p></text:section>')
        source.write_bytes(content_xml(body).encode('utf-8'))
        output = Path(engine.convert(source, 'txt'))
        result = output.read_text(encoding='utf-8-sig')
        self.assertIn('CACHED_ORIGINAL_CONTENT', result)
        self.assertNotIn('EXTERNAL_NEW_CONTENT', result)


if __name__ == '__main__':
    unittest.main()
