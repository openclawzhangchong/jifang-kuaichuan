@echo off
title 机房快传（教师机）
rem 首次使用放行 Windows 防火墙（对本机 8899 端口放行），学生/手机才能连入。
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
if errorlevel 1 (
  echo.
  echo [启动失败] 请截图本窗口内容联系维护人。
  pause
)
