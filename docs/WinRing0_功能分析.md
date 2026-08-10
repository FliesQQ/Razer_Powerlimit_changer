# WinRing0 对本工具（BladePower）可用功能分析

本文说明 **OpenLibSys WinRing0**（`WinRing0x64.dll` + `.sys`）在 BladePower 中的定位：哪些能力已经接入、哪些适合继续扩展、哪些不应指望它完成。面向目标机型为 **Intel + Razer Blade（EC/HID 控功耗档与风扇）**。

---

## 1. 角色边界

| 通路 | 负责内容 | 本工具实现位置 |
|------|----------|----------------|
| **WinRing0** | Intel CPU MSR /（可选）PCI·物理内存 | `app/backends/winring0.py` 及 RAPL/降压/温度后端 |
| **雷蛇 HID/EC** | CPU/GPU 功耗档、风扇模式与转速 | `app/backends/synapse_gpu.py`、`fan_curve.py` |

有效整机功耗通常是 **更严的一层**：`min(EC 策略, MSR PL, …)`。  
因此 WinRing0 **不能单独**解决「写风扇后 EC 掉到 low、功耗卡 ~55W」；那类问题靠 EC 钉住逻辑，不靠抬高 MSR。

**前置条件**

- 以管理员运行并成功加载驱动  
- 杀软对目录放行（常见误报）  
- CPU 为 **Intel**（AMD 上 PL/降压 MSR 路径基本不可用）  
- Win11 + VBS 下 **物理内存读写常失败**，MMIO RAPL 仅作尽力而为

---

## 2. 驱动能力 vs 本仓库封装

WinRing0 常见导出能力与本工具封装对照：

| WinRing0 能力 | 本仓库是否封装 | 用途倾向 |
|---------------|----------------|----------|
| `Rdmsr` / `Wrmsr` | ✅ `read_msr` / `write_msr` | 主路径：功耗、降压、温度、能量 |
| `ReadPciConfigDword` / `WritePciConfigDword` | ✅ 读已用；写已绑 API | 找 MCHBAR；写需极谨慎 |
| `ReadPhysicalMemory` / `WritePhysicalMemory` | ✅ 已封装 | MMIO RAPL；现代系统可靠性差 |
| I/O 端口读写 | ❌ 未封装 | Blade 风扇/EC 已走 HID，优先级低 |
| `Cpuid` / 按核亲和 MSR | ❌ 未单独封装（RAPL 写时绑 CPU0） | 可扩展监控 |
| 物理内存大块映射 | 部分经 `physmem.py` 备选路径 | 优先非 WinRing0 方案 |

---

## 3. 已接入、可被本工具使用的功能

### 3.1 自定义 CPU 功耗上限（RAPL MSR）— **核心写功能**

| 项目 | 说明 |
|------|------|
| MSR | `0x606` 单位、`0x610` Package Power Limit、`0x611` Energy Status |
| 功能 | 读/写 **PL1 / PL2 / Tau**；周期估算 Package 功耗 |
| 模块 | `app/backends/cpu_rapl.py` |
| UI/场景 | CPU 档为 **自定义** 时写入；后台与风扇后 `reassert` |
| 注意 | 固定 EC 档（低/均衡/增强）**不写** MSR PL；须同时保证 EC 不在 low |

**对本工具的价值**：用户自定义瓦数的唯一 MSR 路径；与 EC「增强」底档配合才有效。

### 3.2 Intel FIVR 降压（MSR 0x150）— **核心写功能**

| 项目 | 说明 |
|------|------|
| MSR | `0x150`（XTU / ThrottleStop 兼容 mailbox） |
| 功能 | Core / Cache / E-Cache 平面偏移（mV） |
| 模块 | `app/backends/cpu_undervolt.py` |
| 注意 | 与档位独立；休眠唤醒后常被清零，工具会重申；过深易蓝屏/不稳 |

**对本工具的价值**：降噪发热、抬频余量的主要 CPU 侧手段；不依赖雷云。

### 3.3 CPU 温度（DTS MSR）— **只读监控**

| 项目 | 说明 |
|------|------|
| MSR | `0x1A2` TjMax、`0x1B1` Package、`0x19C` 核心 |
| 功能 | 优先 Package 温度，失败回退核心 DTS / WMI |
| 模块 | `app/backends/temps.py` |
| 用途 | Live、托盘、软件风扇曲线温度输入 |

