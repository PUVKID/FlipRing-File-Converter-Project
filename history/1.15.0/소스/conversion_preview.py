"""원본 폴더 밖의 임시 사본에만 쓰는 실제 변환 미리보기."""
from dataclasses import dataclass
from pathlib import Path
import tempfile
import engine

MAX_PREVIEW_BYTES = 128 * 1024 * 1024

@dataclass(frozen=True)
class PreviewResult:
    source: str
    output: str
    source_bytes: int
    output_bytes: int
    warnings: tuple[str, ...]

def format_warnings(source, destination, language='ko'):
    en=language=='en';kind,extension=engine.classify(source);warnings=[]
    if kind=='이미지':
        from PIL import Image
        frames=1
        try:
            with Image.open(source) as image:frames=getattr(image,'n_frames',1)
        except (OSError,ValueError):
            pass  # SVG 등 기존 변환기가 처리한 형식은 PIL 메타데이터를 요구하지 않는다.
        if frames>1:
            warnings.append((f'The original has {frames} frames. Animation or additional frames may be lost in this output.' if en else f'원본은 {frames}프레임입니다. 출력에서 움직임이나 나머지 프레임이 사라질 수 있습니다.'))
    if destination in ('jpg','bmp'):
        warnings.append('Transparency may be flattened; JPG uses lossy compression.' if en else '투명 배경이 사라질 수 있으며 JPG는 손실 압축을 사용합니다.')
    if kind in ('문서','프레젠테이션','스프레드시트'):
        warnings.append('Fonts, pagination and complex layouts may change. Check the actual preview.' if en else '글꼴·쪽 나눔·복잡한 서식은 달라질 수 있습니다. 실제 결과를 확인하세요.')
    if destination in ('csv','tsv','txt'):
        warnings.append('Plain text outputs cannot preserve all formatting, formulas or multiple sheets.' if en else '텍스트 형식은 서식·수식·여러 시트를 모두 보존하지 못합니다.')
    if destination=='hwp':
        warnings.append('HWP 5 export is experimental.' if en else 'HWP 5 저장은 실험적 기능입니다.')
    if kind in ('오디오','비디오') and destination in ('mp3','m4a','ogg','opus','gif'):
        warnings.append('Re-encoding may reduce quality or discard tracks and metadata.' if en else '다시 인코딩하면 품질·일부 트랙·메타데이터가 달라질 수 있습니다.')
    return tuple(warnings)

class PreviewSession:
    def __init__(self, source, destination, *, max_bytes=MAX_PREVIEW_BYTES, language='ko'):
        self.source=Path(source).resolve(strict=True);self.destination=destination;self.language=language
        if not self.source.is_file():raise ValueError('폴더 대신 파일 하나를 선택해 주세요. / Select one file, not a folder.')
        self.initial=self.source.stat();self.max_bytes=max_bytes
        if self.initial.st_size>max_bytes:raise ValueError('미리보기는 128 MiB 이하 파일을 지원합니다. / Preview supports files up to 128 MiB.')
        if destination not in engine.targets([self.source]):raise ValueError('지원하지 않는 미리보기 형식입니다. / Unsupported preview format.')
        self._temporary=None

    def __enter__(self):
        self._temporary=tempfile.TemporaryDirectory(prefix='flipring-preview-')
        return self

    def run(self,cancel):
        if self._temporary is None:raise RuntimeError('PreviewSession context is required.')
        def check():
            if cancel.is_set():raise engine.Cancelled('미리보기를 취소했습니다. / Preview cancelled.')
        check();missing=engine.requirement(self.source,self.destination)
        if missing:raise RuntimeError(f'{missing} 설치가 필요합니다.')
        duplicate=Path(self._temporary.name)/self.source.name;total=0
        with self.source.open('rb') as original,duplicate.open('xb') as target:
            while True:
                check();chunk=original.read(1024*1024)
                if not chunk:break
                total+=len(chunk)
                if total>self.max_bytes:raise ValueError('미리보기 크기 제한을 초과했습니다. / Preview size limit exceeded.')
                target.write(chunk)
        observed=self.source.stat()
        if (observed.st_size,observed.st_mtime_ns)!=(self.initial.st_size,self.initial.st_mtime_ns):
            raise ValueError('파일이 변경되었습니다. 다시 선택해 주세요. / File changed; select it again.')
        check();output=Path(engine.convert(duplicate,self.destination,cancel=cancel));check()
        observed=self.source.stat()
        if (observed.st_size,observed.st_mtime_ns)!=(self.initial.st_size,self.initial.st_mtime_ns):
            raise ValueError('변환 중 원본이 변경되었습니다. 다시 선택해 주세요. / File changed during preview; select it again.')
        if not output.resolve().is_relative_to(Path(self._temporary.name).resolve()):raise RuntimeError('Unexpected preview output path.')
        size=sum(p.stat().st_size for p in output.rglob('*') if p.is_file()) if output.is_dir() else output.stat().st_size
        return PreviewResult(str(self.source),str(output),total,size,format_warnings(self.source,self.destination,self.language))

    def __exit__(self,*unused):
        if self._temporary is not None:self._temporary.cleanup();self._temporary=None
