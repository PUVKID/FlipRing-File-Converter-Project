"""새 미리보기의 원본 보존·취소와 해결 동작의 경계를 검사한다."""
from pathlib import Path
import tempfile,threading,unittest
from PIL import Image

class PreviewRecoveryTests(unittest.TestCase):
    def test_actual_preview_preserves_source_and_existing_output(self):
        from conversion_preview import PreviewSession
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'사진.png';Image.new('RGBA',(32,20),(255,0,0,90)).save(p)
            before=p.read_bytes();existing=p.with_suffix('.jpg');existing.write_bytes(b'existing')
            with PreviewSession(p,'jpg') as session:
                result=session.run(threading.Event())
                self.assertTrue(Path(result.output).is_file());self.assertEqual(result.output_bytes,Path(result.output).stat().st_size)
                self.assertNotEqual(Path(result.output).parent,p.parent)
                with Image.open(result.output) as image:self.assertEqual(image.size,(32,20))
                self.assertTrue(result.warnings)
                output=Path(result.output)
            self.assertFalse(output.exists());self.assertEqual(p.read_bytes(),before);self.assertEqual(existing.read_bytes(),b'existing')
            self.assertEqual(set(x.name for x in p.parent.iterdir()),{'사진.png','사진.jpg'})

    def test_cancel_has_no_published_result(self):
        from conversion_preview import PreviewSession
        import engine
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'사진.png';Image.new('RGB',(4,4)).save(p);cancel=threading.Event();cancel.set()
            with PreviewSession(p,'jpg') as session:
                with self.assertRaises(engine.Cancelled):session.run(cancel)
            self.assertEqual(len(list(p.parent.iterdir())),1)

    def test_large_or_directory_input_not_copied(self):
        from conversion_preview import PreviewSession
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):PreviewSession(folder,'zip')
            p=Path(folder)/'file.txt';p.write_text('hello')
            with self.assertRaises(ValueError):PreviewSession(p,'pdf',max_bytes=2)

    def test_only_allowed_missing_tool_has_install_action(self):
        from recovery import explain_failure
        a=explain_failure('FFmpeg 도구를 설치해 주세요.','ko');self.assertEqual(a.action,'install');self.assertEqual(a.tool,'ffmpeg')
        b=explain_failure('UnknownTool 설치가 필요합니다.','en');self.assertNotEqual(b.action,'install')

    def test_missing_source_named_after_tool_is_not_an_install_request(self):
        from recovery import explain_failure
        result=explain_failure("File not found: 'E:/사진/ffmpeg.mp4'",'en')
        self.assertEqual(result.action,'select')

    def test_failure_messages_have_actionable_specific_causes(self):
        from recovery import explain_failure
        for raw,action in [('입력이 없거나 이동되었습니다.','select'),('여유 공간이 부족합니다.','location'),('암호화된 PDF는 지원하지 않습니다.','unlock'),('처리 제한 시간을 초과했습니다.','retry')]:
            with self.subTest(raw=raw):
                result=explain_failure(raw,'ko');self.assertEqual(result.action,action);self.assertTrue(result.title);self.assertTrue(result.body)
        result=explain_failure('Module use of python312.dll conflicts with this version of Python','en');self.assertEqual(result.action,'helpers');self.assertNotIn('다시',result.body)

    def test_animation_to_still_warns_about_lost_frames(self):
        from conversion_preview import PreviewSession
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'움직임.gif';Image.new('RGB',(12,8),'red').save(p,save_all=True,append_images=[Image.new('RGB',(12,8),'blue')],duration=100,loop=0)
            with PreviewSession(p,'png') as session:
                result=session.run(threading.Event());self.assertTrue(any('프레임' in x for x in result.warnings))

if __name__=='__main__':unittest.main()
