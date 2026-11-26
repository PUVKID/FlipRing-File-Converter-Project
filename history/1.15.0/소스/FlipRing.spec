from pathlib import Path
import os
source = Path(os.environ['FLIPRING_SOURCE'])
# Windows 배포에 필요한 Qt 기본 모듈만 포함한다.
from PyInstaller.utils.hooks import collect_data_files
a = Analysis([str(source / 'app.py')], pathex=[str(source)], binaries=[], datas=[(str(source / 'assets'), 'assets'), (str(source / 'vendor'), 'vendor'), (str(source / 'document_bridge.py'), '.'), (str(source / 'document_formats.py'), '.'), (str(source / 'document_xlsb.py'), '.')] + collect_data_files('pypdfium2_raw') + collect_data_files('hwpx'), hiddenimports=['PIL.AvifImagePlugin', 'PIL.WebPImagePlugin'], excludes=['tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtQml', 'PySide6.QtQuick', 'olefile'])
blocked = ('Qt6Pdf', 'Qt6Qml', 'Qt6Quick', 'Qt6VirtualKeyboard')
def required(entry):
    path = entry[0].replace('\\', '/')
    if any(part in path for part in blocked): return False
    if '/plugins/platforminputcontexts/' in path or '/plugins/qmltooling/' in path: return False
    if path.endswith('/qpdf.dll'): return False
    return True
a.binaries = [entry for entry in a.binaries if required(entry)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='FlipRing', debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False, icon=str(source / 'assets/app.ico'), version=str(source / 'version-info.txt'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='FlipRing')
