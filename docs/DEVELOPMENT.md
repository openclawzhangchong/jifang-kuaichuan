# 机房快传 · 开发手册

> 适用版本：v1.1.0（见 CHANGELOG.md）。本手册所有代码摘录均取自仓库真实源码，可对照检查；命令均可在仓库根目录直接执行。产品形态：① **桌面版**——教师机起 Flask 服务（`desktop/`），学生浏览器扫码/输地址；② **网页版 P2P**——纯前端 WebRTC（`web/`），发布在 GitHub Pages，无服务器中转。

## 目录：1.项目结构 · 2.技术栈与运行环境 · 3.本地开发 · 4.架构与关键实现 · 5.数据契约 · 6.测试与验收 · 7.构建与部署 · 8.二次开发指南 · 9.常见坑 · 10.维护与发布清单

## 1. 项目结构

```text
jifang-kuaichuan/
├── README.md                    # 产品说明：三形态对比、截图、隐私与安全边界
├── CHANGELOG.md                 # 版本记录（当前 1.1.0）
├── LICENSE                      # MIT
├── .gitignore                   # 忽略运行期数据：共享文件/、收到的作业/、打包_*.zip
├── .github/workflows/pages.yml  # CI：push main 后把 web/ 整目录发布到 GitHub Pages
├── desktop/                     # ===== 桌面版（教师机）=====
│   ├── 启动机房快传.bat          # 入口：放行防火墙 → cd server → python server.py
│   └── server/
│       ├── server.py            # 全部后端（约 300 行）：Flask 路由、安全清洗、二维码、端口探测
│       ├── static/
│       │   ├── teacher.html     # 教师操作台（路由 /）：二维码 + 发文件 + 收作业，5s 轮询
│       │   └── student.html     # 学生端（路由 /student）：下载共享 + 交作业，4s 轮询
│       ├── 共享文件/             # 运行期生成：教师→学生的文件（已被 .gitignore）
│       └── 收到的作业/           # 运行期生成：<班级>/<姓名>/<文件> 归档树（已被 .gitignore）
├── web/                         # ===== 网页版 P2P（无后端）=====
│   ├── index.html               # WebRTC 点对点互传，邀请码握手，零依赖单文件
│   └── test/
│       └── selftest.html        # 回环自测页：同页两条 PeerConnection 互传 2MB 并比对哈希
├── scripts/                     # 验收 / 渗透脚本（依赖 requests，用法见 §6）
│   ├── accept_2.py              # 端到端验收：走真实 LAN IP，上传→下载哈希一致、归档、zip
│   └── pento_2.py               # 渗透：路径穿越、Windows 保留名、金丝雀删除
└── docs/
    ├── DEVELOPMENT.md           # 本手册
    └── screenshots/             # README 引用的三张界面截图
```

职责一句话：`server.py` 是桌面版唯一后端（无数据库，文件系统即存储）；两个 HTML 各自内联 CSS/JS、无构建步骤；`web/index.html` 是零依赖单文件 P2P 页面；`scripts/` 是发布前的验收与安全回归入口。

## 2. 技术栈与运行环境

| 层 | 技术 | 说明 |
|---|---|---|
| 桌面版服务端 | Python 3.10+ / Flask | 标准库 + Flask，仅此而已；`pathlib` 直接操作文件系统 |
| 服务端二维码 | qrcode（Pillow 出 PNG） | `add_qrcode()` 生成 PNG 的 base64 dataURL；缺库时降级为空串 |
| 桌面版前端 | 原生 HTML/CSS/JS | 单文件内联，无框架无打包；`fetch`/XHR + 轮询 `/api/info` |
| 网页版 P2P | 纯前端 WebRTC DataChannel | `RTCPeerConnection`，信令靠复制粘贴邀请码，无信令服务器 |
| 浏览器要求 | Chrome / Edge 现代版；iOS Safari 建议 14.5+ | 需要 fetch/FormData/Blob；P2P 页另需 WebRTC 与 `crypto.subtle`（低版本 iOS 的兼容坑见 §9.3） |

安装桌面版依赖 `pip install flask qrcode pillow`；网页版没有任何依赖，也不需要 Node/构建工具——改完 HTML 刷新页面即生效。

## 3. 本地开发

### 3.1 桌面版

```bash
python desktop/server/server.py     # 或 cd desktop/server && python server.py
```

