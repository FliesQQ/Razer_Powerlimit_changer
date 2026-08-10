# BladePower — Razer Blade 16 power / fan / undervolt switcher

[中文说明](README.md) | **English**

Windows utility for **Razer Blade 16 (RZ09-0483, i9-13950HX + RTX 4090 Laptop)**: switch custom performance profiles via GUI, global hotkeys, and tray. Supports Synapse-like CPU/GPU tiers, optional custom PL1/PL2, software fan curves, and global undervolt.

> **Administrator rights required** (CPU MSR / WinRing0). Validate power and temperatures gradually; excessive limits or deep undervolt may cause overheating or instability.

In the app, switch language with **UI language → 中文 / English** on the Home tab (saved as `settings.ui_language` in `profiles.json`).

---

## Features

| Module | Description | Default |
|--------|-------------|---------|
| **CPU tier** | Synapse-like Low / Med / High / Boost; **Custom** writes PL1/PL2/Tau | On |
| **GPU tier** | Synapse-like Low / Med / High (HID) | On |
| **CPU undervolt** | Core / Cache / E-Cache (MSR 0x150), independent of tier | On |
| **Fan curves** | Dual-zone RPM from CPU/GPU temps (mutex with profile fans) | Off (enable on tab) |
| **Auto brightness** | AC vs battery brightness; optional lock / OLED floor | Off (enable on tab) |
| **Hotkeys / tray / OSD** | Global hotkeys, tray, optional desktop overlay | — |
| **Autostart** | Silent tray after login; re-apply last profile / undervolt | Optional |
| **Resume restore** | Re-assert undervolt (and power if Custom) after sleep/hibernate | Auto |
| **Afterburner** | Optional silent `-ProfileN` (does not write absolute GPU TDP) | Optional |

Toggle modules independently under **Feature modules** on Home.

---

## CPU tier behavior

| CPU tier | Behavior |
|----------|----------|
| **Low / Med / High / Boost** | EC only (Synapse Custom slider equivalent); **no** PL1/PL2 |
| **Custom** | EC floor = Boost, then write **PL1 / PL2 / Tau** (MSR) |

Undervolt stays independent of CPU tier.

> If GPU changes leave CPU stuck near ~55W, EC likely fell to low after entering Custom. Turn on CPU tier and pick Boost/High, or use Custom + suitable PL.

---

## GPU tiers (measured on this machine)

| GPU | Approx GPU cap | Approx system peak |
|-----|----------------|--------------------|
| Low | ~100 W | ~160 W |
| Med | ~150 W | ~180 W |
| High | ≥175 W | ~205 W |

Absolute GPU watts via `nvidia-smi` / Afterburner are **not** available on this chassis.

---

## Requirements

- Windows 10 / 11 **x64**
- **Admin** rights
- Source run: Python 3.10+ (3.11/3.13 recommended)
- `WinRing0x64.dll` + `WinRing0x64.sys` under `vendor/winring0/`
- GPU/fans: Razer HID (Synapse-compatible). Fully quit Synapse if HID conflicts

---

## Install (source)

```bat
cd /d F:\source_code\Power_limit_change
py -3 -m pip install -r requirements.txt
run_as_admin.bat
```

Or: `py -3 -m app.main` (will request UAC if needed).

---

## Build exe

Run `build_exe.bat`. Output: `dist\BladePower_Release\` (exe + WinRing0 + README.md / README.en.md). Run **as Administrator**.

Config: `profiles.json` next to the exe (source uses repo root). Do not mix the two copies.

---

## Notes

1. Effective power is often the stricter of EC vs MSR; fixed tiers skip MSR PL; Custom writes MSR.
2. Avoid fighting Synapse CPU OC / Intel XTU on the same PL registers.
3. HID timeouts may show last good EC values marked `(缓存)` / cache.
4. WinRing0 may trigger AV false positives — whitelist the folder.
5. Use at your own risk; `Ctrl+Alt+0` restores safe defaults.

---

## License / disclaimer

Personal learning and tuning. Author is not liable for hardware damage. Third-party drivers (e.g. WinRing0) retain their own licenses.
