# -*- coding: utf-8 -*-
"""배포용 패키지를 만든다.

    python build.py

결과: release/To-Do Manager.zip  (공유 폴더에 올릴 파일 하나)
      release/To-Do Manager/    (압축 전 폴더)

패키지 안에는 파이썬도 라이브러리도 없어도 되는 실행 파일 하나와
아주 짧은 안내문만 들어간다. 내 일정(data.json)은 %APPDATA% 에 있어 절대 포함되지 않는다.
"""
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
RELEASE = os.path.join(HERE, "release")
OUT_NAME = "To-Do Manager"

READ_ME = r"""To-Do Manager  -  일정 · 루틴 관리
==========================================

■ 시작하기
  1. 이 폴더를 내 PC로 복사하세요. (공유 폴더에서 바로 실행하면 느립니다)
  2. "To-Do Manager.exe" 를 두 번 클릭하면 끝입니다. 설치할 것은 없습니다.
     * 처음 실행할 때 Windows 보안 경고가 나오면
       [추가 정보] → [실행] 을 누르세요. (사내 배포본이라 서명이 없습니다)
  3. 창 오른쪽 위 톱니바퀴에서
       - "바탕화면에 바로가기 만들기"  → 다음부터 아이콘으로 실행
       - "Windows 시작할 때 자동 실행" → 켜두면 항상 알림을 받습니다

■ 기억할 것 하나
  창의 X 는 창만 닫습니다. 프로그램은 뒤에서 계속 돌며 알림을 띄웁니다.
  다시 열려면 작업표시줄 오른쪽 알림영역(^) 의 체크 아이콘을 클릭하세요.
  완전히 끄려면 그 아이콘 우클릭 -> "완전히 종료".

■ 항목 추가   [+ 새 항목]
  · 반복되는 일
      매 영업일 / 매주 / 매월 / 분기 를 고르고 기준을 정합니다.
      예) 매월 2번째 영업일 · 매월 마지막 목요일 · 말일 3영업일 전
          3·6·9·12월 2번째 영업일 · 매 분기 말 3영업일 전
      고르는 즉시 "다음 실행 날짜" 5개를 미리 보여줍니다.
      주말·공휴일에 걸리면 앞 영업일로 자동 조정됩니다.
  · 마감이 있는 일   날짜와 시각을 지정합니다. (오늘 / 내일 / +7일 버튼)
      시각은 5분 단위이고, 0930 처럼 키보드로 바로 칠 수 있습니다.
  · 기한 없는 메모   떠오른 것만 적어둡니다.

■ 화면
  왼쪽             밀린 것 + 오늘 할 일을 시간순으로. 동그라미를 눌러 완료.
  오른쪽 위        다가오는 7일의 마감
  오른쪽 가운데    메모
  오른쪽 아래      반복 업무 (제목줄을 누르면 펼쳐집니다)
  항목 왼쪽 색 띠  진한색 = 마감,  중간색 = 반복,  연한색 = 메모

■ 수정 / 삭제
  항목 이름이나 연필 아이콘을 누르면 수정 창이 열립니다.
  반복 일정은 "이번 회차 건너뛰기" 로 한 번만 넘길 수 있습니다.
  왼쪽 아래 "전체 항목 관리" 에서 등록한 모든 항목을 볼 수 있습니다.

■ 알림
  마감 30분 전(설정에서 변경)에 화면 우측 하단에 카드가 떠오릅니다.
  카드의 "완료" 를 누르면 그 자리에서 처리됩니다.
  아침 08:30 에 오늘 할 일 요약이 한 번 뜹니다.

■ 내 일정이 저장되는 곳
  %APPDATA%\To-Do Manager\data.json      (이 파일만 백업하면 됩니다)
  새 버전으로 폴더를 덮어써도 일정은 그대로 유지됩니다.
"""


def extra_binaries():
    """인터프리터가 표준 위치에 두지 않는 DLL 을 자동으로 찾아 담는다.

    Anaconda 는 확장 모듈이 요구하는 DLL 을 Library\bin 에 둔다.
    PyInstaller 는 그 경로를 스캔하지 않으므로, 넣어주지 않으면 빌드본이
    실행 즉시 "DLL load failed while importing _ctypes / _tkinter" 로 죽는다.
    이름을 박아두면 파이썬 버전이 바뀔 때 또 깨지므로, .pyd 의 임포트 테이블을
    직접 읽어서 필요한 것만 담는다.
    """
    libbin = os.path.join(sys.base_prefix, "Library", "bin")
    dll_dir = os.path.join(sys.base_prefix, "DLLs")
    if not os.path.isdir(libbin):
        return []                       # python.org 배포판 등은 이미 정상
    try:
        import pefile
    except ImportError:
        return []

    need, out = [], []
    for mod in ("_ctypes", "_tkinter", "_socket", "select", "_queue", "_ssl"):
        p = os.path.join(dll_dir, mod + ".pyd")
        if not os.path.exists(p):
            continue
        pe = pefile.PE(p, fast_load=True)
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
            name = entry.dll.decode()
            if name.lower() not in need:
                need.append(name.lower())
        pe.close()

    # OS·VC 런타임이 제공하는 것은 담지 않는다 (시스템 것과 충돌할 수 있다)
    skip = ("api-ms-win", "vcruntime", "msvcp", "ucrtbase", "python3")
    for name in need:
        if name.startswith(skip):
            continue
        cand = os.path.join(libbin, name)
        if os.path.exists(cand):
            out += ["--add-binary", f"{cand}{os.pathsep}."]
            print(f"  + 누락 DLL 포함: {name}")
    return out