**对本工具的价值**：无第三方传感器 DLL 时的 CPU 温源；风扇曲线依赖其稳定性。

### 3.4 Package 功耗采样 — **只读监控**

基于 `0x611` 能量差分换算瓦数，供 Live「CPU 功耗」与 OSD。  
**价值**：验证自定义 PL / EC 是否真的卡住功耗（例如卡在 ~55W）。

### 3.5 PCI + 物理内存读 MMIO RAPL — **辅助、非必须**

通过 Host Bridge PCI 读 MCHBAR，再读 `MCHBAR+0x59A0` 对照 MSR。  
**价值**：诊断「MSR 写了但芯片组侧更严」；失败不影响「EC boost + MSR」主策略。  
**限制**：VBS/现代内存保护下 WinRing0 物理读经常不可用；`physmem.py` 会尝试其它驱动。

---

## 4. 适合扩展、且与本工具产品定位匹配的功能

按「收益 / 风险 / 与 EC 冲突」排序，建议只考虑下列增量。

### 4.1 高优先级（只读诊断，低风险）

| 候选功能 | 实现思路 | 对用户的用处 |
|----------|----------|--------------|
| 节流/热状态读回 | 解析 `IA32_THERM_STATUS` / Package 热状态位 | 区分「PL 限制 / 温度限制 / 电流限制」 |
| PL 锁定位显示 | 读 `0x610` lock 及相关位 | 解释为何写不进 PL |
| RAPL 多域只读 | 读 DRAM/平台等相关状态（若平台暴露） | 高级 Live 面板 |
| 按逻辑核温度 | 设亲和后读 `0x19C` | 热点核、曲线更稳 |

### 4.2 中优先级（写，需与现有策略一致）

| 候选功能 | 说明 | 风险 |
|----------|------|------|
| PL4 / 短时尖峰相关 MSR（若平台支持） | 补充自定义档精细控制 | 机型差异大；可能被 EC 盖掉 |
| 降压平面扩展（如 iGPU plane） | `0x150` 其它 plane | 笔记本核显+独显行为不一 |
| 休眠/插拔后自动校验并重申 | 已有骨架，可加强观测 | 低 |

### 4.3 低优先级或不推荐作为本工具主功能

| 能力 | 原因 |
|------|------|
| 直接改 CPU 倍率 / Turbo 表 | 与 BIOS/雷云/EC 强冲突，稳定性差 |
| I/O 端口操作 EC 风扇 | 本机已用 HID；重复且易砖固件策略 |
| 写 PCI/MMIO「解锁」功耗 | 安全与兼容性差；杀软敏感 |
| 通用内存/外设调试 | 超出 Blade 调优产品范围 |

---

## 5. 明确不应由 WinRing0 承担的功能

下列功能 **应由 HID/EC 或其它模块** 完成，WinRing0 无法可靠替代：

1. **GPU 功耗档 / 风扇自动·最大·手动 RPM / 软件曲线写转速**  
2. **把 EC CPU 从 low 抬回均衡/增强**（须 `set_cpu_boost` 等 HID）  
3. **绕过 EC 后单独让 MSR PL「看起来生效」**（EC 更严时无效）  
4. **AMD 平台 CPU PL / 降压**  
5. **无管理员或驱动被拦截时的任何 MSR 功能**

---

## 6. 与现有功能模块的映射（速查）

```text
WinRing0
├── CpuRaplBackend      → 自定义 PL1/PL2/Tau、Package 功耗、MMIO 对照
├── CpuUndervoltBackend → Core/Cache/E-Cache 降压
├── TempMonitor         → CPU Package/核心温度（风扇曲线、Live）
└──（可选 PhysMem）     → MMIO；WinRing0 物理读失败时降级

Synapse / HID
├── CPU/GPU EC 档
├── 风扇 auto/max/manual
└── 软件曲线写 RPM + preserve_ec_limits（钉住 EC，避免 MSR「假失效」）
```

---

## 7. 结论（给产品/开发）

**本工具真正「用得上」的 WinRing0 能力，集中在 Intel MSR：**