- 监听 **`0.0.0.0:<port>`**（局域网可达），默认端口 **8899**，并自动打开浏览器访问 `http://127.0.0.1:<port>`。
- **端口占满自动 +1..30**：`pick_port()` 从配置端口起连续试 30 个端口，逐个尝试 `bind("0.0.0.0", port)`：

```python
def pick_port(start):
    for port in range(start, start + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise RuntimeError("端口都被占用")
```

- 端口可用 `desktop/server/config.json` 覆盖：`{"port": 8899}`（`load_cfg()` 读取，缺省 8899）。
- 环境变量 `ZC_NO_BROWSER=1` 禁止自动弹浏览器：源码里 `threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}"))` 以该变量为开关（写自动化脚本时用）。
- 启动横幅会打印教师操作台地址与学生地址 `http://<LAN_IP>:<port>/student`；数据目录 `共享文件/`、`收到的作业/` 启动时自动 `mkdir(exist_ok=True)`。

### 3.2 网页版（P2P）

纯静态托管即可，WebRTC 传输不依赖这个服务器（它只发过一次 HTML）：

```bash
python -m http.server 8000 --directory web
# 打开 http://127.0.0.1:8000/                       （P2P 页）
# 打开 http://127.0.0.1:8000/test/selftest.html     （自测页）
```

### 3.3 防火墙：`启动机房快传.bat` 的逻辑

bat 在启动前确保 Windows 防火墙放行 8899/TCP 入站（规则名 `JifangKuaichuan-8899`）：

```bat
netsh advfirewall firewall show rule name="JifangKuaichuan-8899" >nul 2>&1
if errorlevel 1 (
  netsh advfirewall firewall add rule name="JifangKuaichuan-8899" dir=in action=allow protocol=TCP localport=8899 >nul 2>&1
  if errorlevel 1 (
    echo [提示] 防火墙规则添加未成功（可能没有管理员权限）。
    echo        如果学生端打不开网页：右键本脚本，选「以管理员身份运行」一次即可。
  )
)
cd /d "%~dp0server"
python server.py
```

流程：`show rule` 查规则是否已存在（不存在则 errorlevel 1）→ 不存在则 `add rule` 放行 → 添加失败（无管理员权限）只提示不中断 → `cd /d "%~dp0server"` 切到 bat 所在目录下的 `server/` → `python server.py`。手动放行的等价命令：

```bat
netsh advfirewall firewall add rule name="JifangKuaichuan-8899" dir=in action=allow protocol=TCP localport=8899
```

注意：bat 只放行 8899 一个端口；若 8899 被占导致服务漂到 8900+，学生端会被防火墙拦住（见 §9.6）。

## 4. 架构与关键实现

### 4.1 总体架构

```text
【桌面版】
教师机(Windows)                                     学生机/手机（同局域网）
+---------------------------+        HTTP           +--------------+
| desktop/server/server.py  | <-- 0.0.0.0:8899 --> |  浏览器页面    |
|  Flask + 文件系统存储       |                       | student.html |
|  共享文件/   收到的作业/    |                       +--------------+
+---------------------------+
     服务端二维码：http://<LAN_IP>:<port>/student（扫码直达）

【网页版 P2P】
发送方浏览器 <--(邀请码/应答码 人肉信令)--> 接收方浏览器
        文件走 WebRTC DataChannel（DTLS 加密），服务器只提供网页本身
```

### 4.2 双向文件流协议（桌面版）

**教师 → 学生（共享）**：教师页 `upFiles()` 把文件塞进 `FormData`（字段名固定 `files`，可多个），`POST /api/share/upload`；服务端对每个文件 `safe_name()` 清洗后落盘 `共享文件/`，响应带回最新 `share` 列表；学生页 4s 轮询 `/api/info` 即刻看到。下载 `GET /api/share/download/<name>`（`send_file(..., as_attachment=True)`），全部打包 `GET /api/share/pack`——现场打 zip 返回：

```python
stamp = time.strftime("%Y%m%d_%H%M%S")
pack = BASE / f"打包_共享文件_{stamp}.zip"
with zipfile.ZipFile(str(pack), "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
    for p in files:
        z.write(str(p), arcname=p.name)  # 中文 arcname 用 utf-8 标志写入
```

**学生 → 教师（作业）**：学生页校验姓名非空后 `POST /api/work/upload`（form 字段 `cls`、`student`、`files[]`，XHR `upload.onprogress` 显示进度条）；服务端按 `收到的作业/<班级>/<姓名>/` 建目录归档。教师端 `GET /api/work/pack` 把整棵树打成三层结构 zip：

