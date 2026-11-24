# SPDX-License-Identifier: GPL-3.0-or-later
# 수정일: 2026-11-25. 원본 전체 그림 경계 패치 재빌드.
"""원본 OXT의 나머지 항목을 보존하며 전체 그림 경계 패치만 재빌드합니다."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import os
import struct
import subprocess
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
UPSTREAM_SHA = "f36c19fa6b7dff1cf34114d926bdc088e6bcfa7fdc93d67eaafd3f572be1d62c"

def sha(data):
    return hashlib.sha256(data).hexdigest()

def replace_entries(original, replacements, allowed_new=()):
    result = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as before, zipfile.ZipFile(result,"w") as after:
        names = before.namelist()
        if len(names) != len(set(names)) or set(replacements).difference(names) != set(allowed_new):
            raise ValueError("중복 항목 또는 원본에 없는 교체 항목입니다.")
        for info in before.infolist():
            after.writestr(info,replacements.get(info.filename,before.read(info.filename)))
        for name in sorted(allowed_new):
            info = zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            after.writestr(info,replacements[name])
    with zipfile.ZipFile(io.BytesIO(original)) as before, zipfile.ZipFile(io.BytesIO(result.getvalue())) as after:
        assert before.namelist() + sorted(allowed_new) == after.namelist()
        assert all(before.read(n) == after.read(n) for n in before.namelist() if n not in replacements)
    return result.getvalue()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jdk-home",required=True,type=Path)
    parser.add_argument("--libreoffice-home",required=True,type=Path)
    parser.add_argument("--upstream-oxt",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--receipt",type=Path)
    args = parser.parse_args()
    upstream = args.upstream_oxt.read_bytes()
    if sha(upstream) != UPSTREAM_SHA:
        raise ValueError("정확한 v0.8.0 원본 OXT 해시가 아닙니다.")
    if args.output.exists() or args.output.resolve() == args.upstream_oxt.resolve():
        raise ValueError("원본이나 기존 결과를 덮어쓰지 않습니다.")
    javac = args.jdk_home / "bin/javac.exe"
    uno = args.libreoffice_home / "program/classes/libreoffice.jar"
    source = HERE / "수정소스/soffice/ConvGraphics.java"
    with zipfile.ZipFile(io.BytesIO(upstream)) as package:
        original_jar = package.read("H2Orestart.jar")
    with tempfile.TemporaryDirectory(prefix="h2o-build-",dir=args.output.parent) as temp:
        folder = Path(temp)
        jar = folder / "H2Orestart-original.jar"
        jar.write_bytes(original_jar)
        classes = folder / "classes"
        classes.mkdir()
        command = [str(javac),"-encoding","UTF-8","--release","8","-implicit:none",
                   "-classpath",str(jar)+os.pathsep+str(uno),"-d",str(classes),str(source)]
        process = subprocess.run(command,cwd=Path.cwd(),stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90,
                                 creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),check=False)
        receipt = {"argv":command,"cwd":str(Path.cwd()),"exit_code":process.returncode,
                   "stdout":process.stdout.decode("utf-8","strict"),"stderr":process.stderr.decode("utf-8","strict")}
        if args.receipt:
            args.receipt.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        if process.returncode:
            print(json.dumps(receipt,ensure_ascii=False),flush=True)
            return process.returncode
        replacements = {p.relative_to(classes).as_posix():p.read_bytes() for p in classes.rglob("*.class")}
        if set(replacements) != {"soffice/ConvGraphics.class","soffice/ConvGraphics$1.class","soffice/ConvGraphics$2.class"}:
            raise ValueError("예상한 세 컴파일 클래스와 다릅니다: "+str(sorted(replacements)))
        assert all(struct.unpack(">H",b[6:8])[0] == 52 for b in replacements.values())
        for name,data in replacements.items():
            (args.output.parent / Path(name).name).write_bytes(data)
        patched_jar = replace_entries(original_jar,replacements,allowed_new=("soffice/ConvGraphics$2.class",))
        patched_oxt = replace_entries(upstream,{"H2Orestart.jar":patched_jar})
        with args.output.open("xb") as output:
            output.write(patched_oxt)
        result = {"source_sha256":sha(source.read_bytes()),"upstream_oxt_sha256":sha(upstream),
                  "output_bytes":len(patched_oxt),"output_sha256":sha(patched_oxt),
                  "original_jar_sha256":sha(original_jar),"patched_jar_sha256":sha(patched_jar),
                  "classes":{name:{"bytes":len(b),"sha256":sha(b),"major_version":52}
                             for name,b in sorted(replacements.items())},
                  "javac_sha256":sha(javac.read_bytes()),"uno_jar_sha256":sha(uno.read_bytes()),
                  "uno_jar_bytes":uno.stat().st_size,
                  "unchanged_jar_entries_verified":True,"unchanged_oxt_entries_verified":True}
        if args.receipt:
            receipt["result"] = result
            args.receipt.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

