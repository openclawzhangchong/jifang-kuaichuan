# -*- coding: utf-8 -*-
"""产品2《机房快传》安全/边界渗透测试（金丝雀验证，不破坏真实数据）"""
import os, io, json, hashlib, requests

BASE = "http://127.0.0.1:8899"
PROD = r"C:\Users\Administrator\Desktop\02-机房快传"
results = []

def check(name, ok, detail):
    results.append({"name": name, "ok": bool(ok), "detail": str(detail)[:150]})
    print(("PASS " if ok else "**BUG** ") + name + " | " + str(detail)[:150])

# 金丝雀：产品根目录下建一个待删目录，验证 cls=".." 是否能越界删除它
canary = os.path.join(PROD, "canary_probe_dir")
os.makedirs(canary, exist_ok=True)
open(os.path.join(canary, "x.txt"), "w").write("probe")

print("========== 1. 路径穿越下载（读任意文件） ==========")
r = requests.get(BASE + "/api/share/download/..%2F..%2Fserver.py", timeout=10)
leak = "Flask" in r.text or "faster" in r.text or b"import" in r.content
check("下载穿越 ..%2F..%2Fserver.py 被拦截", r.status_code in (400, 404) and not leak, f"HTTP {r.status_code} body[:80]={r.text[:80]!r}")
r = requests.get(BASE + "/api/share/download/..", timeout=10)
check("下载组件为 .. 被拦截", r.status_code in (400, 404), f"HTTP {r.status_code}")
r = requests.get(BASE + "/api/work/download/..%2F..%2F/x/y", timeout=10)
check("作业下载穿越(cls=..%2F..%2F)被拦截", r.status_code in (400, 404), f"HTTP {r.status_code}")

print("========== 2. 目录穿越删除（金丝雀） ==========")
r = requests.post(BASE + "/api/work/delete", json={"cls": "..", "student": "canary_probe_dir"}, timeout=10)
still = os.path.isdir(canary)
check("删除穿越 cls='..' 不可越界（金丝雀仍在=安全）", still, f"HTTP {r.status_code} resp={r.text[:80]!r} canary_still_exists={still}")

print("========== 3. 恶意/边界文件名上传 ==========")
for nm in ("..", ".", "a"*300, "换\n行.txt", "con.txt"):
    r = requests.post(BASE + "/api/share/upload", files={"files": (nm, io.BytesIO(b"x"*16))}, timeout=10)
    j = r.json()
    failed_or_ok = nm not in j.get("ok", [])
    check(f"上传异常文件名 {nm[:12]!r} 不落盘", failed_or_ok and r.status_code == 200, f"ok={j.get('ok')} failed={j.get('failed')[:1] if j.get('failed') else None}")

print("========== 4. 正常边界回归 ==========")
data = os.urandom(1024)
h0 = hashlib.sha256(data).hexdigest()
r = requests.post(BASE + "/api/share/upload", files={"files": ("边界测试_中文名#1.txt", io.BytesIO(data))}, timeout=10)
check("含#号中文名上传", "边界测试_中文名#1.txt" in r.json().get("ok", []), str(r.json().get("ok")))
r = requests.get(BASE + "/api/share/download/边界测试_中文名#1.txt", timeout=10)
check("含#号中文名下载哈希一致", hashlib.sha256(r.content).hexdigest() == h0, f"HTTP {r.status_code}")
requests.post(BASE + "/api/share/delete", json={"name": "边界测试_中文名#1.txt"}, timeout=10)
r = requests.get(BASE + "/api/info", timeout=10)
check("info 正常", r.status_code == 200 and "url" in r.json(), "")

# 清理金丝雀
if os.path.isdir(canary):
    import shutil
    shutil.rmtree(canary)
    print("金丝雀已清理（未被穿越删除，属于服务端无能为力的正常情况）")

with open("evidence/pento_2.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
bugs = [x for x in results if not x["ok"]]
print(f"\n=== 产品2渗透测试：{len(results)-len(bugs)}/{len(results)} 通过，发现 {len(bugs)} 个漏洞 ===")