```python
z.write(str(f), arcname=f"{cls.name}/{st.name}/{f.name}")
```

撤回/清理走 `POST /api/share/delete` 与 `POST /api/work/delete`（后者支持删单文件，或 `shutil.rmtree` 清空某学生的整个目录——这正是 §4.5 安全设计存在的原因）。

### 4.3 服务端二维码与 LAN IP 探测

`GET /api/info` 返回 `url`、`port`、`qrcode`（PNG base64 dataURL，指向 `<url>/student`）、`share`、`work`。二维码在服务端生成，学生端零 JS 依赖：

```python
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
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""   # 未装 qrcode/pillow 时降级：页面只显示文字地址
```

URL 里的 IP 由 `lan_ip()` 探测，两级策略：

```python
def lan_ip() -> str:
    """探测本机局域网 IP（优先网关路径；失败回退到任何 192.168/10.x 地址）。"""
    # ① UDP connect 网关法：connect 一个外部地址（不发包），让路由表选出源 IP
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.168.1", 80))
        ip = s.getsockname()[0]
        if ip and not ip.startswith("127."):
            return ip
    ...
    # ② 兜底：解析 ipconfig 输出，取第一个 192.168./10./172. 的 IPv4
    out = os.popen("ipconfig").read()
    m = re.findall(r"IPv4[^\d]*([\d.]+)", out)
    for ip in m:
        if ip.startswith(("192.168.", "10.", "172.")):
            return ip
    ...
    return "127.0.0.1"
```

UDP connect 不发任何包，只让内核按路由表挑最合适的出口 IP，无副作用；失败（无路由等）才走 `ipconfig` 正则；全失败回退 `127.0.0.1`。

### 4.4 网页版 WebRTC（web/index.html）

**信令封装（GNK1. 前缀 base64）**：SDP 描述 JSON 化后做 UTF-8 安全的 base64，加 `GNK1.` 前缀便于识别、防误贴：

```js
function enc(desc){return "GNK1."+btoa(unescape(encodeURIComponent(JSON.stringify(desc))))}
function dec(text){
  text=text.trim();
  if(!text.startsWith("GNK1."))throw new Error("不是有效的码（应以 GNK1. 开头）");
  return JSON.parse(decodeURIComponent(escape(atob(text.slice(5)))));
}
```

`btoa` 只认 Latin-1，`escape(encodeURIComponent(...))` 是把 UTF-8 字节交给 btoa 的经典手法，保证任何字符不出错。

**无 trickle ICE（waitIce 4s 兜底）**：邀请码里必须带全 ICE 候选，否则对端无法直连。收发两侧都在 `setLocalDescription` 后等收集完成再出码，最多等 4 秒：

```js
function waitIce(pc){
  return new Promise(res=>{
    if(pc.iceGatheringState==="complete")return res();
    const t=setTimeout(res,4000);
    pc.addEventListener("icegatheringstatechange",()=>{ if(pc.iceGatheringState==="complete"){clearTimeout(t);res()} });
  });
}
```

4 秒兜底的原因：STUN（`stun:stun.cloudflare.com:3478`、`stun:stun.l.google.com:19302`）不可达时收集可能迟迟不 complete，不能让用户无限等——局域网内 host candidate 已足够，超时照样出码。

**DataChannel 分块协议**：单条名为 `file` 的通道（`binaryType="array"`），字符串帧是 JSON 控制消息，二进制帧是 64KB 文件块：

```js
const CHUNK=65536;
dc.send(JSON.stringify({t:"meta",name:f.name,size:f.size}));   // ① meta
// ② 分块：f.slice(offset,end).arrayBuffer() 后 dc.send(二进制)
dc.send(JSON.stringify({t:"done",name:f.name}));               // ③ done
```

接收端 `dc.onmessage` 按 `typeof ev.data` 分流：字符串帧解析 `{t:"meta"|"done"}`；二进制帧 `new Uint8Array(ev.data)` 累积进 `incoming.parts`；收到 `done` 后 `finishIncoming()` 用 **`new Blob(incoming.parts)` 重组**、`URL.createObjectURL` 生成 `<a download>` 保存链接。文件之间间隔 120ms（`setTimeout(r,120)`）给接收端 UI 一帧喘息。

**流控 drain()**：发送缓冲无限累积会撑爆内存，发送循环每块之前检查：

