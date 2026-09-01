# To-Do Manager — 개발/유지보수 문서

팀 배포용 안내문은 빌드 결과물 안의 `먼저 읽어주세요.txt` 입니다.
이 문서는 소스를 고치거나 다시 빌드할 때 봅니다.

## 구조

프로세스가 **두 개**입니다. 창을 닫아도 알림이 계속 돌아야 하기 때문입니다.

```
main.py                 진입점. 인수 없으면 서비스, --ui 면 앱 창, --selftest 면 환경 점검
├─ app.py               서비스: HTTP API(8777) + 알림 스케줄러 + 트레이 + 알림 루프
│   ├─ store.py         저장 · 일정 인스턴스 계산 · 화면용 개요
│   ├─ recur.py         반복 규칙 엔진 + 한국 공휴일
│   ├─ toast.py         알림 카드 (Pillow + Windows 레이어드 윈도우)
│   ├─ tray.py          알림영역 아이콘 (pystray)
│   └─ autostart.py     자동 실행 등록 · 바탕화면 바로가기
└─ ui.py                앱 창 (pywebview / WebView2). 포커스·종료 신호용 8779 포트
    └─ web/             index.html · style.css · app.js

paths.py                파일 위치와 로깅을 한 곳에서 결정 (소스 실행 / 빌드본 공통)
build.py                배포 패키지 생성
```

- 두 프로세스는 **HTTP 로만** 통신합니다. 서비스 8777, 창 8779.
- 종료는 반드시 `app.shutdown()` 을 거칩니다 — 창 프로세스에 `/quit` 를 보낸 뒤 자신을 종료합니다.
  서비스만 죽이면 동작하지 않는 빈 창이 남습니다.
- 반대로 서비스가 사라지면 창이 45초 안에 스스로 닫힙니다 (`ui.watch_service`).

## 파일 위치

| | |
|---|---|
| 프로그램 자원 | `paths.RES_DIR` — 소스 폴더, 빌드본은 `sys._MEIPASS` |
| **사용자 데이터** | `%APPDATA%` 아래 `To-Do Manager\data.json` |

데이터를 프로그램 폴더 밖에 두는 이유: 배포본에 남의 일정이 섞이지 않고,
읽기 전용 공유 폴더에서 실행해도 저장이 되고, 새 버전으로 덮어써도 일정이 유지됩니다.
예전 위치(프로그램 폴더, 또는 예전 이름 `오늘` 폴더)에 데이터가 있으면
첫 실행 때 한 번 옮겨옵니다 (`paths.migrate_legacy`).

## 반복 규칙 모델

`주기 × 기준` 조합입니다. 예전 형식(`kind: "monthly_business_day"` 등)은
`recur.normalize()` 가 자동 변환하므로 기존 데이터가 그대로 동작합니다.

```python
period : "day" | "week" | "month" | "quarter"
basis  : "day" | "business_day" | "weekday" | "before_end" | "before_end_bd"

day     : business_only
week    : weekdays[], interval, anchor      # anchor 는 등록 시점에 고정 (격주가 흔들리지 않게)
month   : basis + (n | weekday | k), months[]
quarter : basis + (n | weekday | k)         # 달력 분기(1·4·7·10월 시작)
holiday_shift : "none" | "prev" | "next"    # 기본 prev
```

`n = -1` 은 "마지막", `k` 는 기간 말에서 역산하는 일수입니다.
공휴일은 `recur.DEFAULT_HOLIDAYS`(2026~2027)에 있고,
`data.json` 의 `holidays` 에 `"2028-01-01"` 형식으로 추가할 수 있습니다.

## 알림 카드

카드 한 장을 Pillow 로 그린 뒤 `UpdateLayeredWindow` 로 띄웁니다.
픽셀 단위 알파라서 모서리가 깨지지 않고 흐린 그림자가 나옵니다. 주의할 점:

- GDI 핸들은 64비트입니다. `restype` 를 지정하지 않으면 잘려서 실패합니다.
- `WS_EX_LAYERED` 는 `toplevel_hwnd()`(= `GetParent(winfo_id())`)에 걸어야 합니다.
  `winfo_id()` 는 Tk 내부 자식 창입니다.
- `_pump()` 는 어떤 예외에도 멈추지 않습니다. 여기서 죽으면 알림이 전부 사라집니다.
- Pillow·GDI 를 못 쓰면 tkinter 캔버스 방식으로 자동 폴백합니다.

## 색