1. **写**：自定义 Package 功耗上限、FIVR 降压  
2. **读**：温度、能量/功耗、（可选）MMIO/锁定位诊断  

扩展应以 **只读诊断与现有写路径加固** 为主；不要把风扇、GPU 档、EC 策略迁到 WinRing0。  
评估新功能时用两条标准：

- 是否在 **Intel + 管理员 + 驱动可用** 前提下稳定？  
- 是否会与 **EC/雷云** 抢同一限制维度（若会，必须同时设计 EC 钉住或明确告知用户「以更严者为准」）？

---

## 8. 实现可能性评估（当前 + 候选）

评分说明：

| 等级 | 含义 |
|------|------|
| **已落地** | 代码已有，本机（Intel Blade）可用 |
| **高** | 现有封装足够，1～2 天量级可加，风险低 |
| **中** | 技术可行，但机型/固件差异或与 EC 冲突，需实机验证 |
| **低** | 能试，但成功率/稳定性差，不建议作主功能 |
| **不可行** | 在本工具目标场景下基本做不到或应由别通路做 |

### 8.1 WinRing0 路径

| 功能 | 可能性 | 说明 |
|------|--------|------|
| 自定义 PL1/PL2/Tau | **已落地** | `CpuRaplBackend`；须 EC≠low 才「有效」 |
| Core/Cache/E-Cache 降压 | **已落地** | `0x150`；休眠后重申已有 |
| Package 温度 / 功耗读 | **已落地** | Live、OSD、风扇曲线 |
| MMIO RAPL 对照读 | **已落地（尽力）** | VBS 下常失败；失败可忽略 |
| PL 锁定位 / 写回校验 UI | **高** | 已在读 `0x610`；补展示与「写失败原因」即可 |
| 热/节流原因位（PROCHOT、限功率等） | **高** | 解析已有 THERM MSR 位；只读 |
| 按逻辑核温度 | **高** | 亲和掩码 + 循环读 `0x19C` |
| DRAM/其它 RAPL 域只读 | **中** | 看 HX 平台是否暴露；读不到就隐藏 |
| 休眠/插电后更强校验提示 | **高** | `ResumeWatcher` + `reassert` 已有，补状态文案 |
| PL4 / 尖峰相关写 | **中→低** | 寄存器因代际而异；易被 EC/BIOS 盖掉 |
| iGPU 降压平面 | **中** | mailbox 能写，独显本收益不明、易副作用 |
| 改倍率 / Turbo / 锁核 | **低** | 与 EC/雷云抢控制，易不稳；偏离产品定位 |
| 物理内存写解锁功耗 | **低** | 现代 Win11 常失败；安全与误报风险高 |
| I/O 端口控风扇/EC | **低 / 不建议** | HID 已覆盖；端口路径易与固件打架 |
| 无管理员用 MSR | **不可行** | 驱动加载硬门槛 |
| AMD 上同款 PL/降压 | **不可行（本路径）** | 需别的方案，见 §9 |

### 8.2 关键结论（WinRing0）

- **值得继续做的**：只读诊断（锁定位、节流原因、分核温度）+ 现有写路径的可观测性。  
- **谨慎做的**：额外功耗 MSR 写入（PL4 等）。  
- **不要做的**：用 WinRing0 替代 HID 风扇/GPU/EC 档。

---

## 9. 通过其他通路可实现的功能

下列能力 **不依赖或不仅依赖 WinRing0**，对本工具同样有意义。

### 9.1 雷蛇 HID / EC（已是主通路）

| 功能 | 可能性 | 状态 / 备注 |
|------|--------|-------------|
| CPU 档 low～boost | **已落地** | `set_cpu_boost` |
| GPU 档 low/med/high | **已落地** | 约 100/150/≥175W（本机参考） |
| 风扇 auto / max / 手动 RPM | **已落地** | Custom 写转速会冲 EC → 已有 `preserve_ec_limits` |
| 软件双区风扇曲线 | **已落地** | 温源可 MSR 或 WMI |
| 读回 EC 档 / 转速 / 部分遥测 | **已落地** | Live `EC_CPU` / `EC_GPU` |
| 更多 EC 性能模式/键盘灯等 | **中** | 视 HID 报表是否已逆向；非功耗主线 |
| 「真正的」逐瓦 GPU TDP | **不可行（本机）** | README：本机无法用 smi/AB 写绝对 GPU 瓦 |

