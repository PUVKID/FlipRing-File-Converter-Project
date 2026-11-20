# GCC 런타임의 라이선스와 상응 소스

확인일: 2026-10-21. 이 폴더 이름의 `ubuntu-gcc`는 초기 조사 분류이며, 최종 확인된 두 DLL의 실제 일치 패키지는 **Debian**입니다. 폴더명으로 Ubuntu 패키지라고 판단하지 마세요.

## 배포 DLL과 정확히 일치한 원본 패키지

- 패키지: `gcc-mingw-w64-x86-64-posix-runtime`
- 버전/아키텍처: `14.2.0-19+27+b1`, `amd64`
- 공식 원본: https://deb.debian.org/debian/pool/main/g/gcc-mingw-w64/gcc-mingw-w64-x86-64-posix-runtime_14.2.0-19+27+b1_amd64.deb
- 공식 선택 페이지: https://packages.debian.org/en/trixie/amd64/gcc-mingw-w64-x86-64-posix-runtime/download
- DEB 크기: 13,037,152바이트
- DEB SHA-256: `c898d96177574a8a7238564a1e799d8ddfed5a3d2ea005510305f9ad466a6f59`

실제 압축을 풀어 다음 두 파일의 크기와 SHA-256을 제품 `vendor/tesseract`의 DLL과 비교했고, 두 파일 모두 완전히 일치했습니다. 제품 DLL은 변경하지 않았습니다.

| DLL | DEB 내부 위치 | 바이트 수 | SHA-256 |
|---|---|---:|---|
| libgcc_s_seh-1.dll | usr/lib/gcc/x86_64-w64-mingw32/14-posix/libgcc_s_seh-1.dll | 954773 | 172cfdc9d83703ec0a0ca2cee08f6cf2a166b801717ee51a56b3a63b36bc2f83 |
| libstdc++-6.dll | usr/lib/gcc/x86_64-w64-mingw32/14-posix/libstdc++-6.dll | 26390974 | 5fe5d4d8f6636eb6f2dc55be99dc5dc8a6c40db1abdf592e84480d1e6985abd0 |

패키지 자체의 `control` 메타데이터는 `Source: gcc-mingw-w64 (27)` 및 `Built-Using: gcc-14 (= 14.2.0-19)`를 명시합니다. 원문은 `debian14-runtime-control.txt`, 비교 결과는 `debian14-runtime-comparison.json`에 있습니다. 기록에 들어 있는 과거 PC 경로는 조사 당시의 실행 증거이며 앱 빌드에 필요한 고정 경로가 아닙니다.

## 로컬에 포함한 상응 소스와 고지

아래 원본 파일은 출하물에 로컬로 포함합니다. 소스의 URL만 제공하는 방식으로 대신하지 않습니다.

1. `gcc-mingw-w64_27.dsc`, `gcc-mingw-w64_27.tar.xz`: 정확한 MinGW 교차 빌드 패키징과 Debian 빌드 규칙입니다. 출처는 https://deb.debian.org/debian/pool/main/g/gcc-mingw-w64/ 입니다.
2. `gcc-14_14.2.0-19.dsc`, `gcc-14_14.2.0.orig.tar.gz`, `gcc-14_14.2.0-19.debian.tar.xz`: `Built-Using`이 지정한 GCC 14.2.0-19의 원본과 Debian 패치·패키징입니다. 출처는 https://deb.debian.org/debian/pool/main/g/gcc-14/ 입니다.
3. `debian27/`, `debian-gcc14/`: 위 원본에서 읽기 편하도록 따로 꺼낸 저작권·빌드 규칙·변경 기록이며, 전체 소스는 위 원본 압축 자료에 있습니다.
4. `COPYING3.txt`, `COPYING.RUNTIME.txt`, `COPYING.txt`: GCC 14.2.0 원본 내부에서 그대로 꺼낸 GNU GPL 버전 3, GCC Runtime Library Exception 버전 3.1, GPL 버전 2 원문입니다. 파일별 추가 고지와 저작권은 원본 소스 및 `debian-gcc14/copyright`를 함께 보세요.

GCC 원본 `orig.tar.gz`에는 `gcc-14-14.2.0/gcc-14.2.0-dfsg.tar.xz`와 `newlib-4.4.0.20231231.tar.xz`가 들어 있습니다. 이 구조를 변경하지 않고 제공하며, Debian 패치도 빠뜨리지 않습니다. 각 DSC가 명시한 참조 파일의 SHA-256을 대조했습니다. 원본 PGP 서명은 보존했지만 이 PC에서 서명자의 키로 검증한 것은 아닙니다.

## 소스 확인과 빌드 규칙

Debian 도구가 있는 Linux 환경에서 아래와 같이 각 소스를 재조립할 수 있습니다. 이는 실행 안내이며 이 Windows PC에서 GCC를 재컴파일한 결과가 아닙니다.

```sh
dpkg-source -x gcc-14_14.2.0-19.dsc
dpkg-source -x gcc-mingw-w64_27.dsc
```

교차 런타임의 실제 빌드 절차는 `gcc-mingw-w64-27/debian/rules`가 정의합니다. 해당 규칙은 설치된 `gcc-14-source`의 소스와 패치를 사용하고 POSIX/Win32 스레드 변형을 빌드합니다. 원본과 같은 소스가 되려면 `gcc-14-source` 버전을 `14.2.0-19`로 맞추고, `debian/control`의 빌드 의존성을 준비해야 합니다. GCC 네이티브 패키징의 소스 준비법과 패치는 GCC 14 Debian 소스의 `debian/README.source` 및 `debian/rules`에 들어 있습니다. 컴파일러와 빌드 환경의 완전한 재현, 재컴파일 결과의 바이트 동일성은 이번 확인 범위가 아닙니다.

두 배포 DLL과 공식 Debian DEB 안의 파일이 바이트 단위로 같다는 것은 직접 확인했습니다. 이를 GCC를 직접 다시 빌드하여 동일 바이너리를 만들었다는 뜻으로 해석하지 마세요.

## 비교 도구 재실행

`download_one.py`와 `inspect_runtime.py`는 출처 확인용 보조 소스입니다. 제품 실행에는 필요하지 않습니다. `inspect_runtime.py`는 7-Zip 실행 파일 위치와 제품 DLL 폴더를 명시적 인자로 받으므로 원래 개발 PC의 경로를 요구하지 않습니다. 이 폴더에서 다음 형식으로 실행합니다. DEB는 위 공식 URL에서 받아 같은 폴더에 놓아야 합니다.

```powershell
python -B -X utf8 inspect_runtime.py "C:\사용하는도구\7z.exe" "..\..\..\vendor\tesseract" "gcc-mingw-w64-x86-64-posix-runtime_14.2.0-19+27+b1_amd64.deb" "debian14"
```

`출하목록.json`과 `SHA256SUMS.txt`가 필요한 고지·상응 소스 파일을 지정합니다. 조사용 `*.deb`, `*-data.tar.*`, Ubuntu 13 후보 자료, 실패 기록은 배포 대상이 아닙니다. Ubuntu `13.2.0-6ubuntu1+26.1` 후보의 두 DLL은 제품과 일치하지 않았으므로 실제 출처로 쓰지 않습니다.