```js
async function drain(){
  const HIGH=8*1024*1024;
  while(dc.bufferedAmount>HIGH && dc.readyState==="open"){
    await new Promise(r=>{ dc.onbufferedamountlow=()=>{dc.onbufferedamountlow=null;r()} });
  }
}
```

`bufferedAmount` 超过 8MB 就挂起，等浏览器触发 `bufferedamountlow` 再继续——WebRTC 文件传输的标准背压写法（自测页 selftest.html 用同样手法，阈值 4MB）。

**多文件发送**：`sendAll()` 顺序遍历 `files`，每个文件重置 `offset=0` → meta → `pump()` 分块 → done；任一文件中断（`dc.readyState!=="open"` 或 `send` 抛异常）立即停止并提示"连接中断，发送停止"。

### 4.5 安全设计：safe_name + contained

**威胁模型**：桌面版按"机房内可信"设计，无登录鉴权；但要防两类经典攻击——路径穿越读写（`../server.py`）与"删除接口变 format 按钮"。`api/work/delete` 里有 `shutil.rmtree`（递归强删），一旦让 `cls=".."` 之类输入拼出容器外的路径，攻击者可以删掉教师机上任意目录。因此上传名与拼接路径全部过两层防线：

```python
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.I)

def safe_name(name: str) -> str:
    """清洗文件/目录名：剥路径分隔符、去首尾点号（阻断 .. 穿越）、拦 Windows 保留设备名。"""
    name = os.path.basename(name or "")                                   # ① 剥掉目录部分
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', "_", name).strip().strip(".")  # ② 非法字符→_，剥首尾点号
    if not cleaned or _RESERVED.match(cleaned):                           # ③ 空名/保留名→前缀 _
        cleaned = "_" + (cleaned or "file")
    return cleaned or "file.txt"
```

- `os.path.basename` 先把 `..\..\x` 变成 `x`；
- `.strip(".")` 把 `..` 清成空串再兜底改名，穿越分量直接消失；
- `CON/PRN/AUX/NUL/COM1-9/LPT1-9` 是 Windows 保留设备名（`con.txt` 历史上会把写入串到控制台），统一加 `_` 前缀。

```python
def contained(base: Path, p: Path) -> bool:
    """路径容器校验：拼接后的最终路径必须仍在 base 内（防御纵深）。"""
    try:
        return os.path.commonpath([str(base.resolve()), str(p.resolve())]) == str(base.resolve())
    except ValueError:
        return False
```

`contained()` 在下载/删除前对**最终拼接结果**再验一次。为什么有了 `safe_name` 还要它？`safe_name` 只作用于单个名字，而 `WORK_DIR / cls / student / name` 是多级拼接——万一某级清洗有遗漏或未来代码新增拼接点，容器校验保证最终路径也出不了 `收到的作业/`，属于纵深防御。删除接口在 rmtree 前还显式判了一次：

```python
if not contained(WORK_DIR, p):
    return jsonify({"error": "非法路径"}), 400
```

两层防御都由 `scripts/pento_2.py` 的渗透用例锁定（§6.2），包括金丝雀目录法：在产品根目录放一个待删探针，用 `cls=".."` 尝试越界删除，探针仍在才算 PASS。

## 5. 数据契约

### 5.1 HTTP API 全表（desktop/server/server.py，共 11 条路由 = 2 个页面 + 9 个 API）

| # | 方法与路径 | 入参 | 出参 / 行为 |
|---|---|---|---|
| 1 | GET `/` | - | 教师操作台页（render_template teacher.html） |
| 2 | GET `/student` | - | 学生端页（render_template student.html） |
| 3 | GET `/api/info` | - | `{url, port, qrcode, share[], work[]}`；url=`http://<lan_ip>:<port>`，qrcode 为指向 `/student` 的 PNG dataURL（可能为空串） |
| 4 | POST `/api/share/upload` | multipart `files`（可多个） | `{ok:[落盘名…], failed:["原名: 原因"…], share[]}`；落盘 `共享文件/<safe_name>` |
| 5 | GET `/api/share/download/<path:name>` | - | 文件流（as_attachment）；不在容器内或不存在 → 404 |
| 6 | GET `/api/share/pack` | - | `打包_共享文件_<时间戳>.zip`；无文件 → 404 |
| 7 | POST `/api/share/delete` | JSON `{name}` | 删除该共享文件，返回 `{ok, share[]}` |
| 8 | POST `/api/work/upload` | form `cls`、`student`；`files`（可多个） | `{ok[], failed[]}`；归档 `收到的作业/<班级>/<姓名>/`；缺省落 `未填班级`/`未填姓名` |
| 9 | GET `/api/work/download/<cls>/<student>/<name>` | - | 文件流；三级都过 `safe_name` + `contained`，失败 404 |
| 10 | POST `/api/work/delete` | JSON `{cls, student, name?}` | 带 `name` 删单文件；不带则 rmtree 学生目录；容器外 → 400 `{error:"非法路径"}`；返回 `{ok, work[]}` |
| 11 | GET `/api/work/pack` | - | `打包_作业_<时间戳>.zip`，arcname 三层 `<班级>/<姓名>/<文件>`；空目录 → 404 |

