# -*- coding: utf-8 -*-
"""To-Do Manager - 진입점.

  인수 없음     백그라운드 서비스
  --ui          앱 창
  --selftest    환경 점검 결과를 파일로 남긴다 (문제 생겼을 때 확인용)

실행 파일 하나로 모든 역할을 담당한다.
"""
import sys


def selftest():
    """빌드본에서 무엇이 안 되는지 파일로 남긴다. 콘솔이 없어 화면에 못 찍기 때문."""
    import os
    import platform
    import traceback

    import paths
    paths.ensure_data_dir()
    out = os.path.join(paths.DATA_DIR, "selftest.txt")
    lines = [
        f"python      {sys.version}",
        f"platform    {platform.platform()}",
        f"frozen      {paths.FROZEN}",
        f"executable  {sys.executable}",
        f"RES_DIR     {paths.RES_DIR}",
        f"WEB_DIR     {paths.WEB_DIR}  (있음={os.path.isdir(paths.WEB_DIR)})",
        f"DATA_FILE   {paths.DATA_FILE}",
        "",
        "[import 점검]",
    ]
    for mod in ("tkinter", "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFilter",
                "pystray", "pystray._win32", "clr", "clr_loader",
                "bottle", "proxy_tools", "webview", "webview.guilib",
                "webview.platforms.winforms", "webview.platforms.edgechromium"):
        try:
            __import__(mod)
            lines.append(f"  OK    {mod}")
        except Exception as e:
            lines.append(f"  실패  {mod}: {type(e).__name__}: {e}")

    lines += ["", "[webview 창 생성 점검]"]
    try:
        import webview
        lines.append(f"  webview 버전 {getattr(webview, '__version__', '?')}")
        from webview.guilib import initialize
        gui = initialize()
        lines.append(f"  guilib initialize -> {gui}")
    except Exception:
        lines.append("  " + traceback.format_exc().replace("\n", "\n  "))

    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    try:                                    # 결과를 바로 볼 수 있게 열어준다
        os.startfile(out)
    except Exception:
        pass


def run():
    if "--selftest" in sys.argv:
        selftest()
    elif "--ui" in sys.argv:
        import ui
        ui.main()
    else:
        import app
        app.main()


if __name__ == "__main__":
    run()