# 쓰지 않는데 크게 들어오는 것들. PIL 은 플러그인 임포트를 try/except 로 감싸므로
# 코덱 .pyd 를 지워도 안전하다 (해당 포맷만 못 읽게 된다).
PRUNE = [
    "_internal/PIL/_avif.cp*.pyd",        # AVIF 코덱 7.5MB - 안 씀
    "_internal/PIL/_webp.cp*.pyd",        # WebP  0.4MB - 안 씀
    "_internal/PIL/_imagingcms.cp*.pyd",  # 컬러 매니지먼트 0.3MB - 안 씀
    "_internal/_tcl_data/tzdata",         # Tcl 시간대 DB 2.0MB - 안 씀
    "_internal/_tcl_data/msgs",           # Tcl 번역 메시지 - 안 씀
    # 주의: libcrypto/libssl 은 지우면 안 된다.
    #       pywebview 의 http.py 가 import ssl 을 하고, 없으면 네이티브 창이
    #       통째로 실패해서 Edge 폴백으로 떨어진다.
]


def prune(root):
    """빌드 결과에서 쓰지 않는 큰 파일을 지운다."""
    import glob
    freed = 0
    for pat in PRUNE:
        for p in glob.glob(os.path.join(root, pat.replace("/", os.sep))):
            if os.path.isdir(p):
                for r, _, fs in os.walk(p):
                    freed += sum(os.path.getsize(os.path.join(r, f)) for f in fs)
                shutil.rmtree(p, ignore_errors=True)
            elif os.path.exists(p):
                freed += os.path.getsize(p)
                os.remove(p)
    print(f"  - 불필요 파일 정리: {freed / 1024 / 1024:.1f} MB")


def run(cmd):
    print(">", " ".join(cmd))
    if subprocess.call(cmd, cwd=HERE) != 0:
        sys.exit("빌드 실패")


def main():
    for d in ("build", "dist", RELEASE):
        path = os.path.join(HERE, d)
        shutil.rmtree(path, ignore_errors=True)
        if os.path.exists(path):
            # 배포본이 실행 중이면 exe 가 잠겨 있어 지워지지 않는다.
            # 예전에 여기서 조용히 넘어가 copytree 가 엉뚱한 곳에서 터졌다.
            sys.exit(f"'{path}' 를 지울 수 없습니다." \
                     f"\n실행 중인 To-Do Manager 를 먼저 완전히 종료하세요." \
                     '\n  taskkill /F /IM \"To-Do Manager.exe\"')
    for f in (OUT_NAME + ".spec",):
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            os.remove(p)

    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--windowed",                       # 콘솔 창 없음
            "--noupx",
            "--name", OUT_NAME,
            "--icon", os.path.join(HERE, "app.ico"),
            "--add-data", f"web{os.pathsep}web",
            "--add-data", f"app.ico{os.pathsep}.",
            ]
    # 지연 임포트되는 것들
    for m in ("PIL.ImageTk", "pystray._win32", "clr",
              "webview.platforms.winforms", "webview.platforms.edgechromium"):
        args += ["--hidden-import", m]
    # pywebview 는 WebView2 DLL 을 자기 패키지 안에 들고 있다
    args += ["--collect-data", "webview", "--collect-binaries", "webview",
             "--collect-data", "clr_loader", "--collect-binaries", "clr_loader"]
    # 안 쓰는 무거운 것들 (깨끗한 venv 로 빌드해도 한 번 더 막아둔다)
    for m in ("numpy", "pandas", "scipy", "matplotlib", "IPython", "jupyter",
              "notebook", "nbformat", "sklearn", "sympy", "numba", "llvmlite",
              "PyQt5", "PyQt6", "PySide2", "PySide6", "qtpy", "cv2", "zmq",
              "tornado", "dask", "bokeh", "pytest", "setuptools", "pip"):
        args += ["--exclude-module", m]
    args += extra_binaries()
    args.append("main.py")
    run(args)

    prune(os.path.join(HERE, "dist", OUT_NAME))

    src = os.path.join(HERE, "dist", OUT_NAME)
    dst = os.path.join(RELEASE, OUT_NAME)
    os.makedirs(RELEASE, exist_ok=True)
    shutil.copytree(src, dst)

    with open(os.path.join(dst, "먼저 읽어주세요.txt"), "w", encoding="utf-8-sig") as f:
        f.write(READ_ME)

    zip_path = os.path.join(RELEASE, OUT_NAME + ".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(dst):
            for name in files:
                full = os.path.join(root, name)
                z.write(full, os.path.relpath(full, RELEASE))

    for d in ("build", "dist"):
        shutil.rmtree(os.path.join(HERE, d), ignore_errors=True)
    spec = os.path.join(HERE, OUT_NAME + ".spec")
    if os.path.exists(spec):
        os.remove(spec)

    size = os.path.getsize(zip_path) / 1024 / 1024
    print(f"\n완료: {zip_path}  ({size:.1f} MB)")
    print(f"      {dst}")


if __name__ == "__main__":
    main()
