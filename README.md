# BladePower — Razer Blade 16 功耗 / 风扇 / 降压快捷工具

**中文** | [English](README.en.md)

面向 **Razer Blade 16（RZ09-0483，i9-13950HX + RTX 4090 Laptop）** 的 Windows 管理工具：用 GUI、全局热键、托盘切换自定义性能档，并支持雷云同款 CPU/GPU 档位、可选自定义 PL1/PL2、软件风扇曲线、全局降压。

> **需要管理员权限**（读写 CPU MSR / 加载 WinRing0）。请先小步验证功耗与温度，过高或过深降压可能导致过热或不稳定。

界面语言：主页顶部 **界面语言 → 中文 / English**（写入 `profiles.json` 的 `settings.ui_language`）。

---

## 功能一览

| 模块 | 说明 | 默认 |
|------|------|------|
| **CPU 档位** | 雷云同款：低 / 中 / 高 / 增强；**自定义** 才写 PL1/PL2/Tau | 开 |
| **GPU 档位** | 雷云同款低 / 中 / 高（HID，实测见下表） | 开 |
| **CPU 降压** | Core / Cache / E-Cache（MSR 0x150），与档位独立 | 开 |
| **风扇曲线** | 按 CPU/GPU 温度插值设定双区转速（与档位风扇互斥） | 关（页内启用） |
| **自动亮度** | 按插电/电池切换屏幕亮度；可选锁定与 OLED 下限 | 关（页内启用） |
| **热键 / 托盘 / OSD** | 全局热键、托盘（可自选菜单档位并显示当前档）、可选桌面浮层 | — |
| **开机自启** | 登录后托盘静默启动，并套用上次档位与降压 | 可选 |
| **休眠恢复** | 睡眠/休眠唤醒后重申降压与（若启用）功耗设定 | 自动 |
| **Afterburner** | 可选静默 `-ProfileN`（不写 GPU 绝对 TDP） | 可选 |

各模块可在主页 **功能模块** 中独立开关。

---

## CPU 档位怎么选

| CPU 档 | 行为 |
|--------|------|
| **低 / 中 / 高 / 增强** | 只写 EC（与雷云 Custom 滑条同源），**不写** PL1/PL2 |
| **自定义** | EC 抬到「增强」作底，再写 **PL1 / PL2 / Tau**（MSR） |

降压始终独立：开关「CPU 降压」即可，不依赖 CPU 是否为自定义。

> 若只改 GPU 档却发现 CPU 被卡在约 55W：多半是 EC 进 Custom 后 CPU 落在 low。请打开「CPU 档位」并显式选择增强/高，或改用「自定义」+ 合适 PL。

---

## GPU 档（本机实测参考）

| GPU 档 | 约 GPU 上限 | 约整机最大负载 |
|--------|-------------|----------------|
| 低 | ~100 W | ~160 W |
| 中 | ~150 W | ~180 W |
| 高 | ≥175 W | ~205 W |

本机 **无法** 用 `nvidia-smi` / Afterburner 写绝对 GPU 瓦数，只能切低/中/高。

---

## 预置性能档（可改可删）

| 名称 | CPU 档 | PL1/PL2（自定义时） | GPU | 热键 |
|------|--------|---------------------|-----|------|
| 静音 | 低 | 55 / 75 W | 低 | `Ctrl+Alt+1` |
| 均衡 | 中 | 60 / 80 W | 中 | `Ctrl+Alt+2` |
| 性能 | 高 | 75 / 95 W | 中 | `Ctrl+Alt+3` |
| 水冷 | 增强 | 130 / 150 W | 高 | `Ctrl+Alt+4` |
| 恢复默认 | — | 电压归零 + 安全档 | — | `Ctrl+Alt+0` |

---

## 环境要求

- Windows 10 / 11，**64 位**
- **管理员权限**
- 源码运行：Python 3.10+（推荐 3.11/3.13）
- `vendor/winring0/` 中有 `WinRing0x64.dll` + `WinRing0x64.sys`
- GPU/风扇：Razer HID（与 Synapse 同源）。冲突时可暂时完全退出雷云后再试

---

## 安装（源码）

```bat
cd /d F:\source_code\Power_limit_change
py -3 -m pip install -r requirements.txt
```

