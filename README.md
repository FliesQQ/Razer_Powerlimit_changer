# Blade 16 CPU/GPU 功耗快捷切换工具

面向 **Razer Blade 16 (RZ09-0483)**：用全局快捷键 / GUI 切换自定义「CPU 功耗 + Synapse GPU 低/中/高」性能档，并统一应用 XTU 风格降压。

## 功能

- **自定义性能档**：任意组合 CPU PL1/PL2/Tau 与 GPU 低/中/高，另存、编辑、删除、绑定热键
- **全局降压**：Core / Cache / E-Cache（默认 -120 / -95 / -80 mV），各档共用
- **恢复默认**：`Ctrl+Alt+0` 电压归零并应用安全档（默认「静音」）
- **GPU**：通过 Razer HID 无感切换 Synapse 同款 GPU 档（本机实测：低≈100W/整机≈160W，中≈150W/整机≈180W，高≥175W/整机≈205W）
- **风扇**：自动 / 最大 / 手动固定 RPM（约 2000–5500），可写入性能档
- **开机自启**：任务计划登录启动（托盘静默），自动应用上次档位与降压
- **休眠恢复**：睡眠/休眠唤醒后自动重申降压与功耗限制
- **可选**：MSI Afterburner `-ProfileN` 静默联动（不改 GPU Power Limit）

## 预置档（可改可删）

| 名称 | CPU PL1/PL2 | GPU | 热键 |
|------|-------------|-----|------|
| 静音 | 55 / 75 W | 低 | Ctrl+Alt+1 |
| 均衡 | 60 / 80 W | 中 | Ctrl+Alt+2 |
| 性能 | 75 / 95 W | 中 | Ctrl+Alt+3 |
| 水冷 | 130 / 150 W | 高 | Ctrl+Alt+4 |

## 要求

- Windows 10/11，**管理员权限**（CPU MSR / 降压）
- 64 位 Python 3.10+
- `vendor/winring0/` 下的 WinRing0x64.dll + .sys
- GPU 档通过 Razer HID（与 Synapse 同源）。若切换失败，请**暂时完全退出 Razer Synapse** 后重试

## 安装

```bat
cd /d F:\source_code\Power_limit_change
python -m pip install -r requirements.txt
```

确认 `vendor\winring0\WinRing0x64.dll` 与 `WinRing0x64.sys` 存在。

## 一键打包 exe

双击 `build_exe.bat`（或在项目根目录运行）。

成功后输出目录：

```
dist\BladePower_Release\
  BladePower.exe          # 主程序（需管理员）
  WinRing0x64.dll         # 必要
  WinRing0x64.sys         # 必要驱动
  WinRing0.dll / .sys     # 可选
  profiles.json
  README.md / 使用说明.txt
```

整夹拷贝即可分发；**dll/sys 必须与 exe 同目录**。

```bat
python -m app.main
```

（非管理员会自动 UAC 提权。）

## 使用说明

1. 左侧选择性能档 → **应用**，或用热键
2. 右侧编辑 CPU/GPU 组合 → **立即应用** 或 **另存为新档**
3. 下方修改全局降压 → **保存降压配置** / **重新应用我的降压**
4. 出问题：**恢复默认** 或 `Ctrl+Alt+0`
5. 关闭窗口会最小化到托盘（若 pystray/Pillow 可用）

配置文件：`profiles.json`。

## 限制与风险

- 本机 **无法** 用 nvidia-smi/Afterburner 写绝对 GPU TDP；只能切低/中/高
- Synapse/HID 占用时读写可能不稳定；工具已改为快速发送，并会尝试关闭被惊醒的雷云界面进程
- 笔记本 EC 可能回写 CPU PL，工具每 5 秒重申一次最近目标功耗
- 过高功耗可能导致过热；降压过深可能导致不稳定——请先小步验证
- WinRing0 常被杀软误报，请加白名单
- 请勿与 Intel XTU 同时乱改同一组 PL/电压

## 项目结构

```
app/
  main.py              入口
  gui.py               界面
  profile_manager.py   档位 CRUD / 应用
  backends/            MSR、Synapse GPU、Afterburner、监控
vendor/winring0/       WinRing0 驱动
profiles.json          用户配置
```
