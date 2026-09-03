# -*- coding: utf-8 -*-
"""Windows 자동 실행 등록 / 바탕화면 바로가기 만들기."""
import os
import subprocess
import winreg

import paths

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "TodoManager"
NO_WINDOW = 0x08000000


def _cmd():
    """로그인할 때 실행할 명령.

    --silent 를 붙여 창을 띄우지 않고 조용히 시작한다. 대신 창을 숨긴 채로
    미리 만들어 두므로(app.prewarm_window), 나중에 아이콘을 누르면 곧바로 열린다.
    """
    p = paths.exe_path()
    if not p.startswith('"'):
        p = f'"{p}"'
    return p + " --silent"


def is_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, NAME)
        return True
    except OSError:
        return False


def set_enabled(on):
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            if on:
                winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, _cmd())
            else:
                try:
                    winreg.DeleteValue(k, NAME)
                except OSError:
                    pass
        return is_enabled()
    except OSError:
        return is_enabled()


def make_desktop_shortcut():
    """바탕화면에 바로가기(.lnk) 생성. 만들어진 경로를 돌려준다."""
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(desktop):
        desktop = os.path.join(os.environ.get("USERPROFILE", ""), "OneDrive", "Desktop")
    if not os.path.isdir(desktop):
        return None
    link = os.path.join(desktop, "To-Do Manager.lnk")

    target = paths.exe_path()
    if not paths.FROZEN:                     # 개발 중에는 pythonw + main.py
        runner, _, arg = target.partition('" "')
        target, args = runner.strip('"'), arg.rstrip('"')
    else:
        args = ""

    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{link}');"
        "$s.TargetPath='{target}';"
        "$s.Arguments='{args}';"
        "$s.WorkingDirectory='{wd}';"
        "$s.IconLocation='{icon}';"
        "$s.Description='To-Do Manager - 일정/루틴 관리';"
        "$s.Save()"
    ).format(link=link.replace("'", "''"), target=target.replace("'", "''"),
             args=args.replace("'", "''"), wd=paths.APP_DIR.replace("'", "''"),
             icon=(paths.ICON if os.path.exists(paths.ICON) else target).replace("'", "''"))
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       creationflags=NO_WINDOW, timeout=25,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return None
    return link if os.path.exists(link) else None