`share[]` 元素：`{name, size, size_h, mtime}`（按 mtime 倒序）；`work[]` 元素：`{cls, students:[{student, files:[{name,size,size_h,mtime}]}]}`。上传体上限 `MAX_CONTENT_LENGTH = 4GB`，超限返回 413。

### 5.2 磁盘布局（全部相对 `desktop/server/`）

```text
desktop/server/
├── server.py / static/ …                # 代码与页面
├── config.json                          # 可选：{"port": 8899}
├── 共享文件/                             # 教师→学生；上传平铺落此目录
├── 收到的作业/
│   └── <班级>/            ← safe_name(request.form["cls"])
│       └── <姓名>/       ← safe_name(request.form["student"])
│           └── <文件>    ← safe_name(f.filename)
└── 打包_共享文件_YYYYMMDD_HHMMSS.zip / 打包_作业_YYYYMMDD_HHMMSS.zip   # pack 产物
```

运行期目录已被 `.gitignore` 忽略（`共享文件/`、`收到的作业/`、`打包_*.zip`），仓库永远不含用户数据。

### 5.3 WebRTC 消息格式（web/index.html）

**信令码**（复制粘贴的字符串）：

```text
GNK1.<base64( UTF-8( JSON({"type":"offer"|"answer", "sdp":{...RTCSessionDescription}}) ))>
```

**DataChannel 帧序列**（每个文件）：

| 顺序 | 类型 | 载荷 |
|---|---|---|
| 1 | 字符帧 | `{"t":"meta","name":"讲义.pdf","size":1048576}` |
| 2..N | 二进制帧 | 65536 字节/块（末块可不足），`binaryType="array"` 收到 ArrayBuffer |
| N+1 | 字符帧 | `{"t":"done","name":"讲义.pdf"}` |

接收端状态机：`meta` → `incoming={name,size,parts:[]}`；二进制 → `parts.push(Uint8Array)` 并按 `received/size` 刷进度；`done` → `new Blob(parts)` 重组出下载链接并清空 `incoming`。目前协议没有逐块 ACK（DataChannel 默认 ordered+reliable，通道不断即不丢不乱序），需要续传时见 §8.b。

## 6. 测试与验收

三个入口，各管一段：`accept_2.py` 管功能端到端，`pento_2.py` 管安全边界，`selftest.html` 管 P2P 协议。

### 6.1 `scripts/accept_2.py` —— 端到端验收（走真实 LAN IP）

前提：桌面版已启动。执行（先 `pip install requests`）：

```bash
python scripts/accept_2.py http://192.168.x.x:8899 evidence
```

覆盖点（全走 LAN IP，证明 `0.0.0.0` 真的对局域网开放）：教师/学生页 200 → `/api/info` 的 url 以 `192.168.` 开头、二维码是合法 base64 PNG → 上传中文课件名（`测试课件_计算机网络第五章.pdf`）→ 学生列表可见 → **下载回读 SHA-256 与上传字节一致** → 共享打包 zip 内含该文件且字节一致 → 学生交作业（班级 `24级3班`、姓名 `张三`）→ 教师端归档树正确 → 单文件下载哈希一致 → 作业打包 zip 内路径恰为 `24级3班/张三/第五章作业_张三.pdf` → 撤回共享文件 → 清理测试作业。报告写 `evidence/product2_accept.json`，全过输出 `全部通过 [OK]` 并以退出码 0 结束，任何一项失败退出码 1（可挂 CI）。

### 6.2 `scripts/pento_2.py` —— 渗透测试（穿越 / 保留名 / 金丝雀）

```bash
python scripts/pento_2.py     # 目标 http://127.0.0.1:8899
```

