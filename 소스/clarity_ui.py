"""기존 기능과 값을 유지하고 기본 화면의 정보 밀도만 낮춘다."""
from pathlib import Path
from PySide6.QtCore import QObject,Qt,QTimer
from PySide6.QtWidgets import (QWidget,QLabel,QPushButton,QVBoxLayout,QHBoxLayout,QMenu,QPlainTextEdit,QFormLayout,QSizePolicy)
from recovery import explain_failure
from studio_ui import NavButton

CLARITY_STYLE='''
QMainWindow QLabel#pageTitle {font-size:24px;padding:0;border:0;}
QLabel#sectionHeading {border:0;padding:3px 0;color:#707070;}
QLabel#quietDialogTitle {font-size:21px;}
QLabel#quietSummary {color:#666666;font-size:12px;}
QWidget#quietRecovery {background:#f2f2f2;border-radius:10px;}
QMainWindow QPushButton[quiet="true"] {background:transparent;border:0;color:#666666;padding:7px 9px;}
QMainWindow QPushButton[quiet="true"]:hover {background:#eeeeee;color:#242424;}
QMainWindow QFrame#dropCard[compact="true"] {background:transparent;border:0;}
QFrame#sidebar {border:0;background:#f1f1f1;}
QLabel#brand {font-size:21px;}
QFrame#studioCard,QFrame#dropCard {border:1px solid #ebebeb;border-radius:12px;}
QLabel#cardTitle {font-size:14px;}
QLabel#dropTitle {font-size:19px;}
QListWidget::item {padding:12px 10px;border-bottom:0;}
QListWidget::item:selected {background:#ededed;border-radius:6px;}
QTabBar::tab {padding:10px 14px;}
QFrame#pickerHeader {border:0;}
QLabel#pickerTitle {font-size:19px;}
'''

def quiet_button(button):button.setProperty('quiet',True);button.setAutoDefault(False)

