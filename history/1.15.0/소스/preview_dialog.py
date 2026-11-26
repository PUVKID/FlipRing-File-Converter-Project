"""미리보기 작업과 임시 파일의 수명을 함께 소유하는 작은 창."""
import threading
from pathlib import Path
from PySide6.QtCore import QThread, Signal, QTimer, Qt, QSize
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QProgressBar
from conversion_preview import PreviewSession
from preview_panel import PreviewPanel
from recovery import explain_failure
from fixed_viewport import fit_window
from ui_motion import install_surface_motions,set_reduced_motion

class _PreviewJob(QThread):
    result=Signal(object,str)
    def __init__(self,session,parent):
        super().__init__(parent);self.session=session;self.cancel=threading.Event()
    def run(self):
        try:self.result.emit(self.session.run(self.cancel),'')
        except Exception as error:self.result.emit(None,str(error))

class ConversionPreviewDialog(QDialog):
    recovery_requested=Signal(str,str)
    def __init__(self,owner,source,destination):
        super().__init__(owner);self.language=owner.language;self.session=None;self.job=None;self._closing=False;self._outcome=(None,'');self.timed_out=False
        en=self.language=='en';self.setWindowTitle('Conversion preview' if en else '변환 미리보기');fit_window(self,QSize(880,650))
        body=QVBoxLayout(self);body.setContentsMargins(28,26,28,24);body.setSpacing(16)
        title=QLabel((destination.upper()+' preview') if en else (destination.upper()+' 결과 미리보기'));title.setObjectName('quietDialogTitle');body.addWidget(title)
        self.note=QLabel('A temporary copy is converted. Your original and existing outputs remain unchanged.' if en else '임시 사본으로 변환합니다. 원본과 기존 결과는 그대로 남습니다.');self.note.setWordWrap(True);self.note.setObjectName('muted');body.addWidget(self.note)
        self.preview=PreviewPanel();self.preview.set_language(self.language);body.addWidget(self.preview,1)
        # 임시 결과는 창과 함께 정리된다. 탐색기에서 열어 유지되는 파일처럼 보이지 않게 한다.
        for _,_,_,button in self.preview.panels:button.hide()
        self.summary=QLabel();self.summary.setWordWrap(True);body.addWidget(self.summary)
        self.warnings=QLabel();self.warnings.setWordWrap(True);self.warnings.setObjectName('muted');body.addWidget(self.warnings)
        self.progress=QProgressBar();self.progress.setRange(0,0);self.progress.setTextVisible(False);body.addWidget(self.progress)
        row=QHBoxLayout();self.recovery_button=QPushButton();self.recovery_button.hide();self.recovery_button.clicked.connect(self._recover);row.addWidget(self.recovery_button);row.addStretch();self.close_button=QPushButton('Cancel' if en else '취소');self.close_button.clicked.connect(self.reject);row.addWidget(self.close_button);body.addLayout(row)
        self.source=str(source)
        self.timeout=QTimer(self);self.timeout.setSingleShot(True);self.timeout.timeout.connect(self._timeout)
        try:
            self.session=PreviewSession(source,destination,language=self.language);self.session.__enter__()
            self.preview.set_paths(source,'');self.summary.setText('Creating the actual result…' if en else '실제 결과를 만들고 있습니다…')
            self.job=_PreviewJob(self.session,self);self.job.result.connect(self._receive);self.job.finished.connect(self._finished);self.job.start();self.timeout.start(60000)
        except Exception as error:
            self._outcome=(None,str(error));self._finished()
        install_surface_motions(self);set_reduced_motion(self,owner.reduced_motion_toggle.isChecked())

    def is_busy(self):return bool(self.job and self.job.isRunning())
    def _receive(self,result,error):self._outcome=(result,error)
    def _timeout(self):
        if self.is_busy():self.timed_out=True;self.job.cancel.set();self.summary.setText('Stopping the preview…' if self.language=='en' else '미리보기를 중지하고 있습니다…')
    def _finished(self):
        self.timeout.stop();self.progress.hide();en=self.language=='en';self.close_button.setText('Close' if en else '닫기');result,error=self._outcome
        if result:
            shown=Path(result.output)
            if shown.is_dir():
                candidates=sorted(x for x in shown.iterdir() if x.suffix.lower() in ('.png','.jpg','.jpeg','.pdf'))
                if candidates:shown=candidates[0]
            self.preview.set_paths(result.source,str(shown))
            for _,_,_,button in self.preview.panels:button.hide()
            self.summary.setText((f'Original {result.source_bytes:,} bytes  →  Actual result {result.output_bytes:,} bytes' if en else f'원본 {result.source_bytes:,}바이트  →  실제 결과 {result.output_bytes:,}바이트'))
            self.warnings.setText('\n'.join(result.warnings))
        elif not self._closing:
            if self.timed_out:self.summary.setText('Preview exceeded 60 seconds and was cancelled. The original is unchanged.' if en else '미리보기 60초를 초과해 취소했습니다. 원본은 그대로입니다.')
            elif self.job and self.job.cancel.is_set():self.summary.setText('Preview cancelled.' if en else '미리보기를 취소했습니다.')
            else:
                issue=explain_failure(error,self.language);self.summary.setText(issue.title);self.warnings.setText(issue.body+'\n'+error[:450]);self.recovery_button.setText(issue.label);self.recovery_button.show()
        if self._closing:self._dispose();super().reject()
    def _dispose(self):
        if self.session:self.session.__exit__(None,None,None);self.session=None
    def _recover(self):
        if self.is_busy():return
        error=self._outcome[1];self.reject();self.recovery_requested.emit(error,self.source)
    def reject(self):
        if self.is_busy():self._closing=True;self.job.cancel.set();self.close_button.setEnabled(False);self.summary.setText('Cancelling…' if self.language=='en' else '취소하고 있습니다…');return
        self._dispose();super().reject()
    def closeEvent(self,event):
        if self.is_busy():self.reject();event.ignore()
        else:self._dispose();event.accept()
