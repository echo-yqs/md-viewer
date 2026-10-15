# md-viewer

Windows 桌面 Markdown 所见即所得编辑器：**双击任意 `.md` 直接弹出一个原生窗口**，渲染效果等同 IDE 预览栏（Chromium 内核），并且渲染出来的带格式内容**本身可以直接编辑**，`Ctrl+S` 存回 Markdown。

- 独立窗口程序，不打开浏览器、无后台进程，关窗即退出
- 渲染内核 = Win11 系统自带 WebView2 运行时（Chromium），无需额外安装组件
- 单目录绿色安装，用户级文件关联（HKCU），不需要管理员权限

## 功能

| 功能 | 说明 |
| ---- | ---- |
| 所见即所得编辑 | 渲染后的标题/代码/表格直接点击编辑，所见即所改 |
| `Ctrl+S` 保存 | 格式化内容经内嵌 Turndown 转回 Markdown 写回原文件，状态栏显示保存状态 |
| 划词复制 | 直接拖选文字，右键菜单 / Ctrl+C 均可 |
| 自动刷新（预览） | 外部编辑器里 `Ctrl+S`，窗口 1 秒内更新，滚动位置不丢 |
| `F5` | 放弃未保存编辑，从磁盘重新载入 |
| 本地图片 | 文档同目录相对路径图片正常显示 |
| 编码容错 | UTF-8 / GBK 自动识别 |

## 安装

```powershell
# 1. 构建（在工程根目录，任意带 tkinter 的 Python 3.13）
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\pyinstaller --noconfirm --clean --onedir --noconsole --name md-viewer ^
  --add-data "assets;assets" ^
  --collect-all webview --collect-all pythonnet --collect-all clr_loader --collect-all proxy_tools ^
  --collect-submodules pygments md_viewer_webview.py

# 2. 安装（注册文件关联 + 开始菜单/桌面快捷方式 + 卸载器，自动结束旧实例）
.venv\Scripts\python install_md_viewer.py
```

安装后：双击任意 `.md` 打开；从快捷方式启动则弹文件选择框。

- 程序位置：`%LOCALAPPDATA%\md-viewer\app\md-viewer.exe`
- 卸载：双击 `%LOCALAPPDATA%\md-viewer\uninstall.bat`，注册表关联、快捷方式、程序文件全部清除
- Windows 第一次双击可能弹一次「你要如何打开这个文件」——选 md-viewer 并勾选「始终」

## 技术要点

- **渲染**：`pywebview` 内嵌系统 WebView2（检测注册表 `EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}` 的 `pv` 值）；Markdown → HTML 用 `markdown`（GFM 表格/任务列表/codehilite + Pygments 高亮），样式为 GitHub 风格 CSS
- **编辑回存**：页面为 `contenteditable`，保存时用内嵌 [Turndown](https://github.com/mixmark-io/turndown)（MIT，30 KB，`assets/` 随包）+ GFM 插件把 HTML 转回 Markdown；标题、代码围栏（含语言标注）、表格、图片相对路径、引用、列表往返无损
- **打包**：PyInstaller `--onedir`（单文件 onefile 模式每次启动要自解包，慢 2~7 秒；目录版约 1 秒）

## 目录结构

```
md-viewer/
├── md_viewer_webview.py    # 主程序（WebView2 版，当前维护）
├── install_md_viewer.py    # 安装器（文件关联/快捷方式/卸载器/结束旧实例）
├── assets/                 # turndown.js + turndown-plugin-gfm.js（随包内嵌）
├── samples/                # 测试样例（含本地图片引用）
├── legacy/                 # 历史版本：浏览器版(md_viewer.py)、tkinterweb 版(md_viewer_gui.py)
├── requirements-dev.txt
└── .gitignore
```

## 版本演进

1. `md_viewer.py` —— 本地 HTTP 服务 + 默认浏览器（已弃用）
2. `md_viewer_gui.py` —— tkinterweb（TkHtml 控件）原生窗口（已弃用：CSS 子集太弱，渲染质量与浏览器差距大）
3. `md_viewer_webview.py` —— **当前版本**：pywebview + 系统 WebView2，预览质量等同 IDE 预览栏，并支持所见即所得编辑