팔레트 `#08202b · #0b2c36 · #4d7572 · #85bdb3 · #cfd6d5`.
`web/style.css` 맨 위 `:root` 만 고치면 전체가 따라옵니다.

작은 글씨(10.5~12px)에는 팔레트 원색을 그대로 쓰지 않습니다 — 대비가 부족해서입니다.
`--muted #365350`(6.4:1), `--faint #516764`(4.7:1) 처럼 같은 계열을 어둡게 한 값을 씁니다.
팔레트 원색은 띠·링·칩 같은 장식에 씁니다.

## 아이콘

`python gen_icon.py` 로 다시 만듭니다. `app.ico`(16·20·24·32·40·48·64·96·128·256)와
`web/icon.png`(256, 트레이용)가 나옵니다.

큰 그림 하나를 축소하면 16px 에서 뭉개지므로 **크기마다 새로 그립니다.**
각 크기를 8배로 그린 뒤 LANCZOS 로 줄이고, 24px 이하에서는 여백을 줄이고
선을 굵게 하고 뉴모피즘 그늘을 생략합니다 (작은 크기에서는 탁해집니다).
Pillow 의 ICO 저장은 `sizes` 만 주면 스스로 축소하므로,
따로 그린 프레임을 `append_images` 로 직접 넣어야 합니다.

## 시각 입력

시각은 전부 **5분 단위**입니다. `type="time"` 에 `step="300"`,
알림 분 입력에는 `class="min5"` 를 붙입니다.
값을 실제로 맞추는 것은 `web/app.js` 위쪽의 위임 `change` 리스너 한 곳입니다
(폼을 매번 새로 그리므로 개별 바인딩은 곧 빠집니다).
직접 입력은 브라우저 기본 동작이라 막지 않습니다 — 5분 배수가 아닌 값이
들어오면 가장 가까운 5분으로 맞춰줍니다.

## 문제가 생겼을 때

빌드본은 `--windowed` 라서 `sys.stderr` 가 `None` 입니다.
화면에 아무것도 찍히지 않으므로 모든 예외를 파일로 남깁니다.

| | |
|---|---|
| `%APPDATA%` 의 `To-Do Manager\app.log` | 시작 단계 추적 + 모든 예외 (128KB 넘으면 `.1` 로 한 번 보관) |
| `To-Do Manager.exe --selftest` | 임포트·WebView2 초기화 점검 결과를 `selftest.txt` 로 남기고 열어줍니다 |

**`except Exception: pass` 를 남기지 마세요.** 예외를 삼키면 진단이 불가능해집니다.
실제로 `import paths` 누락이 이 때문에 오래 안 잡혔고, 창이 조용히 Edge 폴백으로
떨어지는 증상만 보였습니다.

## 빌드할 때 주의할 것

이 프로젝트에서 실제로 배포를 막았던 문제들입니다.

1. **Anaconda 는 확장 모듈이 쓰는 DLL 을 `Library` 아래 `bin` 에 둡니다.**
   PyInstaller 는 거기를 보지 않습니다. `build.extra_binaries()` 가 `.pyd` 의 PE
   임포트 테이블을 읽어 자동으로 담습니다. 없으면 실행 즉시
   `DLL load failed while importing _ctypes / _tkinter` 로 죽습니다.
2. **`_ssl` 을 스캔 목록에서 빼면 안 됩니다.** pywebview 의 `http.py` 가
   최상단에서 `import ssl` 을 하고, 실패하면 창이 통째로 Edge 폴백으로 떨어집니다.
   그래서 `libcrypto` · `libssl` 은 용량을 아끼려고 지우면 안 됩니다.
3. **소스 줄바꿈은 LF 로 유지하세요.** CRLF 가 섞이면 스크립트로 패치할 때
   조용히 실패합니다. 고친 뒤에는 정적 검사를 돌립니다.

```
python -m pyflakes *.py
```

## 다시 빌드하기

빌드는 **깨끗한 가상환경**에서 합니다. Anaconda 본체에서 빌드하면 환경 전체가
끌려들어와 295MB 가 됩니다.

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install pyinstaller pywebview pythonnet pystray pillow pyflakes
.venv\Scripts\python.exe build.py
```

`release/To-Do Manager.zip` (약 17MB) 과 `release/To-Do Manager/` 가 생깁니다.
zip 하나만 공유 폴더에 올리면 됩니다.

## 소스에서 바로 실행 (개발용)

```
pythonw main.py          # 또는 "개발용 실행.vbs" 두 번 클릭
```