四组用例：① 路径穿越下载（`..%2F..%2Fserver.py`、`..`、`cls=..%2F..%2F`）必须 400/404 且不泄露源码；② **金丝雀**：脚本在产品根目录建 `canary_probe_dir/x.txt`，然后 `POST /api/work/delete {"cls":"..","student":"canary_probe_dir"}`，探针目录必须仍然存在——这是 §4.5 两层防御（`safe_name` 把 `..` 清洗成 `_file` + `contained` 拒容器外路径）的直接验证；③ 恶意文件名上传（`..`、`.`、300 字符名、含换行名、`con.txt`）都不得按原名落盘；④ 正常边界回归（含 `#` 的中文名往返哈希一致）。报告写 `evidence/pento_2.json`，结尾打印 `x/y 通过，发现 n 个漏洞`。注意脚本内 `PROD` 常量指向金丝雀的宿主目录，换机器时改成自己的产品根目录。

### 6.3 `web/test/selftest.html` —— WebRTC 回环自测

**原理**：同一个页面里建两条 `RTCPeerConnection`（A 发 B 收），手动互喂 `onicecandidate`（纯 host candidate 即可打通，不依赖外网 STUN，机房断外网也能跑）；生成 **2MB `crypto.getRandomValues` 随机数据**先算 SHA-256，然后按与 index.html 完全相同的协议（`meta` → 65536B 分块 + 4MB 流控 → `done`）传给 B；B 重组 Blob 再算哈希比对。判定三条件：接收哈希一致 && 字节数一致 && 收到 done。超时保护：ICE 12s、接收 15s，任何异常路径都保证输出 FAIL。

**运行方式**（任选其一，看页面输出的 `RESULT:PASS` / `RESULT:FAIL`）：

```bash
# 方式 A：本地 http.server + 无头浏览器（crypto.subtle 需要可信来源，127.0.0.1 满足）
python -m http.server 8000 --directory web
msedge --headless=new --disable-gpu --virtual-time-budget=40000 --dump-dom http://127.0.0.1:8000/test/selftest.html | findstr RESULT:
#（chrome 亦可，同样支持 --headless=new --dump-dom）

# 方式 B：资源管理器直接双击 selftest.html（file:// 在 Chrome/Edge 视为可信来源，crypto.subtle 可用）
```

页面纯自动无交互，结尾输出一行 `RESULT:PASS` 或 `RESULT:FAIL`，grep 它即可做自动化断言。

## 7. 构建与部署

### 7.1 GitHub Pages（网页版）

`.github/workflows/pages.yml`：push 到 `main`（或手动 `workflow_dispatch`）→ `upload-pages-artifact` 直接以 **`web/` 为站点根** → `deploy-pages` 发布。无构建步骤，线上地址 `https://openclawzhangchong.github.io/jifang-kuaichuan/`，自测页在 `/test/selftest.html`。

```yaml
- uses: actions/upload-pages-artifact@v3
  with:
    path: web
- id: deployment
  uses: actions/deploy-pages@v4
```

改 `web/index.html` 后 push main 即自动更新线上版。

### 7.2 桌面版：拷目录即用

桌面版没有"构建"概念：把 `desktop/` 整个目录拷到教师机，装好 Python 3.10+ 与 `flask qrcode pillow`，双击 `启动机房快传.bat` 即可。数据目录与 zip 产物都生成在 `desktop/server/` 内，升级时只替换 `server.py` 与 `static/`，不要覆盖 `共享文件/`、`收到的作业/`。需要单文件 exe 时见 §8.d。

## 8. 二次开发指南

每个案例给出：改哪些文件 → 关键函数 → 注意事项。

### a. 加访问口令（防隔壁班乱入）

- **改 `server.py`**：口令放进 `config.json`（`load_cfg()` 已并入该文件，加一个 `"token"` 字段即可，缺省空 = 不启用），挂 `before_request` 钩子：

```python
TOKEN = CFG.get("token", "")

@app.before_request
def gate():
    if not TOKEN:
        return                        # 未配置口令 = 保持现状
    if request.args.get("token") == TOKEN or request.cookies.get("jfk") == TOKEN:
        return
    return "需要口令", 401
```

首次访问 `/` 或 `/student?token=xxx` 校验通过后 `resp.set_cookie("jfk", TOKEN, httponly=True)`，后续请求靠 cookie 免输。
- **改 `student.html`**：加口令输入框，token 存 `localStorage`，所有 `fetch`/XHR URL 后拼 `?token=`（页面现有 `up()` 与 `refresh()` 两处请求点）。
- **注意**：二维码 URL 要带口令——`/api/info` 里 `add_qrcode(url + "/student")` 改成 `add_qrcode(url + "/student?token=" + TOKEN)`，学生扫码免输；口令走查询串是明文，机房场景够用但别当重要密码用；`before_request` 对页面也生效，注意保留 token 正确时的放行分支，别把自己锁死。

