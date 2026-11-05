# -*- coding: utf-8 -*-
"""
机房快传（局域网互传 + 作业回收）
- 双击「启动机房快传.bat」，教师机自动开放网页服务
- 学生/手机连同一 Wi-Fi/网线，扫码或输入地址即可：
  ①「发文件」：教师拖入文件，全班一键下载（或打包下载）
  ②「收作业」：学生填班级姓名上传，自动按 班级/姓名 归档，教师一键打包
- 全程局域网内传输，不经外网。
"""
import io
import json
import os
import re
import socket
import threading
import time
import uuid
import webbrowser
import zipfile
from pathlib import Path

from flask import Flask, jsonify, request, send_file, render_template, abort

BASE = Path(__file__).resolve().parent
SHARE_DIR = BASE / "共享文件"     # 教师→学生 的文件
WORK_DIR = BASE / "收到的作业"    # 学生→教师 的作业
CONFIG_F = BASE / "config.json"
SHARE_DIR.mkdir(exist_ok=True)
WORK_DIR.mkdir(exist_ok=True)

DEFAULT_PORT = 8899


def load_cfg():
    cfg = {"port": DEFAULT_PORT, "storage": "产品文件夹内"}
    if CONFIG_F.exists():
        try:
            cfg.update(json.loads(CONFIG_F.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


CFG = load_cfg()
PORT = int(CFG.get("port", DEFAULT_PORT))

app = Flask(__name__, static_folder="static", template_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 4GB


def safe_name(name: str) -> str:
    name = os.path.basename(name or "")
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', "_", name).strip()
    return cleaned or "file.txt"


def lan_ip() -> str:
    """探测本机局域网 IP（优先网关路径；失败回退到任何 192.168/10.x 地址）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.168.1", 80))
        ip = s.getsockname()[0]
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    finally:
        s.close()
    try:
        out = os.popen("ipconfig").read()
        m = re.findall(r"IPv4[^\d]*([\d.]+)", out)
        for ip in m:
            if ip.startswith(("192.168.", "10.", "172.")):
                return ip
    except Exception:
        pass
    return "127.0.0.1"


def human_size(n: int) -> str:
    n = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.1f} {u}" if u != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} GB"


def list_share():
    items = []
    for p in sorted(SHARE_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_file():
            items.append({"name": p.name, "size": p.stat().st_size,
                          "size_h": human_size(p.stat().st_size),
                          "mtime": time.strftime("%m-%d %H:%M", time.localtime(p.stat().st_mtime))})
    return items


def list_work():
    """按 班级/姓名 归档的作业树。"""
    tree = []
    if not WORK_DIR.exists():
        return tree
    for cls in sorted(p for p in WORK_DIR.iterdir() if p.is_dir()):
        students = []
        for st in sorted(p for p in cls.iterdir() if p.is_dir()):
            files = []
            for f in sorted(st.iterdir()):
                if f.is_file():
                    files.append({"name": f.name, "size": f.stat().st_size,
                                  "size_h": human_size(f.stat().st_size),
                                  "mtime": time.strftime("%m-%d %H:%M", time.localtime(f.stat().st_mtime))})
            students.append({"student": st.name, "files": files})
        tree.append({"cls": cls.name, "students": students})
    return tree


def add_qrcode(url: str) -> str:
    """服务端生成二维码 PNG（base64 dataURL），学生扫码直达。"""
    try:
        import qrcode
        qr = qrcode.QRCode(box_size=6, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#1f2330", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        import base64
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


@app.get("/")
def teacher():
    return render_template("teacher.html")


@app.get("/student")
def student():
    return render_template("student.html")


@app.get("/api/info")
def api_info():
    ip = lan_ip()
    url = f"http://{ip}:{PORT}"
    return jsonify({"url": url, "port": PORT, "qrcode": add_qrcode(url + "/student"),
                    "share": list_share(), "work": list_work()})


# ---------- 教师 → 学生 ----------
@app.post("/api/share/upload")
def api_share_upload():
    ok, failed = [], []
    for f in request.files.getlist("files"):
        if not f.filename:
            continue
        try:
            f.save(str(SHARE_DIR / safe_name(f.filename)))
            ok.append(f.filename)
        except Exception as e:
            failed.append(f"{f.filename}: {e}")
    return jsonify({"ok": ok, "failed": failed, "share": list_share()})


@app.get("/api/share/download/<path:name>")
def api_share_download(name):
    p = SHARE_DIR / safe_name(name)
    if not p.is_file():
        abort(404)
    return send_file(str(p), as_attachment=True, download_name=p.name)


@app.get("/api/share/pack")
def api_share_pack():
    """全部共享文件打包 zip（边打包边流式落盘，兼容中文文件名）。"""
    files = [p for p in SHARE_DIR.iterdir() if p.is_file()]
    if not files:
        abort(404)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    pack = BASE / f"打包_共享文件_{stamp}.zip"
    with zipfile.ZipFile(str(pack), "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        for p in files:
            z.write(str(p), arcname=p.name)  # 中文 arcname 用 utf-8 标志写入
    return send_file(str(pack), as_attachment=True, download_name=pack.name)


@app.post("/api/share/delete")
def api_share_delete():
    name = safe_name(request.get_json(force=True).get("name", ""))
    p = SHARE_DIR / name
    if p.is_file():
        p.unlink()
    return jsonify({"ok": True, "share": list_share()})


# ---------- 学生 → 教师（作业回收） ----------
@app.post("/api/work/upload")
def api_work_upload():
    cls = safe_name(request.form.get("cls", "")).strip() or "未填班级"
    student = safe_name(request.form.get("student", "")).strip() or "未填姓名"
    dest = WORK_DIR / cls / student
    dest.mkdir(parents=True, exist_ok=True)
    ok, failed = [], []
    for f in request.files.getlist("files"):
        if not f.filename:
            continue
        try:
            f.save(str(dest / safe_name(f.filename)))
            ok.append(f.filename)
        except Exception as e:
            failed.append(f"{f.filename}: {e}")
    return jsonify({"ok": ok, "failed": failed})


@app.get("/api/work/download/<path:cls>/<path:student>/<path:name>")
def api_work_download(cls, student, name):
    p = WORK_DIR / safe_name(cls) / safe_name(student) / safe_name(name)
    if not p.is_file():
        abort(404)
    return send_file(str(p), as_attachment=True, download_name=p.name)


@app.post("/api/work/delete")
def api_work_delete():
    d = request.get_json(force=True)
    p = WORK_DIR / safe_name(d.get("cls", "")) / safe_name(d.get("student", ""))
    if d.get("name"):
        f = p / safe_name(d["name"])
        if f.is_file():
            f.unlink()
    elif p.is_dir():
        import shutil
        shutil.rmtree(str(p), ignore_errors=True)
    return jsonify({"ok": True, "work": list_work()})


@app.get("/api/work/pack")
def api_work_pack():
    """全部作业打包 zip：班级/姓名/文件 三层结构。"""
    if not any(WORK_DIR.iterdir()):
        abort(404)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    pack = BASE / f"打包_作业_{stamp}.zip"
    with zipfile.ZipFile(str(pack), "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        for cls in WORK_DIR.iterdir():
            if not cls.is_dir():
                continue
            for st in cls.iterdir():
                if not st.is_dir():
                    continue
                for f in st.iterdir():
                    if f.is_file():
                        z.write(str(f), arcname=f"{cls.name}/{st.name}/{f.name}")
    return send_file(str(pack), as_attachment=True, download_name=pack.name)


def pick_port(start):
    for port in range(start, start + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise RuntimeError("端口都被占用")


if __name__ == "__main__":
    PORT = pick_port(PORT)
    ip = lan_ip()
    url = f"http://{ip}:{PORT}"
    print("=" * 56, flush=True)
    print(f"  机房快传 已启动", flush=True)
    print(f"  教师操作台 : {url}", flush=True)
    print(f"  学生/手机  : {url}/student  （页面上有扫码）", flush=True)
    print(f"  共享文件放: {SHARE_DIR}", flush=True)
    print(f"  作业存放在: {WORK_DIR}", flush=True)
    print("  本窗口最小化即可；关闭窗口即停止服务。", flush=True)
    print("=" * 56, flush=True)
    if not os.environ.get("ZC_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    app.run(host="0.0.0.0", port=PORT, debug=False)
