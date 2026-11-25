"""허용된 외부 도구만 셸 없이 비동기로 설치한다."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import winreg
from PySide6.QtCore import QObject, QProcess, QTimer, Signal
import engine


def install_arguments(name):
    if name not in engine.TOOLS:
        raise ValueError('허용되지 않은 설치 도구입니다.')
    return ['install', '--id', engine.TOOLS[name][1], '--exact', '--source', 'winget',
            '--accept-package-agreements', '--accept-source-agreements', '--disable-interactivity']


def refresh_process_path():
    """설치 프로그램이 갱신한 사용자·시스템 PATH를 현재 프로세스에도 반영한다."""
    paths = [os.environ.get('PATH', '')]
    for hive, key in ((winreg.HKEY_LOCAL_MACHINE,
                      r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'),
                     (winreg.HKEY_CURRENT_USER, 'Environment')):
        try:
            with winreg.OpenKey(hive, key) as handle:
                value, _ = winreg.QueryValueEx(handle, 'Path')
                paths.append(os.path.expandvars(str(value)))
        except OSError:
            continue
    os.environ['PATH'] = os.pathsep.join(dict.fromkeys(
        item for value in paths for item in value.split(os.pathsep) if item))


class ToolInstaller(QObject):
    state_changed = Signal(str, str, str)
    finished = Signal(str, str, int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.name = ''
        self.state = 'ready'
        self.detail = ''
        self.cancel_requested = False
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self.cancel)

    def is_busy(self):
        return self.process is not None

    def start(self, name):
        args = install_arguments(name)
        if self.is_busy():
            return False
        refresh_process_path()
        self.name, self.cancel_requested, self.detail = name, False, ''
        executable = shutil.which('winget.exe')
        if not executable:
            self.state = 'missing'
            self.state_changed.emit(name, 'missing', '')
            self.finished.emit(name, 'missing', -1, '')
            return False
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.errorOccurred.connect(self._error)
        self.process.finished.connect(self._finished)
        self.state = 'installing'
        self.state_changed.emit(name, self.state, '')
        self._timeout.start(30 * 60 * 1000)
        self.process.start(executable, args)
        return True

    def _read(self):
        if self.process is None:
            return
        chunk = bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
        # 외부 출력은 마지막 8Ki 문자만 보관하고 실제 백분율을 만들어 내지 않는다.
        self.detail = (self.detail + chunk)[-8192:]
        self.state_changed.emit(self.name, self.state, self.detail)

    def _error(self, error):
        if self.process is not None and error == QProcess.FailedToStart:
            self.detail = self.process.errorString()
            self._complete('failed', -1)

    def _finished(self, code, status):
        self._read()
        self._complete('cancelled' if self.cancel_requested else
                       'complete' if status == QProcess.NormalExit and code == 0 else 'failed', code)

    def _complete(self, state, code):
        if self.process is not None:
            self.process.deleteLater()
        self.process = None
        self._timeout.stop()
        refresh_process_path()
        self.state = state
        self.state_changed.emit(self.name, state, self.detail)
        self.finished.emit(self.name, state, code, self.detail)

    def cancel(self):
        if self.process is None:
            return
        self.cancel_requested = True
        self.state = 'cancelling'
        self.state_changed.emit(self.name, self.state, self.detail)
        # winget 외에 위임된 Windows Installer/UAC 작업은 강제 종료하지 않는다.
        # 설치 관리 프로세스를 멈춘 뒤 재탐지하여 실제 설치 여부를 표시한다.
        self.process.kill()
