"""문서가 달라도 동시 호출할 수 없는 PDFium의 프로세스 내 공용 잠금."""
from threading import RLock

PDFIUM_LOCK = RLock()
