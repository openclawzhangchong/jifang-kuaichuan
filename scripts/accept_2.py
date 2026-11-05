# -*- coding: utf-8 -*-
"""产品2《机房快传》验收：走真实 LAN IP，验证 上传→列表→下载哈希一致、学生作业归档、zip 打包、二维码。"""
import sys, os, io, json, time, hashlib, zipfile, random, string, requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.168.199:8899"
EVID = sys.argv[2] if len(sys.argv) > 2 else "evidence"
os.makedirs(EVID, exist_ok=True)
report = {"base": BASE, "checks": []}

def check(name, ok, detail):
    report["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)})
    print(("PASS " if ok else "FAIL ") + name + " | " + str(detail))

def mkfile(size_kb=64, seed=None):
    rng = random.Random(seed)
    data = bytes(rng.getrandbits(8) for _ in range(size_kb * 1024))
    return data

# 1 教师页/学生页可访问（走 LAN IP —— 证明 0.0.0.0 对局域网开放）
r = requests.get(BASE + "/", timeout=10)
check("教师页(LAN可达)", r.status_code == 200 and "机房快传" in r.text, f"status={r.status_code} len={len(r.text)}")
r = requests.get(BASE + "/student", timeout=10)
check("学生页(LAN可达)", r.status_code == 200 and "学生端" in r.text, f"status={r.status_code} len={len(r.text)}")

# 2 info + 二维码
info = requests.get(BASE + "/api/info", timeout=10).json()
check("LAN地址探测", info["url"].startswith("http://192.168."), info["url"])
check("二维码生成", info["qrcode"].startswith("data:image/png;base64,") and len(info["qrcode"]) > 200,
      f"qr_base64={len(info['qrcode'])}B")

# 3 教师发文件 → 学生下载，字节哈希一致
blob = mkfile(128, seed=42)
h0 = hashlib.sha256(blob).hexdigest()
files = {"files": ("测试课件_计算机网络第五章.pdf", io.BytesIO(blob), "application/octet-stream")}
r = requests.post(BASE + "/api/share/upload", files=files, timeout=60)
j = r.json()
check("教师上传共享文件", "测试课件_计算机网络第五章.pdf" in j.get("ok", []), json.dumps(j, ensure_ascii=False)[:120])
names = [f["name"] for f in j["share"]]
check("学生端文件列表含该文件", "测试课件_计算机网络第五章.pdf" in names, str(names[:5]))
d = requests.get(BASE + "/api/share/download/测试课件_计算机网络第五章.pdf", timeout=60).content
h1 = hashlib.sha256(d).hexdigest()
check("下载字节哈希一致", h1 == h0, f"sha256={h1[:16]}… size={len(d)}B")

# 4 全部打包 zip（zip内含该文件，中文文件名可读）
z = requests.get(BASE + "/api/share/pack", timeout=120).content
zf = zipfile.ZipFile(io.BytesIO(z))
zl = zf.namelist()
check("共享打包zip", any("测试课件_计算机网络第五章.pdf" in n for n in zl), f"zip内文件={zl[:5]} 共{len(z)}B")
if any("测试课件_计算机网络第五章.pdf" in n for n in zl):
    inner = zf.read([n for n in zl if "测试课件" in n][0])
    check("zip内文件字节一致", hashlib.sha256(inner).hexdigest() == h0, f"sha256={hashlib.sha256(inner).hexdigest()[:16]}…")

# 5 学生交作业 → 教师端归档树 → 下载
hw = mkfile(32, seed=7)
r = requests.post(BASE + "/api/work/upload",
                  files={"files": ("第五章作业_张三.pdf", io.BytesIO(hw))},
                  data={"cls": "24级3班", "student": "张三"}, timeout=60)
j = r.json()
check("学生上传作业", "第五章作业_张三.pdf" in j.get("ok", []), json.dumps(j, ensure_ascii=False))
info = requests.get(BASE + "/api/info", timeout=10).json()
tree_ok = any(c["cls"] == "24级3班" and any(s["student"] == "张三" and
              any(f["name"] == "第五章作业_张三.pdf" for f in s["files"]) for s in c["students"]) for c in info["work"])
check("教师端按班级/姓名归档", tree_ok, json.dumps(info["work"], ensure_ascii=False)[:200])
d = requests.get(BASE + "/api/work/download/24级3班/张三/第五章作业_张三.pdf", timeout=60).content
check("教师下载作业哈希一致", hashlib.sha256(d).hexdigest() == hashlib.sha256(hw).hexdigest(), f"size={len(d)}B")

# 6 作业打包 zip 结构（班级/姓名/文件 三层）
z = requests.get(BASE + "/api/work/pack", timeout=120).content
zf = zipfile.ZipFile(io.BytesIO(z))
zl = zf.namelist()
check("作业打包zip三层结构", any(n == "24级3班/张三/第五章作业_张三.pdf" for n in zl), f"zip内={zl[:6]}")

# 7 撤回共享文件 + 清理测试作业
r = requests.post(BASE + "/api/share/delete", json={"name": "测试课件_计算机网络第五章.pdf"}, timeout=10).json()
check("撤回共享文件", "测试课件_计算机网络第五章.pdf" not in [f["name"] for f in r["share"]], "已删除")
requests.post(BASE + "/api/work/delete", json={"cls": "24级3班", "student": "张三"}, timeout=10)
info = requests.get(BASE + "/api/info", timeout=10).json()
check("清理测试作业", not any(c["cls"] == "24级3班" and any(s["student"] == "张三" for s in c["students"]) for c in info["work"]), "已清空")

with open(os.path.join(EVID, "product2_accept.json"), "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
all_ok = all(c["ok"] for c in report["checks"])
print("\n=== 产品2验收：" + ("全部通过 [OK]" if all_ok else "存在失败 [NG]") + " ===")
sys.exit(0 if all_ok else 1)