确认 WinRing0 文件存在后，任选其一启动：

```bat
run_as_admin.bat
```

或：

```bat
py -3 -m app.main
```

（非管理员会尝试 UAC 提权。）

依赖见 `requirements.txt`：`psutil`、`hidapi`、`keyboard`、`pystray`、`Pillow` 等。

---

## 一键打包 exe

双击 `build_exe.bat`（需已放置 WinRing0 与 `Synapse.ico`）。

输出目录：

```
dist\BladePower_Release\
  BladePower.exe
  WinRing0x64.dll / WinRing0x64.sys   # 必须与 exe 同目录
  profiles.json                      # 已存在则不会被打包覆盖
  README.md / README.en.md / 使用说明.txt
```

整夹拷贝即可使用；右键 **以管理员身份运行** `BladePower.exe`。

---

## 使用说明

1. **功能模块**：按需开关 CPU 档位 / GPU 档位 / 降压；风扇曲线在「风扇曲线」页启用  
2. **搭配编辑器**：设 CPU 档、GPU 档、风扇；仅当 CPU=**自定义** 时 PL1/PL2/Tau 生效  
3. **应用**：左侧选档 → 应用，或热键；编辑后可「立即应用 / 保存到当前档 / 另存为」  
4. **降压**：底部全局 mV → 保存 / 重新应用；`Ctrl+Alt+0` 恢复默认  
5. **风扇曲线**：启用后由温度曲线接管转速（档位内风扇设定让出）；RPM `0` = 交回 EC 自动（低温可停转）  
6. **自动亮度**：在「自动亮度」页按供电切换亮度；支持亮度锁定与 OLED 最低 60%；休眠唤醒后自动校正  
7. 关闭窗口默认进托盘（依赖 pystray/Pillow）

### 配置文件

| 运行方式 | `profiles.json` 位置 |
|----------|----------------------|
| 源码 | 项目根目录 |
| 打包 exe | 与 `BladePower.exe` **同目录** |

请勿把仓库根目录配置与 `dist\...\profiles.json` 混用。

### 实时状态（节选）

- `EC_CPU` / `EC_GPU`：后台轮询；HID 超时会显示上次成功值并标 `(缓存)`  
- `CPU PL` / `CPU 功耗`：MSR 读回与 Package 功耗估算  
- `UV`：当前降压读回  

---

## 限制与注意

1. **EC 与 MSR 同时生效**：有效功耗常为更严的一层；固定 CPU 档不写 PL，自定义档才写 MSR。  
2. **勿与雷云「CPU 超频」面板 / Intel XTU 同时乱改同一组 PL**，易互相抢写。降压可与 XTU 对照，但不要两边同时狂改。  
3. **雷云 HID**：占用时读写可能超时；工具已降低读频率并缓存档位显示。  
4. **WinRing0** 常被杀软误报，请对程序目录加白名单。  
5. 过高功耗或过深降压风险自负；出问题先 `Ctrl+Alt+0` 或关机冷启动。

---

## 项目结构

```
app/
  main.py                 入口、热键、托盘、状态轮询、休眠恢复
  gui.py                  主界面与功能开关
  profile_manager.py      档位 CRUD、模块化应用编排
  backends/
    winring0.py           WinRing0 驱动加载 / MSR / PCI
    cpu_rapl.py           PL1/PL2/Tau（自定义 CPU 档）
    cpu_undervolt.py      降压 MSR 0x150
    synapse_gpu.py        雷云 EC：CPU/GPU 档、风扇
    fan_curve.py          软件风扇曲线
    physmem.py            物理内存多后端（MMIO 诊断，可选）
    afterburner.py        Afterburner 配置档
    ...
  widgets/                风扇曲线图、热键录制等
vendor/winring0/          WinRing0 二进制（见 README_VENDOR.md）
profiles.json             用户档位与设置
BladePower.spec           PyInstaller 规格
build_exe.bat / run_as_admin.bat
```

---

## 许可证与免责

本项目供个人学习与自用调优。修改功耗/电压/风扇可能影响稳定性与硬件寿命；作者不对任何损失负责。WinRing0 等第三方驱动请遵守其各自许可。
