# 자체 HEIC 시험 자료의 출처와 재생성

PUVKID의 파일 변환 검사를 위해 색상과 도형을 직접 계산한 시험 자료입니다. 외부 사진이나 기존 시험 사진의 픽셀을 사용하지 않았습니다. `자체HEIC_생성.py`가 수평·수직 그라데이션, 체크 패턴, 사각형·타원, 검정·흰색·기본색 띠를 만듭니다.

- 크기 48×36, RGB 8비트, 단일 이미지, 알파 없음, ICC 없음, 4:2:0 색차 표본화입니다.
- HEIC NCLX는 color_primaries=1, transfer_characteristics=13, matrix_coefficients=6, full_range_flag=1입니다.
- 저장 품질90은 손실 인코딩 조건입니다. PNG 원본과 HEIC가 픽셀까지 같다고 주장하지 않습니다.
- 실제 생성 환경은 Python3.12.14, Pillow13.0.0, pillow-heif1.8.1, libheif1.23.6, x2654.3+1-e9b8812입니다. 원본 PNG·HEIC 해시는 생성조건과출처.json에 있습니다.

생성 도구만 사용할 별도 빈 폴더에 `자체HEIC_생성.py`, `생성환경_준비.py`, `공식휠_출처와해시.json`을 복사하고 Windows x64 CPython3.12에서 다음 순서로 실행합니다. 이미 있는 시험 자료와 환경을 덮어쓰지 않도록 검사합니다.

```powershell
python -B -X utf8 생성환경_준비.py
python -I -B -X utf8 자체HEIC_생성.py
```

의존성은 해당 폴더의 생성전용환경에만 설치됩니다. 앱에는 읽기 전용 pi-heif-decoder를 계속 사용하며 이 생성용 인코더를 추가하지 않습니다. 공식 휠 주소·크기·SHA256을 고정하고 내려받은 바이트를 확인합니다. 설치된 생성 환경과 휠은 개발용이므로 앱 실행 파일에 포함할 필요가 없습니다. 의존성 자체의 라이선스는 각 공식 배포물에 따릅니다.

생성 코드는 동일한 패턴을 계산합니다. 다른 라이브러리·운영체제 조합에서 HEIC 파일 바이트가 동일하다는 보장은 하지 않습니다. 이번 저장 파일의 실제 해시와 인코더 버전을 구분해 확인해 주세요. 이 단일 RGB 자료는 알파·HDR·다중 프레임 이미지 전체의 검증을 대신하지 않습니다.

실제 앱 환경의 pi-heif-decoder1.7.0.post4에서 읽기와 PNG/JPG/TIFF/AVIF 변환을 확인했습니다. PNG/TIFF 출력은 디코딩한 HEIC의 픽셀과 같았고, 각 변환 전후 입력 파일 해시를 보존했습니다. 이는 이 후보에 대한 변환 확인이며 기존 전체 검사·설치본·모든 HEIC 호환 검증은 아닙니다.

공식 출처: [pillow-heif PyPI](https://pypi.org/project/pillow-heif/1.8.1/), [Pillow PyPI](https://pypi.org/project/Pillow/13.0.0/), [공식 이미지 저장 문서](https://pillow-heif.readthedocs.io/en/latest/saving-images.html).


생성 결과는 별도 작업 폴더의 `자체시험자료` 하위에 `sample.heic`와 `자체색상패턴.png`로 저장됩니다. 생성 도구를 소스 폴더에서 실행하지 말고 위의 빈 폴더 복사 절차를 사용해 주세요.
