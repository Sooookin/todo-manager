# To-Do Manager

루틴 업무 특화형 일정관리 / 백그라운드 알림 앱. Windows.

- 반복 규칙: 매 영업일 · 매주 · 매월 · 분기.
  `2번째 영업일`, `마지막 목요일`, `말일 3영업일 전` 같은 기준을 조합한다.
  주말·공휴일에 걸리면 앞 영업일로 조정.
- 마감이 있는 일 / 기한 없는 메모.
- 창을 닫아도 뒤에서 돌며 마감 전에 알림 카드를 띄운다.

## 실행

```
pythonw main.py
```

Python 3.11+ / `pip install pywebview pythonnet pystray pillow`

## 빌드

깨끗한 가상환경에서 해야 한다. Anaconda 본체에서 빌드하면 295MB 가 된다.

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install pyinstaller pywebview pythonnet pystray pillow pefile
.venv\Scripts\python.exe build.py
```

`release/To-Do Manager.zip` (약 17MB). 아이콘은 `python gen_icon.py`.

세 가지만 주의한다.

1. Anaconda 는 확장 모듈의 DLL 을 `Library\bin` 에 두고 PyInstaller 는 거기를 안 본다.
   `build.extra_binaries()` 가 `.pyd` 임포트 테이블을 읽어 담는다.
2. `_ssl` 을 빼면 안 된다. pywebview 가 `import ssl` 을 하고, 실패하면 창이
   통째로 Edge 폴백으로 떨어진다. `libcrypto`·`libssl` 도 지우면 안 된다.
3. 소스 줄바꿈은 LF. CRLF 가 섞이면 스크립트 패치가 조용히 실패한다.

## 구조

```
main.py     진입점 (없으면 서비스 / --ui 창 / --selftest 점검)
app.py      서비스: HTTP 8777 + 알림 + 트레이
ui.py       창: pywebview(WebView2), 포커스·종료용 8779
recur.py    반복 규칙 + 한국 공휴일
store.py    저장 · 화면용 개요
toast.py    알림 카드 (Pillow + UpdateLayeredWindow)
web/        화면
```

일정은 `%APPDATA%\To-Do Manager\data.json` 에 저장된다. 저장소·배포본에 들어가지 않는다.
로그는 같은 폴더의 `app.log` (빌드본은 콘솔이 없다).