### b. 断点续传 / 分片确认（网页版协议扩展）

- **改 `web/index.html`**：`meta` → 分块 → `done` 的帧序列不变，往里加确认帧。DataChannel 默认 **ordered + reliable**，通道不断时块不丢、不乱序——所以"续传"只在连接断开重连后才有含义，设计为：
  1. 接收端每收 16 块（或每秒一次）回一帧 `{"t":"ack","name":...,"offset":<已收字节数>}`（JSON 字符帧；别逐块 ACK，会与 `drain()` 背压打架）；
  2. 发送端在 `pump()` 里维护 `acked` 游标（取收到的最大 offset 与本地 offset 的较小值），进度条按 acked 显示，`done` 只在 acked==size 后发；
  3. 断线重连：接收端把 `incoming.parts` 与 `received` 持久化到 IndexedDB（内存 Blob 数组刷新即丢），新通道打开后先发 `{"t":"resume","name":...,"offset":N}`；发送端 `f.slice(N).arrayBuffer()` 从 N 续发；`done` 前双方各算一遍 SHA-256（`crypto.subtle.digest`，用法参考 selftest.html）兜底校验。
- **关键函数**：`pump()`（游标起点改为可注入的 resume offset）、`drain()`（不动）、`sendAll()`（重连后按 resume 重新进入 pump）、接收端 `wireReceiverChannel()`（加 ack 定时器与 resume 分支）。
- **注意**：resume 时先等接收端确认再开泵，否则发送端可能把已收数据冲掉；`offset` 必须以接收端 ack 为准而非发送端 bufferedAmount——后者只代表"发出去了"，不代表对端收到。

### c. 教师端广播消息 / 课堂广播屏

建议做在桌面版（P2P 版是 1:1 且无信令服务器，多点广播没有现成信道）：
- **最简（轮询，改动最小）**：`server.py` 加内存变量 `BROADCAST = {"text": "", "ts": 0}`，加 `POST /api/broadcast`（教师页发文本，写入变量）并把 `broadcast` 字段并进 `/api/info` 响应；学生页已有 4s 轮询 `refresh()`，把 `info.broadcast.text` 画成顶部横幅即可。零新协议，十来行搞定。
- **实时（SSE）**：`server.py` 加 `GET /api/stream` 返回 `text/event-stream`（每连接一个队列，推 `data: {...}\n\n`），学生页 `new EventSource("/api/stream")` 监听，断线自动重连。`app.run` 默认多线程，几十个 SSE 连接没问题。
- **改哪些文件**：`server.py`（新路由 + `/api/info` 增字段）、`teacher.html`（广播输入框）、`student.html`（横幅渲染）。
- **注意**：消息不落盘（下课即失效是特性）；教师页与横幅渲染都要过 `esc()` 转义（页面已有现成函数）；P2P 版若也要广播，得引入信令服务器做多连接管理，成本远超收益。

### d. 打包成单文件 exe（PyInstaller）

- **命令**（在 `desktop/server/` 下）：

```bash
pyinstaller --noconfirm --onefile --name JifangKuaichuan ^
  --add-data "static;static" ^
  --collect-all qrcode --collect-all PIL ^
  --icon jfk.ico server.py
```

- **必改代码**：`server.py` 顶部 `BASE = Path(__file__).resolve().parent` 在 onefile 模式下指向 `%TEMP%\_MEIxxxx` 临时解压目录——只读资源与用户数据必须分开解析：

```python
import sys
def res_path(rel):   # 只读资源（static/）从解包目录取
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / rel

app = Flask(__name__, static_folder=str(res_path("static")), template_folder=str(res_path("static")))

DATA_BASE = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
SHARE_DIR = DATA_BASE / "共享文件"     # 用户数据必须落在 exe 旁边，否则关机即蒸发
WORK_DIR  = DATA_BASE / "收到的作业"
```

- **注意**：① `--collect-all qrcode --collect-all PIL` 防止 qrcode/Pillow 的延迟 import 被 PyInstaller 静态分析漏掉（`add_qrcode` 是函数内 `import qrcode`）；② exe 未签名会被 Windows SmartScreen 拦一道（"仍要运行"），防火墙逻辑照旧——建议把 §3.3 的 netsh 命令挪进程序启动或保留 bat 包一层；③ 别加 `-w`（noconsole），控制台横幅和"关窗口即停服"都依赖它；④ 打包后先跑 §6.1/§6.2 两个脚本回归再分发。

