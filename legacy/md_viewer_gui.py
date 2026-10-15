# -*- coding: utf-8 -*-
"""
md_viewer_gui.py - Markdown 原生窗口查看器(不依赖浏览器)
tkinter + tkinterweb(纯 Tk HTML 控件,非浏览器引擎)
用法:
    md-viewer.exe <file.md>        双击 .md 关联启动
    md-viewer.exe --selftest <f>   无窗口自检
"""
import argparse
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import markdown
from pygments.formatters import HtmlFormatter

try:
    from tkinterweb import HtmlFrame
except Exception as e:  # 打包缺文件时给出明确报错
    if "--selftest" in sys.argv:
        print("tkinterweb import failed: %s" % e)
        sys.exit(3)
    raise

POLL_INTERVAL_MS = 1000

CSS = """
body { font-family: "Microsoft YaHei", "Segoe UI", sans-serif; font-size: 14px;
       line-height: 1.65; color: #1f2328; background-color: #ffffff;
       margin: 18px 22px; }
h1 { font-size: 22px; color: #1f2328; }
h2 { font-size: 19px; color: #24292f; }
h3 { font-size: 16px; color: #24292f; }
code { font-family: Consolas, "Courier New", monospace; font-size: 13px;
       background-color: #f0f2f5; color: #c7254e; }
pre { font-family: Consolas, monospace; font-size: 13px;
      background-color: #f6f8fa; color: #24292f; padding: 10px; }
blockquote { color: #59636e; padding-left: 12px; }
table { border-collapse: collapse; }
th { background-color: #f0f2f5; font-weight: bold; }
td, th { padding: 4px 8px; }
a { color: #0969da; }
hr { color: #d0d7de; }
img { max-width: 100%; }
"""


def read_text(path):
    raw = open(path, "rb").read()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="replace")


def render(md_path):
    """md -> 完整 HTML 字符串(代码高亮用内联样式,tkhtml 不认外部 CSS 类)"""
    text = read_text(md_path)
    body = markdown.markdown(
        text,
        extensions=["extra", "sane_lists", "toc", "codehilite", "md_in_html"],
        extension_configs={
            "codehilite": {"guess_lang": False, "noclasses": True,
                           "formatter": HtmlFormatter(style="default", noclasses=True)},
            "toc": {"permalink": False},
        },
        output_format="html5",
    )
    base = "file:///" + os.path.dirname(os.path.abspath(md_path)).replace("\\", "/") + "/"
    return (
        '<html><head><meta charset="utf-8">'
        '<base href="%s"><style>%s</style></head><body>%s</body></html>'
    ) % (base, CSS, body)


def file_signature(md_path):
    try:
        st = os.stat(md_path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


class ViewerApp:
    def __init__(self, root, md_path):
        self.root = root
        self.md_path = os.path.abspath(md_path)
        self.sig = None
        self.auto = tk.BooleanVar(value=True)

        root.title(os.path.basename(self.md_path) + " - md-viewer")
        root.geometry("1080x800")

        # 顶部工具条
        bar = tk.Frame(root, bg="#eef1f4")
        bar.pack(side=tk.TOP, fill=tk.X)
        tk.Button(bar, text="打开 (Ctrl+O)", command=self.open_file,
                  relief=tk.FLAT, bg="#eef1f4", activebackground="#dde3e8").pack(side=tk.LEFT, padx=4, pady=3)
        tk.Button(bar, text="刷新 (F5)", command=self.reload,
                  relief=tk.FLAT, bg="#eef1f4", activebackground="#dde3e8").pack(side=tk.LEFT, padx=4, pady=3)
        tk.Checkbutton(bar, text="自动刷新", variable=self.auto,
                       bg="#eef1f4", activebackground="#eef1f4").pack(side=tk.LEFT, padx=4)
        self.status = tk.Label(bar, text="", bg="#eef1f4", fg="#656d76")
        self.status.pack(side=tk.RIGHT, padx=8)

        self.frame = HtmlFrame(root, messages_enabled=False)
        self.frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        root.bind("<Control-o>", lambda e: self.open_file())
        root.bind("<F5>", lambda e: self.reload())
        root.protocol("WM_DELETE_WINDOW", root.destroy)

        self.load()
        self.root.after(POLL_INTERVAL_MS, self.watch)

    def set_status(self, msg):
        self.status.config(text=msg)

    def load(self):
        try:
            html = render(self.md_path)
        except Exception as e:
            messagebox.showerror("md-viewer", "渲染失败:\n%s" % e)
            return
        self.sig = file_signature(self.md_path)
        self.frame.load_html(html)
        self.set_status("%s · %s" % (os.path.basename(self.md_path), time.strftime("%H:%M:%S")))

    def reload(self):
        self.load()

    def open_file(self):
        p = filedialog.askopenfilename(
            filetypes=[("Markdown", "*.md *.markdown"), ("所有文件", "*.*")])
        if p:
            self.md_path = os.path.abspath(p)
            self.root.title(os.path.basename(self.md_path) + " - md-viewer")
            self.load()

    def watch(self):
        """文件变更监听(线程外:直接轮询 stat,开销可忽略)"""
        if self.auto.get():
            if file_signature(self.md_path) != self.sig:
                self.load()
        self.root.after(POLL_INTERVAL_MS, self.watch)


def selftest(md_path):
    html = render(md_path)
    checks = ["<table", "codehilite" in html or "color:", "你好", "<h1", "<pre"]
    ok = all([c in html if isinstance(c, str) else c for c in checks])
    print("selftest:", "PASS" if ok else "FAIL", "| html bytes:", len(html))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mdfile", nargs="?", default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        if not args.mdfile:
            print("selftest 需要 md 文件路径")
            return 2
        return selftest(args.mdfile)

    md_path = args.mdfile
    if md_path is None:
        # 无参启动:弹文件选择框(从开始菜单/桌面快捷方式打开时)
        tmp = tk.Tk()
        tmp.withdraw()
        md_path = filedialog.askopenfilename(
            filetypes=[("Markdown", "*.md *.markdown"), ("所有文件", "*.*")])
        tmp.destroy()
        if not md_path:
            return 0
    if not os.path.isfile(md_path):
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("md-viewer", "文件不存在:\n%s" % md_path)
        return 2

    root = tk.Tk()
    ViewerApp(root, md_path)
    root.mainloop()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        if "--selftest" in sys.argv:
            print("selftest ERROR: %s" % e)
            sys.exit(1)
        raise
