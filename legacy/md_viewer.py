# -*- coding: utf-8 -*-
"""
md_viewer.py - Markdown 双击查看器
用法:
    python md_viewer.py <file.md> [--no-open] [--port N]

行为:
    1. 在 127.0.0.1 上起一个临时本地服务(随机端口)
    2. 把 md 渲染成 GitHub 风格 HTML(代码高亮/表格/任务列表)
    3. 自动调起默认浏览器打开
    4. 文件保存后页面自动刷新(实时预览)
    5. md 所在目录内的本地图片/引用文件也能正常加载
    6. 浏览器关闭后约 1 小时服务自动退出,不留后台垃圾
"""
import argparse
import hashlib
import http.server
import io
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import webbrowser

import markdown
from pygments.formatters import HtmlFormatter

INACTIVITY_TIMEOUT = 3600  # 秒:无任何请求(含轮询)1小时后自动退出

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
}
h1, h2 { border-bottom: 1px solid #d1d9e0; padding-bottom: .3em; }
h1, h2, h3, h4, h5, h6 { font-weight: 600; margin-top: 1.5em; margin-bottom: .8em; line-height: 1.3; }
h1 { font-size: 2em; margin-top: 0; }
h2 { font-size: 1.5em; }
h3 { font-size: 1.25em; }
p { margin: .8em 0; }
a { color: #0969da; text-decoration: none; }
a:hover { text-decoration: underline; }
code, pre, kbd {
  font-family: ui-monospace, Consolas, "Cascadia Code", "Courier New", monospace;
}
code {
  background: rgba(175,184,193,.2); border-radius: 6px;
  padding: .2em .4em; font-size: 85%;
}
pre {
  background: #f6f8fa; border-radius: 8px; padding: 16px;
  overflow-x: auto; line-height: 1.5;
}
pre code { background: none; padding: 0; font-size: 100%; }
.codehilite { background: #f6f8fa; border-radius: 8px; }
.codehilite pre { margin: 0; }
blockquote {
  margin: 1em 0; padding: 0 1em; color: #59636e;
  border-left: .25em solid #d1d9e0;
}
table { border-collapse: collapse; margin: 1em 0; display: block; overflow-x: auto; max-width: 100%; }
th, td { border: 1px solid #d1d9e0; padding: 6px 13px; }
th { background: #f6f8fa; font-weight: 600; }
tr:nth-child(2n) td { background: #f6f8fa; }
img { max-width: 100%; border-radius: 4px; }
hr { border: 0; border-top: 2px solid #d1d9e0; margin: 2em 0; }
ul, ol { padding-left: 2em; }
li + li { margin-top: .25em; }
input[type=checkbox] { margin-right: .4em; }
.task-list-item { list-style-type: none; margin-left: -1.4em; }
.badge {
  position: fixed; right: 12px; bottom: 12px; z-index: 9;
  font-size: 12px; color: #8b949e; background: rgba(255,255,255,.9);
  border: 1px solid #d0d7de; border-radius: 20px; padding: 3px 12px;
  user-select: none;
}
"""

RELOAD_JS = """
(function () {
  var last = "%(sig)s";
  setInterval(function () {
    fetch("/poll?sig=" + encodeURIComponent(last))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.sig && d.sig !== last) { location.reload(); }
      })
      .catch(function () {});
  }, 1200);
})();
"""


def read_text(path):
    raw = open(path, "rb").read()
    # 跳过 BOM
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="replace")


def render(md_path, base_url):
    text = read_text(md_path)
    pyg_css = HtmlFormatter(style="default").get_style_defs(".codehilite")
    body = markdown.markdown(
        text,
        extensions=["extra", "sane_lists", "toc", "codehilite", "md_in_html"],
        extension_configs={
            "codehilite": {"guess_lang": False, "css_class": "codehilite"},
            "toc": {"permalink": False},
        },
        output_format="html5",
    )
    # 相对路径的图片/媒体 -> 走本地文件服务 /f/
    body = re.sub(
        r'''(<(?:img|video|audio|source)\b[^>]*?\bsrc=)(["'])(?!https?://|#|data:)([^"']+)\2''',
        lambda m: '%s%s%s/f/%s%s' % (m.group(1), m.group(2),
                                     base_url, urllib.parse.quote(m.group(3)), m.group(2)),
        body,
        flags=re.I,
    )
    title = os.path.basename(md_path)
    return (
        "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>%s</title><style>%s%s</style></head><body>"
        "<div class=\"page\">%s</div><div class=\"badge\">md-viewer · 保存自动刷新</div>"
        "<script>%s</script></body></html>"
    ) % (title, CSS, pyg_css, body, RELOAD_JS)


def file_signature(md_path):
    try:
        st = os.stat(md_path)
        return hashlib.md5(
            ("%d-%d-%s" % (st.st_mtime_ns, st.st_size, md_path)).encode()
        ).hexdigest()
    except OSError:
        return "gone"


def safe_join(root, rel):
    root = os.path.realpath(root)
    full = os.path.realpath(os.path.join(root, rel))
    if full != root and not full.startswith(root + os.sep):
        return None
    return full


class Handler(http.server.BaseHTTPRequestHandler):
    md_path = None
    md_dir = None
    last_hit = [time.time()]

    def log_message(self, *a):  # 静默
        pass

    def touch(self):
        self.last_hit[0] = time.time()

    def send_bytes(self, data, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.touch()
        url = urllib.parse.urlparse(self.path)
        if url.path == "/poll":
            want = urllib.parse.parse_qs(url.query).get("sig", [""])[0]
            cur = file_signature(Handler.md_path)
            self.send_bytes(
                json.dumps({"sig": cur, "changed": bool(want) and cur != want}).encode(),
                "application/json; charset=utf-8",
            )
            return
        if url.path == "/":
            try:
                html = render(Handler.md_path, "http://127.0.0.1:%d" % self.server.server_port)
                self.send_bytes(html.encode("utf-8"), "text/html; charset=utf-8")
            except Exception as e:
                msg = "<pre>渲染失败:\n%s</pre>" % e
                self.send_bytes(msg.encode("utf-8"), "text/html; charset=utf-8")
            return
        if url.path.startswith("/f/"):
            rel = urllib.parse.unquote(url.path[len("/f/"):])
            full = safe_join(Handler.md_dir, rel)
            if full and os.path.isfile(full):
                try:
                    with open(full, "rb") as f:
                        data = f.read()
                except OSError:
                    self.send_error(500)
                    return
                ctype = "application/octet-stream"
                ext = os.path.splitext(full)[1].lower()
                known = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                         ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
                         ".bmp": "image/bmp", ".ico": "image/x-icon", ".mp4": "video/mp4",
                         ".mp3": "audio/mpeg", ".wav": "audio/wav", ".txt": "text/plain; charset=utf-8"}
                ctype = known.get(ext, ctype)
                self.send_bytes(data, ctype)
                return
        self.send_error(404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mdfile", help="要查看的 .md 文件路径")
    ap.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--port", type=int, default=0, help="指定端口(默认随机)")
    args = ap.parse_args()

    md_path = os.path.abspath(args.mdfile)
    if not os.path.isfile(md_path):
        print("文件不存在: %s" % md_path, file=sys.stderr)
        sys.exit(2)

    Handler.md_path = md_path
    Handler.md_dir = os.path.dirname(md_path)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = "http://127.0.0.1:%d/" % srv.server_port
    try:
        print(url, flush=True)
    except Exception:
        pass  # pythonw / 无控制台打包环境下 stdout 为 None

    if not args.no_open:
        def _open():
            try:
                webbrowser.open(url)
            except Exception:
                os.startfile(url)  # 打包环境兜底
        threading.Thread(target=_open, daemon=True).start()

    # 看门狗:无请求超时自动退出
    def watchdog():
        while True:
            time.sleep(30)
            if time.time() - Handler.last_hit[0] > INACTIVITY_TIMEOUT:
                os._exit(0)

    threading.Thread(target=watchdog, daemon=True).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
