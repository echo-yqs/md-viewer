# -*- coding: utf-8 -*-
"""安装 md-viewer (onedir 版): 复制程序目录 + HKCU 关联 + 快捷方式 + 卸载器,免管理员"""
import os
import shutil
import subprocess
import sys
import winreg

SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist", "md-viewer")
INSTALL_ROOT = os.path.join(os.environ["LOCALAPPDATA"], "md-viewer")
APP_DIR = os.path.join(INSTALL_ROOT, "app")
EXE_PATH = os.path.join(APP_DIR, "md-viewer.exe")
PROGID = "md-viewer.md"

UNINSTALL_BAT = r"""@echo off
rem Uninstall md-viewer (per-user, HKCU only)
reg delete "HKCU\Software\Classes\md-viewer.md" /f >nul 2>&1
reg delete "HKCU\Software\Classes\.md" /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.md" /f >nul 2>&1
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\md-viewer.lnk" >nul 2>&1
del "%USERPROFILE%\Desktop\md-viewer.lnk" >nul 2>&1
rd /s /q "%LOCALAPPDATA%\md-viewer" >nul 2>&1
echo md-viewer uninstalled.
pause
"""


def q(root, path, val=None):
    try:
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, val or "")[0]
    except OSError:
        return None


def set_value(root, path, val, vtype=winreg.REG_SZ):
    with winreg.CreateKey(root, path) as k:
        winreg.SetValueEx(k, "", 0, vtype, val)


def dir_size_mb(d):
    return sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(d) for f in fs) / 1048576


def main():
    if not os.path.isfile(os.path.join(SRC_DIR, "md-viewer.exe")):
        print("找不到打包目录 %s,请先 pyinstaller --onedir 打包" % SRC_DIR)
        sys.exit(2)

    # 结束运行中的实例,否则文件占用
    subprocess.run(["taskkill", "/F", "/IM", "md-viewer.exe"], capture_output=True)

    os.makedirs(INSTALL_ROOT, exist_ok=True)
    if os.path.isdir(APP_DIR):
        shutil.rmtree(APP_DIR)
    shutil.copytree(SRC_DIR, APP_DIR)
    print("程序目录 -> %s (%.1f MB)" % (APP_DIR, dir_size_mb(APP_DIR)))

    # ProgId
    set_value(winreg.HKEY_CURRENT_USER, r"Software\Classes\%s" % PROGID, "Markdown 文档 (md-viewer)")
    set_value(winreg.HKEY_CURRENT_USER, r"Software\Classes\%s\shell\open\command" % PROGID,
              '"%s" "%%1"' % EXE_PATH)
    set_value(winreg.HKEY_CURRENT_USER, r"Software\Classes\%s\DefaultIcon" % PROGID,
              "%s,0" % EXE_PATH)
    # .md 指向 ProgId
    set_value(winreg.HKEY_CURRENT_USER, r"Software\Classes\.md", PROGID)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.md") as k:
        winreg.SetValueEx(k, "Content Type", 0, winreg.REG_SZ, "text/markdown")
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.md\UserChoice")
        print("已移除旧 .md UserChoice")
    except OSError:
        pass

    up = os.path.join(INSTALL_ROOT, "uninstall.bat")
    with open(up, "w", encoding="ascii", newline="") as f:
        f.write(UNINSTALL_BAT)
    print("卸载器 -> %s" % up)

    for name, dirpath in [
        ("md-viewer.lnk", os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs")),
        ("md-viewer.lnk", os.environ["USERPROFILE"] + "\\Desktop"),
    ]:
        lnk = os.path.join(dirpath, name)
        cmd = [
            "powershell", "-NoProfile", "-Command",
            "$s = New-Object -ComObject WScript.Shell;"
            "$l = $s.CreateShortcut('%s');"
            "$l.TargetPath = '%s'; $l.Save()" % (lnk.replace("'", "''"), EXE_PATH.replace("'", "''")),
        ]
        subprocess.run(cmd, capture_output=True)
        print("快捷方式 %s: %s" % ("OK" if os.path.isfile(lnk) else "FAIL", lnk))

    print("验证: HKCU\\.md =", q(winreg.HKEY_CURRENT_USER, r"Software\Classes\.md"))
    print("验证: open cmd =", q(winreg.HKEY_CURRENT_USER,
          r"Software\Classes\%s\shell\open\command" % PROGID))
    print("安装完成。双击任意 .md 试试。")


if __name__ == "__main__":
    main()
