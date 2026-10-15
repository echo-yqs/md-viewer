# -*- coding: utf-8 -*-
"""
md_viewer_webview.py - Markdown 所见即所得编辑器(WebView2 内核)
渲染出来的格式化内容**本身可直接编辑**(contenteditable),像记事本一样打字,
区别是编辑时看到的就是排版后的样子。Ctrl+S 把编辑结果转回 Markdown 存回原文件。
- 支持划词复制、格式化直接编辑
- 编辑后未保存时,外部修改不会覆盖你的编辑(状态栏提示)
用法:
    md-viewer.exe <file.md>        双击 .md 关联启动
    md-viewer.exe --selftest <f>   无窗口自检
"""
import argparse
import os
import sys
import threading
import time

import markdown
import webview

POLL_INTERVAL_S = 1.0

CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; padding: 0;
  font-family: -apple-system, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
  font-size: 16px; line-height: 1.7; color: #1f2328;
  background: #f6f8fa;
}
.page {
  max-width: 880px; margin: 0 auto; padding: 40px 48px 80px;
  background: #ffffff; min-height: 100vh;
  box-shadow: 0 0 0 1px #d0d7de;
  outline: none; cursor: text;
}
h1, h2 { border-bottom: 1px solid #d1d9e0; padding-bottom: .3em; }
h1, h2, h3, h4, h5, h6 { font-weight: 600; margin-top: 1.5em; margin-bottom: .8em; line-height: 1.3; }
h1 { font-size: 2em; margin-top: 0; }
h2 { font-size: 1.5em; }
h3 { font-size: 1.25em; }
p { margin: .8em 0; }
a { color: #0969da; text-decoration: none; }
a:hover { text-decoration: underline; }
code, pre, kbd { font-family: ui-monospace, Consolas, "Cascadia Code", monospace; }
code { background: rgba(175,184,193,.2); border-radius: 6px; padding: .2em .4em; font-size: 85%; }
pre { background: #f6f8fa; border: 1px solid #d8dee4; border-radius: 8px; padding: 16px; overflow-x: auto; line-height: 1.5; }
pre code { background: none; padding: 0; font-size: 100%; }
blockquote { margin: 1em 0; padding: 0 1em; color: #59636e; border-left: .25em solid #d1d9e0; }
table { border-collapse: collapse; margin: 1em 0; display: block; overflow-x: auto; max-width: 100%; }
th, td { border: 1px solid #d1d9e0; padding: 6px 13px; }
th { background: #f6f8fa; font-weight: 600; }
tr:nth-child(2n) td { background: #f6f8fa; }
img { max-width: 100%; border-radius: 4px; }
hr { border: 0; border-top: 2px solid #d1d9e0; margin: 2em 0; }
ul, ol { padding-left: 2em; }
li + li { margin-top: .25em; }
input[type=checkbox] { margin-right: .4em; }
.status {
  position: fixed; right: 14px; bottom: 12px; z-index: 10;
  font-size: 12px; color: #8b949e;
  background: rgba(255,255,255,.92); border: 1px solid #d0d7de;
  border-radius: 20px; padding: 4px 14px; user-select: none;
}
.status.dirty { color: #9a6700; border-color: #d4a72c; }
"""

# JS: Turndown 配置 + 保存/快捷键/脏标记
APP_JS = """
var BASE = "%(base)s";
var td = new TurndownService({headingStyle: 'atx', codeBlockStyle: 'fenced', bulletListMarker: '-', emDelimiter: '*'});
td.use(turndownPluginGfm.gfm);

// 图片/链接: 浏览器会把相对路径解析成 file:/// 绝对路径,存回时转回相对
td.addRule('relimg', {
  filter: 'img',
  replacement: function (content, node) {
    var src = node.getAttribute('src') || '';
    if (src.indexOf(BASE) === 0) { src = src.slice(BASE.length); }
    return '![' + (node.getAttribute('alt') || '') + '](' + src + ')';
  }
});
td.addRule('rellink', {
  filter: function (node) { return node.nodeName === 'A' && node.getAttribute('href'); },
  replacement: function (content, node) {
    var href = node.getAttribute('href') || '';
    if (href.indexOf(BASE) === 0) { href = href.slice(BASE.length); }
    if (!content) { return ''; }
    return '[' + content + '](' + href + ')';
  }
});
td.addRule('taskitem', {
  filter: function (node) {
    return node.nodeName === 'INPUT' && node.type === 'checkbox';
  },
  replacement: function (content, node) {
    return node.checked ? '[x] ' : '[ ] ';
  }
});

var dirty = false;
function markDirty() {
  dirty = true;
  var s = document.getElementById('statusbar');
  if (s) { s.textContent = '未保存更改 · Ctrl+S 保存'; s.classList.add('dirty'); }
}
function markSaved() {
  dirty = false;
  var s = document.getElementById('statusbar');
  if (s) { s.textContent = '已保存 ' + new Date().toLocaleTimeString(); s.classList.remove('dirty'); }
}
function saveNow() {
  if (window.pywebview && window.pywebview.api) {
    var md = td.turndown(document.querySelector('.page').innerHTML)
               .replace(/\\n{3,}/g, '\\n\\n')
               .replace(/\\\\\[([ xX])\\\\\] ?/g, '[$1] ')  // 任务列表转义还原
               .trim() + '\\n';
    window.pywebview.api.save(md);
  }
}
function reloadFromDisk() {
  if (window.pywebview && window.pywebview.api) { window.pywebview.api.reload(); }
}
document.addEventListener('keydown', function (e) {
  if (e.ctrlKey && (e.key === 's' || e.key === 'S')) { e.preventDefault(); saveNow(); }
  else if (e.key === 'F5') { e.preventDefault(); reloadFromDisk(); }
});
document.addEventListener('input', markDirty);
"""


def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def read_text(path):
    raw = open(path, "rb").read()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="replace")


def file_signature(md_path):
    try:
        st = os.stat(md_path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def render(md_path):
    text = read_text(md_path)
    # 不用 codehilite: 代码块保持 <pre><code class=language-x>,所见即所得编辑后
    # Turndown 才能无损转回 ``` 围栏
    body = markdown.markdown(
        text,
        extensions=["extra", "sane_lists", "md_in_html"],
        output_format="html5",
    )
    base = "file:///" + os.path.dirname(os.path.abspath(md_path)).replace("\\", "/") + "/"
    turndown_js = open(resource_path(os.path.join("assets", "turndown.js")), encoding="utf-8").read()
    gfm_js = open(resource_path(os.path.join("assets", "turndown-plugin-gfm.js")), encoding="utf-8").read()
    app_js = APP_JS % {"base": base}
    return (
        "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<base href=\"%s\"><title>%s</title><style>%s</style></head><body>"
        "<div class=\"page\" contenteditable=\"true\" spellcheck=\"false\">%s</div>"
        "<div class=\"status\" id=\"statusbar\">Ctrl+S 保存 · 直接打字即可编辑</div>"
        "<script>%s</script><script>%s</script><script>%s</script></body></html>"
    ) % (base, os.path.basename(md_path), CSS, body, turndown_js, gfm_js, app_js)


class Api:
    def __init__(self, state):
        self.state = state

    def reload(self):
        self.state["sig"] = file_signature(self.state["path"])
        self.state["win"].load_html(render(self.state["path"]))

    def save(self, text):
        try:
            with open(self.state["path"], "w", encoding="utf-8", newline="") as f:
                f.write(text)
            self.state["sig"] = file_signature(self.state["path"])
            self.state["win"].evaluate_js("markSaved()")
        except Exception as e:
            self.state["win"].evaluate_js(
                "var s=document.getElementById('statusbar');"
                "s.textContent='保存失败: %s';s.classList.add('dirty');"
                % str(e).replace("'", "").replace("\\", "/"))


_state = {"path": None, "sig": None, "win": None}


def watcher(win):
    while True:
        time.sleep(POLL_INTERVAL_S)
        try:
            cur = file_signature(_state["path"])
            if cur != _state["sig"]:
                # 内容脏(有未保存编辑)时不覆盖,只提示
                changed_hint = (
                    "var s=document.getElementById('statusbar');"
                    "if(s&&!s.classList.contains('dirty')){"
                    "s.textContent='磁盘文件已更新 · F5 重新载入';}")
                try:
                    dirty = win.evaluate_js("typeof dirty!=='undefined' && dirty")
                except Exception:
                    dirty = True
                if not dirty:
                    y = win.evaluate_js("window.scrollY") or 0
                    _state["sig"] = cur
                    win.load_html(render(_state["path"]))
                    if y:
                        win.evaluate_js("window.scrollTo(0, %d)" % int(y))
                else:
                    _state["sig"] = None  # 保持"已变化"状态,存盘后归位
                    win.evaluate_js(changed_hint)
        except Exception:
            pass


def selftest(md_path):
    html = render(md_path)
    ok = all(k in html for k in ["contenteditable", "TurndownService", "turndownPluginGfm",
                                 "<table", "你好", "<h1", "base href", "saveNow"])
    print("selftest:", "PASS" if ok else "FAIL", "| html bytes:", len(html))
    return 0 if ok else 1


def run_gui(md_path):
    _state["path"] = os.path.abspath(md_path)
    _state["sig"] = file_signature(_state["path"])

    win = webview.create_window(
        os.path.basename(_state["path"]) + " - md-viewer",
        html=render(_state["path"]),
        js_api=Api(_state),
        width=1100, height=820,
        min_size=(420, 300),
        text_select=True,
    )
    _state["win"] = win
    threading.Thread(target=watcher, args=(win,), daemon=True).start()
    webview.start()


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
    if not md_path:
        import tkinter as tk
        from tkinter import filedialog
        tmp = tk.Tk()
        tmp.withdraw()
        md_path = filedialog.askopenfilename(
            filetypes=[("Markdown", "*.md *.markdown"), ("所有文件", "*.*")])
        tmp.destroy()
        if not md_path:
            return 0
    if not os.path.isfile(md_path):
        import tkinter as tk
        from tkinter import messagebox
        tmp = tk.Tk()
        tmp.withdraw()
        messagebox.showerror("md-viewer", "文件不存在:\n%s" % md_path)
        return 2

    run_gui(md_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