class ClarityController(QObject):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.error='';self.error_source='';self.issue=None
        owner.sidebar.setFixedWidth(178);owner.page_description.hide();owner.key_badge.hide()
        for label in owner.sidebar.findChildren(QLabel):
            if label.objectName()=='sideCaption':label.hide()
        for label in owner.findChildren(QLabel):
            if label.objectName()=='sectionHeading':label.hide()
        side=owner.sidebar.layout();self.more=NavButton('tools');self.more.clicked.connect(self.open_more)
        side.insertWidget(side.indexOf(owner.nav_buttons[5])+1,self.more)
        for index in (1,3,6,7):owner.nav_buttons[index].hide()
        theme_label=next((w for w,key,_ in owner._translated_widgets if key=='theme'),None)
        settings=owner.quick_settings.layout()
        if theme_label:settings.insertWidget(2,theme_label)
        settings.insertWidget(3,owner.theme_combo)
        owner.subtitle.hide()
        for label in owner.quick_settings.findChildren(QLabel):
            if label.objectName()=='cardTitle':label.hide()
        owner.queue_list.setMinimumHeight(110);owner.queue_list.setMaximumHeight(150)
        quiet_button(owner.preset_toggle);owner.preset_toggle.setMaximumWidth(200)
        body=owner.workbench.layout();body.setSpacing(16);body.setAlignment(Qt.AlignTop)
        self.preview_button=QPushButton();quiet_button(self.preview_button);self.preview_button.clicked.connect(self.open_preview)
        body.itemAt(3).layout().insertWidget(2,self.preview_button)
        execution=body.itemAt(3).layout();execution.addStretch(1)
        execution.itemAt(0).widget().setMaximumWidth(82)
        owner.output_combo.setMinimumWidth(132);owner.output_combo.setMaximumWidth(180)
        for button in (self.preview_button,owner.run_button):button.setMaximumWidth(200)
        owner.drop_card.title.setAlignment(Qt.AlignLeft);owner.drop_card.caption.setAlignment(Qt.AlignLeft)
        owner.choose_button.setMaximumWidth(210);owner.folder_button.setMaximumWidth(170);quiet_button(owner.folder_button)
        for i in range(owner.drop_card.body.count()):
            row=owner.drop_card.body.itemAt(i).layout()
            if row and row.indexOf(owner.choose_button)>=0:
                row.setContentsMargins(0,0,0,0);row.addStretch(1)
        owner.preflight_label.hide();owner.preview_panel.hide()
        self.result_toggle=QPushButton();self.result_toggle.setCheckable(True);quiet_button(self.result_toggle);self.result_toggle.toggled.connect(owner.preview_panel.setVisible);body.addWidget(self.result_toggle)
        self.recovery=QWidget();self.recovery.setObjectName('quietRecovery');r=QVBoxLayout(self.recovery);r.setContentsMargins(16,14,16,14);r.setSpacing(8)
        self.recovery.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Maximum)
        self.title=QLabel();self.title.setWordWrap(True);self.message=QLabel();self.message.setWordWrap(True);self.message.setObjectName('quietSummary');r.addWidget(self.title);r.addWidget(self.message)
        actions=QHBoxLayout();self.fix=QPushButton();self.fix.clicked.connect(self.resolve);actions.addWidget(self.fix);self.details_toggle=QPushButton();self.details_toggle.setCheckable(True);quiet_button(self.details_toggle);actions.addWidget(self.details_toggle);actions.addStretch();r.addLayout(actions)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setFixedHeight(90);r.addWidget(self.details);self.details.hide();self.details_toggle.toggled.connect(self.details.setVisible)
        body.insertWidget(4,self.recovery);self.recovery.hide()
        owner.output_combo.currentIndexChanged.connect(self.refresh)
        owner.queue_list.currentRowChanged.connect(self.selection_changed)
        owner.tabs.currentChanged.connect(self.navigation_changed)
        # 2차 작업 도구의 선택 옵션을 기존 고급 영역으로 옮긴다. 값/시그널은 그대로다.
        panel=owner.workspace_panel;panel.visual.hide();form=panel.format.parentWidget().layout()
        original=next((layout for layout in (panel.format.parentWidget().layout().itemAt(i).layout() for i in range(panel.format.parentWidget().layout().count())) if isinstance(layout,QFormLayout)),None)
        if original:
            extra=QFormLayout();panel.advanced_body.layout().insertLayout(0,extra)
            for widget in (panel.max_bytes,panel.dpi,panel.quality):
                row=original.takeRow(widget)
                if row.labelItem and row.fieldItem:extra.addRow(row.labelItem.widget(),row.fieldItem.widget())
        for widget in (panel.quality_enabled,panel.a4,panel.name_template,panel.names_preview):panel.advanced_body.layout().insertWidget(0,widget)
        for widget,key in panel._labels:
            if key=='ws_name':panel.advanced_body.layout().insertWidget(0,widget)
        for name in ('note','pdf_note'):
            owner.pdf_panel._advanced_form.addWidget(getattr(owner.pdf_panel,name))
        quiet_button(owner.pdf_panel.save_preset_button)
        self.set_language()

    def set_language(self):
        en=self.owner.language=='en';self.more.setText('More tools' if en else '더 보기');self.preview_button.setText('Preview result' if en else '결과 미리보기');self.result_toggle.setText('Original · saved result' if en else '원본 · 저장된 결과 보기');self.details_toggle.setText('Technical details' if en else '상세 내용');self.owner.drop_card.title.setText('Convert files' if en else '파일 변환');self.owner.drop_card.caption.setText('Drop files here, or choose them below.' if en else '파일을 여기에 놓거나 아래에서 선택하세요.');self.navigation_changed(self.owner.tabs.currentIndex());self.refresh()

    def navigation_changed(self,index):self.more.setChecked(index in (1,3,6,7))
    def open_more(self):
        owner=self.owner;menu=QMenu(owner)
        for index,key in ((7,'quick_actions'),(6,'ws_title'),(1,'studio_helpers'),(3,'about')):
            menu.addAction(owner.text(key),lambda checked=False,target=index:owner.tabs.setCurrentIndex(target))
        menu.exec(self.more.mapToGlobal(self.more.rect().bottomLeft()))
    def open_preview(self):
        owner=self.owner
        if owner.work_busy() or not owner.paths or not owner.output_combo.currentData():return
        index=owner.queue_list.currentRow();source=owner.jobs[index]['source'] if 0<=index<len(owner.jobs) else owner.paths[0]
        from preview_dialog import ConversionPreviewDialog
        dialog=ConversionPreviewDialog(owner,source,owner.output_combo.currentData());owner.conversion_preview=dialog;dialog.recovery_requested.connect(self.preview_recovery)
        try:dialog.exec()
        finally:owner.conversion_preview=None;dialog.deleteLater()
    def preview_recovery(self,error,source):
        self.show_error(error,source)
        QTimer.singleShot(0,self.open_preview if self.issue.action=='retry' else self.resolve)
    def selection_changed(self,*unused):
        i=self.owner.queue_list.currentRow()
        if 0<=i<len(self.owner.jobs):
            row=self.owner.jobs[i];self.show_error(row.get('error',''),row['source'])
        else:self.show_error('','')
        self.refresh()
    def refresh(self,*unused):
        owner=self.owner;self.preview_button.setEnabled(not owner.work_busy() and bool(owner.paths) and bool(owner.output_combo.currentData()))
        owner.queue_list.setFixedHeight(min(180,max(68,len(owner.jobs)*46+16)))
        owner.selection_label.setVisible(not owner.paths)
        owner.drop_card.setProperty('compact',bool(owner.paths));owner.drop_card.setMaximumHeight(80 if owner.paths else 210)
        owner.drop_card.style().unpolish(owner.drop_card);owner.drop_card.style().polish(owner.drop_card)
        i=owner.queue_list.currentRow();has_output=0<=i<len(owner.jobs) and bool(owner.jobs[i].get('output'));self.result_toggle.setVisible(has_output)
        if not has_output:self.result_toggle.setChecked(False);owner.preview_panel.hide()
        if self.error:self.show_error(self.error,self.error_source)
    def show_error(self,error,source=''):
        self.error=str(error);self.error_source=source;self.recovery.setVisible(bool(error))
        if not error:return
        self.issue=explain_failure(error,self.owner.language);self.title.setText(self.issue.title);self.message.setText(self.issue.body);self.fix.setText(self.issue.label);self.details.setPlainText(str(error));self.fix.setEnabled(not self.owner.work_busy())
    def resolve(self):
        owner=self.owner
        if owner.work_busy() or self.issue is None:return
        action=self.issue.action
        if action=='install':
            if self.issue.tool in __import__('engine').TOOLS:owner.installer.start(self.issue.tool)
        elif action in ('select','unlock'):owner.pick_files()
        elif action=='helpers':owner.tabs.setCurrentIndex(1)
        elif action=='location':
            path=Path(self.error_source)
            if path.exists():owner.reveal_preview(str(path))
            else:owner.pick_files()
        elif action=='format':owner.output_combo.setFocus();owner.output_combo.showPopup()
        else:
            if any(row['state']=='failed' for row in owner.jobs):owner.retry_failed()
            else:owner.tabs.setCurrentIndex(4)
