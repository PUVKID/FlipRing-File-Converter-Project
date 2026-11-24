# SPDX-License-Identifier: GPL-3.0-or-later
# 수정일: 2026-11-25. H2Orestart 전체 그림 및 부분 자르기 회귀 검사.
"""사용자가 제공한 고정 표본을 별도 LibreOffice/H2Orestart로 읽어 검사합니다."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import shutil
import struct
import sys
import zipfile
import zlib
from PIL import Image
from lxml import etree
from hwpx.hwp5.cfb import CompoundFile, build_compound_file
from hwpx.hwp5.fileheader import parse_file_header

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def prepare_hwpx(source, output):
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(output, "w") as after:
        changes = 0
        for info in before.infolist():
            data = before.read(info.filename)
            if info.filename.startswith("Contents/section") and info.filename.endswith(".xml"):
                tree = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
                for clip in tree.xpath("//*[local-name()='pic']/*[local-name()='imgClip']"):
                    assert dict(clip.attrib) == {"left":"0","right":"9071","top":"0","bottom":"6803"}
                    for name, value in {"left":2268,"right":6804,"top":1701,"bottom":5103}.items():
                        clip.set(name, str(value))
                    changes += 1
                if changes:
                    data = etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
            after.writestr(info, data)
        assert changes == 1

def prepare_hwp(source, output):
    cf = CompoundFile(source.read_bytes())
    compressed = parse_file_header(cf.read("FileHeader")).compressed
    streams = []
    changes = 0
    for name in cf.stream_paths():
        data = cf.read(name)
        if name.startswith("BodyText/Section"):
            raw = bytearray(zlib.decompress(data, -15) if compressed else data)
            offset = 0
            while offset < len(raw):
                header = struct.unpack_from("<I", raw, offset)[0]
                offset += 4
                size = header >> 20
                if size == 0xfff:
                    size = struct.unpack_from("<I", raw, offset)[0]
                    offset += 4
                if (header & 0x3ff) == 0x55:
                    assert struct.unpack_from("<4i", raw, offset + 44) == (0,0,9071,6803)
                    struct.pack_into("<4i", raw, offset + 44, 2268,1701,6804,5103)
                    changes += 1
                offset += size
            if compressed:
                compressor = zlib.compressobj(wbits=-15)
                data = compressor.compress(bytes(raw)) + compressor.flush()
            else:
                data = bytes(raw)
        streams.append((name,data))
    assert changes == 1
    output.write_bytes(build_compound_file(streams, root_modified=cf.root.modified, root_clsid=cf.root.clsid))


def check_image(output, expected):
    with zipfile.ZipFile(output) as package:
        names = [n for n in package.namelist() if n.startswith("word/media/")]
        assert len(names) == 1, names
        with Image.open(io.BytesIO(package.read(names[0]))) as picture:
            actual = picture.convert("RGB")
    assert actual.size == expected.size, f"그림 크기 {actual.size} != {expected.size}"
    assert actual.tobytes() == expected.tobytes(), "전체 RGB 픽셀 불일치"
    last = actual.crop((0,actual.height-1,actual.width,actual.height)).tobytes()
    expected_last = expected.crop((0,expected.height-1,expected.width,expected.height)).tobytes()
    assert last == expected_last, "마지막 행 불일치"
    return {"image_size":list(actual.size),"rgb_sha256":hashlib.sha256(actual.tobytes()).hexdigest(),
            "last_row_sha256":hashlib.sha256(last).hexdigest()}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir",type=Path,help="제품 engine.py가 있는 소스 폴더")
    parser.add_argument("--hwp",type=Path,help="수정하지 않은 64×48 전체 그림 HWP 표본")
    parser.add_argument("--hwpx",type=Path,help="수정하지 않은 같은 그림 HWPX 표본")
    parser.add_argument("--image",type=Path,required=True,help="독립 기대값인 원본 64×48 PNG")
    parser.add_argument("--expected-image-sha256",required=True,help="보존된 원본 명세의 PNG SHA-256")
    parser.add_argument("--oxt",type=Path,help="이번 실행에서 명시적으로 사용할 H2Orestart OXT")
    parser.add_argument("--output",type=Path,help="아직 존재하지 않는 결과 폴더")
    parser.add_argument("--check-report",type=Path,help="이미 실행한 네 결과만 다시 읽고 픽셀 대조. 변환 없음")
    args = parser.parse_args()
    if sha(args.image) != args.expected_image_sha256:
        raise ValueError("고정 원본 PNG 해시가 다릅니다.")
    with Image.open(args.image) as opened:
        full = opened.convert("RGB")
    if full.size != (64,48):
        raise ValueError("이 고정 회귀의 원본 크기는 64×48이어야 합니다.")
    partial = full.crop((16,12,48,36))
    if args.check_report:
        loaded = json.loads(args.check_report.read_text(encoding="utf-8-sig"))
        cases = loaded["cases"] if isinstance(loaded,dict) else loaded
        assert len(cases) == 4
        assert {(x["extension"],x["partial_clip"]) for x in cases} == {("hwp",False),("hwpx",False),("hwp",True),("hwpx",True)}
        for case in cases:
            assert sha(Path(case["source"])) == case["source_sha256"]
            assert sha(Path(case["output"])) == case["output_sha256"]
            check_image(Path(case["output"]),partial if case["partial_clip"] else full)
        print(json.dumps({"checks":4,"conversion_count":0,"result":"passed","mode":"기존 결과의 실제 파일 대조"},ensure_ascii=False))
        return 0
    if not all((args.source_dir,args.hwp,args.hwpx,args.oxt,args.output)):
        parser.error("변환 실행에는 --source-dir --hwp --hwpx --oxt --output이 모두 필요합니다.")
    if args.output.exists():
        raise ValueError("기존 출력 폴더를 덮어쓰지 않습니다.")
    for path in (args.source_dir/"engine.py",args.hwp,args.hwpx,args.oxt):
        if not path.is_file():
            raise ValueError("필수 원본 또는 도구가 없습니다: "+str(path))
    args.output.mkdir(parents=True)
    sys.path.insert(0,str(args.source_dir.resolve()))
    import engine
    original_status = engine.hwp_status
    def explicit_oxt_status(office_path=None):
        status = original_status(office_path)
        if not status["ready"]:
            raise RuntimeError(status["message"])
        status["oxt"] = str(args.oxt.resolve())
        return status
    engine.hwp_status = explicit_oxt_status
    result = {"oxt_sha256":sha(args.oxt),"image_sha256":sha(args.image),"cases":[]}
    for is_partial in (False,True):
        for extension,original in (("hwp",args.hwp),("hwpx",args.hwpx)):
            folder = args.output / (("부분자르기-" if is_partial else "전체-")+extension)
            folder.mkdir()
            source = folder / ("고정표본."+extension)
            original_hash = sha(original)
            if is_partial:
                (prepare_hwp if extension=="hwp" else prepare_hwpx)(original,source)
            else:
                shutil.copyfile(original,source)
                assert sha(source) == original_hash
            before = sha(source)
            output = Path(engine.convert(str(source),"docx"))
            assert sha(source) == before and sha(original) == original_hash, "원본 변경"
            item = {"extension":extension,"partial_clip":is_partial,"source":str(source.resolve()),
                    "source_sha256":before,"output":str(output.resolve()),"output_sha256":sha(output)}
            item.update(check_image(output,partial if is_partial else full))
            result["cases"].append(item)
            (args.output/"검사결과.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"checks":4,"conversion_count":4,"result":"passed","oxt_sha256":result["oxt_sha256"]},ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