### 9.2 NVIDIA / 系统侧（监控为主）

| 功能 | 通路 | 可能性 | 备注 |
|------|------|--------|------|
| GPU 温度 | nvidia-smi / NVAPI / 现有探测 | **已落地或高** | 风扇曲线 GPU 温 |
| GPU 利用率、显存、功耗读数 | nvidia-smi / NVAPI | **高** | 只读进 Live/OSD；不替代 EC GPU 档 |
| 强制 P-State / 锁频 | NVAPI | **中→低** | 笔记本驱动常限制；易与雷云冲突 |
| 写 GPU 功率上限（瓦） | NVAPI / AB | **低 / 本机不可行** | 与产品结论一致：只能 EC 三档 |

### 9.3 MSI Afterburner（可选依赖）

| 功能 | 可能性 | 备注 |
|------|--------|------|
| 静默切换 AB Profile | **已落地** | `-ProfileN`，不写绝对 TDP |
| RTCore 物理内存（MMIO 后备） | **已落地（可选）** | `physmem.py` |
| 替代本工具做完整调校 | — | 外部工具；本工具只做联动 |

### 9.4 Windows / 无驱动能力

| 功能 | 通路 | 可能性 | 备注 |
|------|------|--------|------|
| CPU 温度回退 | WMI 热区 | **已落地** | MSR 失败时用 |
| 电源计划 / 插电休眠策略 | powercfg / API | **高** | 与档位联动「省电/高性能」 |
| 开机自启、热键、托盘、OSD | 现有 | **已落地** | 不依赖 WinRing0 |
| 休眠唤醒重申 | `ResumeWatcher` | **已落地** | 降压/PL/EC |
| 电池/适配器状态 | Win32 API | **高** | 可做「仅插电允许自定义高 PL」 |
| 进程规则自动切档 | 进程监视 | **中** | 产品化成本在策略与误切，不在驱动 |

### 9.5 明确不适合再找「第三通路」硬做的

| 诉求 | 原因 |
|------|------|
| 绕过 EC 把整机功耗抬过固件墙 | 固件/供电硬限制；改 MSR 或 NVAPI 都抬不动 |
| 无 HID 时完整控风扇与 GPU 档 | Blade 策略在 EC；无 Razer HID 则本工具 GPU/风扇模块不可用 |
| 用普通用户权限改 PL/降压 | 必须 Ring0 |

---

## 10. 综合优先级建议（若继续迭代）

| 优先级 | 做什么 | 通路 |
|--------|--------|------|
| P0 维持 | EC 钉住 + 自定义 PL + 降压 + 曲线（现状） | HID + WinRing0 |
| P1 | Live：PL 锁定位、节流原因、写回是否漂移 | WinRing0 只读 |
| P2 | Live/OSD：GPU 功耗/利用率只读 | nvidia-smi/NVAPI |
| P2 | 插电/电池策略门闩（高 PL 仅 AC） | Windows API + 现有档位 |
| P3 | 分核温度、DRAM RAPL 只读 | WinRing0 |
| 暂缓 | PL4、倍率、NV 锁频、I/O 控 EC | 冲突多、收益不确定 |

---

## 11. 相关代码与文档

| 路径 | 内容 |
|------|------|
| `app/backends/winring0.py` | DLL 加载、MSR/PCI/物理内存封装 |
| `app/backends/cpu_rapl.py` | PL / 功耗 |
| `app/backends/cpu_undervolt.py` | 降压 |
| `app/backends/temps.py` | 温度 |
| `app/backends/physmem.py` | 物理内存备选 |
| `app/backends/synapse_gpu.py` | HID EC / 风扇 / GPU 档 |
| `app/backends/gpu_nvapi_probe.py` | NVAPI 探测 |
| `vendor/winring0/README_VENDOR.md` | 二进制放置说明 |
| `tests/MANUAL_FAN_EC_CHECKLIST.txt` | EC 掉档与功耗实机核对 |

*文档对应代码状态：以仓库当前实现为准；WinRing0 第三方许可与风险自负，见项目 README 免责声明。*