## 9. 常见坑

1. **PAC/系统代理吃掉 LAN 流量**：学生机若配了 PAC 或全局代理，`192.168.x.x` 的请求可能被塞给代理服务器然后失败，表现为"ping 得通但打不开页面"。解法：代理例外里加 `192.168.*` 或 `<local>`。教师机自己用 `127.0.0.1` 调试不受影响（loopback 一般绕过代理）。
2. **Edge/Chrome 对 localhost 与 LAN 的双标（可信来源）**：`http://127.0.0.1` 是可信来源，`http://192.168.x.x` 不是——`navigator.clipboard`、`crypto.subtle` 等只在可信来源可用。桌面版页面刻意没碰这些 API 所以无感；给网页版加功能（如 §b 的哈希校验）时注意：GitHub Pages 的 https 没问题，LAN 内自托管 P2P 页则要绕开或降级。（桌面版走的是 http 无证书，谈不上证书问题，本质是安全上下文判定。）
3. **iOS Safari 的 DataChannel 二进制兼容**：老 iOS（约 <14.5）对 DataChannel 二进制帧支持不完整，且 `<a download>` 触发的保存是"先预览再存"。若必须兼容，降级路径：二进制块 base64 后走 JSON 字符帧（体积 +33%，机房小文件可接受），或提示 iOS 用户改用桌面版网址。
4. **zip 中文文件名编码**：`zipfile` 对非 ASCII arcname 会自动打 UTF-8 标志位（§4.2 代码注释），Win10+ 资源管理器与主流解压工具显示正常；但默认 GBK 的老解压器可能乱码。目标环境有老机器时，文档里推荐 7-Zip/Bandizip，或加一个 GBK 编码 zip 的可选项。
5. **并发上传的覆盖语义**：`/api/share/upload` 与 `/api/work/upload` 都按 `safe_name(原文件名)` 直接落盘，**同名即覆盖、后传者为准**——两个同名学生（同班同名）会互相覆盖作业。这是有意的简单语义；要防覆盖可把落盘名改成 `"时间戳_原名"`（只改 `api_work_upload`），但 `list_work()`、下载路由与打包 arcname 都要跟着适配。
6. **端口漂移导致防火墙失效**：8899 被占时 `pick_port()` 漂到 8900..8928，而 bat 只放行 8899——学生会连不上而教师本机一切正常（`127.0.0.1` 不走防火墙入站规则）。处理：看启动横幅的实际端口手动补 netsh 规则，或把 bat 规则改成端口段。
7. **上传 4GB 上限**：`MAX_CONTENT_LENGTH = 4GB`，超限 Flask 直接 413；更大文件请压缩或分卷。网页 P2P 版无此限制（内存允许即可），但 8MB 流控阈值下超大文件耗时线性增长。

## 10. 维护与发布清单

发布前逐项过：

- [ ] `python scripts/accept_2.py http://<LAN_IP>:8899 evidence` 全 PASS（退出码 0）
- [ ] `python scripts/pento_2.py` 0 漏洞（金丝雀仍在）
- [ ] `web/test/selftest.html` 输出 `RESULT:PASS`（双击或无头跑）
- [ ] 真机冒烟：一台学生机 + 一台手机，扫码 → 下载 → 交作业 → 教师端打包
- [ ] CHANGELOG.md 版本号与日期更新；README 截图与入口链接仍有效
- [ ] `git status` 里没有 `共享文件/`、`收到的作业/`、`打包_*.zip`（.gitignore 已兜底）
- [ ] push main → GitHub Pages Actions 绿 → 在线版抽一次 P2P 互传
- [ ] 桌面版分发目录 `desktop/` 整拷 + 目标机 `pip install flask qrcode pillow` 验证过
- [ ] 打 git tag（`v1.x.x`）与 CHANGELOG 对齐

维护要点：`server.py` 是单文件后端，改完必须跑 §6.1/§6.2 两个脚本——`safe_name`/`contained` 的行为被渗透用例锁定，动安全函数先跑 pento；前端 HTML 无构建，改完刷新即生效，但两个页面各有独立的 `refresh()` 轮询与 `esc()` 转义，新增任何动态渲染都必须过 `esc()`，轮询间隔（教师 5s/学生 4s）若调整注意两处同步。
