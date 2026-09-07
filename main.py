# -*- coding: utf-8 -*-
"""To-Do Manager - 진입점.

  인수 없음     백그라운드 서비스
  --ui          앱 창
  --selftest    환경 점검 결과를 파일로 남긴다 (문제 생겼을 때 확인용)

실행 파일 하나로 모든 역할을 담당한다.
"""
import sys


def stub_ssl():
    """ssl 자리에 껍데기를 끼운다 (배포 용량 5.8MB 절약).

    pywebview 의 http.py 가 최상단에서 import ssl 을 한다. 그 파일의 SSL 서버는
    우리가 쓰지 않는다 - 우리 서비스(127.0.0.1:8777)의 http URL 을 그대로 띄운다.
    그런데 _ssl 하나 때문에 libcrypto(5.0MB) + libssl(0.8MB) 이 따라 들어온다.

    조용히 잘못 동작하는 것이 제일 나쁘므로, 껍데기를 건드리는 순간
    바로 터지고 로그에 스택까지 남긴다. 소스로 실행할 때는 진짜 ssl 을 쓴다.
    """
    if "ssl" in sys.modules:
        return
    try:
        __import__("ssl")
        return                                        # 진짜가 있으면 그대로
    except ImportError:
        pass

    import types

    def missing(name):
        """껍데기를 건드리면 로그를 한 번 남기고 AttributeError 를 낸다.

        AttributeError 로 내보내야 hasattr 같은 확인은 조용히 False 가 되고,
        실제로 쓰려는 곳은 바로 실패한다. 조용히 잘못 동작하는 것보다 낫다.
        """
        if not (name.startswith("__") and name.endswith("__")):
            import traceback
            try:
                import paths
                paths.log("ssl 껍데기 접근: %s" % name + chr(10)
                          + "".join(traceback.format_stack()[-4:]))
            except Exception:
                pass
        raise AttributeError(
            "ssl.%s - 이 빌드에는 ssl 이 없습니다 (용량을 줄이려고 제외)" % name)

    m = types.ModuleType("ssl")
    m.__getattr__ = missing
    m.SSLError = type("SSLError", (OSError,), {})
    m.CERT_NONE = 0
    sys.modules["ssl"] = m




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
    lines.append("  ssl         " + ("껍데기(용량 절약)" if getattr(
        sys.modules.get("ssl"), "__file__", None) is None else "정품"))
    for mod in ("PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFilter",
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

    lines += ["", "[그림 읽기 점검] 트레이 아이콘이 여기서 막힌 적이 있다"]
    try:
        from PIL import Image
        Image.preinit()
        Image.init()
        lines.append("  등록된 형식 %d개: %s" % (len(set(Image.ID)),
                                             ", ".join(sorted(set(Image.ID)))))
        for mod in ("zlib", "PIL._imaging", "PIL.PngImagePlugin",
                    "PIL.IcoImagePlugin", "PIL.BmpImagePlugin"):
            try:
                __import__(mod)
                lines.append("  OK    " + mod)
            except Exception as e:
                lines.append("  실패  %s: %s: %s" % (mod, type(e).__name__, e))
        for f in (paths.ICON, os.path.join(paths.WEB_DIR, "icon-16.png")):
            try:
                with Image.open(f) as im:
                    lines.append("  OK    %s %s" % (os.path.basename(f), im.size))
            except Exception as e:
                lines.append("  실패  %s: %s: %s" % (os.path.basename(f),
                                                    type(e).__name__, e))
    except Exception:
        lines.append("  " + traceback.format_exc().replace(chr(10), chr(10) + "  "))

    lines += ["", "[알림 점검] 어제~내일의 각 회차가 언제 알려지는지"]
    try:
        import app
        plan = app.notify_plan()
        lines.append("  지금 %s · 기본 알림 %d분 전" % (plan["now"], plan["default_lead_min"]))
        for r in plan["rows"]:
            mark = "예정" if r["will_notify"] else ("이미 띄움" if r["already_fired"] else "건너뜀")
            lines.append("  %s %5s  알림 %-11s  %-9s %-14s %s"
                         % (r["date"], r["time"] or "--:--", r["notify_at"] or "-",
                            mark, r["skip"], r["title"][:24]))
    except Exception:
        lines.append("  " + traceback.format_exc().replace(chr(10), chr(10) + "  "))

    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    try:                                    # 결과를 바로 볼 수 있게 열어준다
        os.startfile(out)
    except Exception:
        pass


def run():
    stub_ssl()
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
