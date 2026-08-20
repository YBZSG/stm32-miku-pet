# STM32 Miku Pet

基于 STM32F103ZE 的初音未来桌面宠物。项目将 ILI9341 触摸屏动画、ESP8266 Wi-Fi 仪表盘、VS1053 语音播放和 Windows Web 控制台组合在一起，可显示任务状态、天气、留言与番茄钟，并通过网页控制宠物动作和语音。

## 功能

- 11 种宠物状态：待机、左右奔跑、挥手、跳跃、失败、等待、工作、审查和左右凝视
- ILI9341 LCD 动画显示与 XPT2046 触摸交互
- AI 状态、天气、留言板、极客信息四种仪表盘模式
- ESP8266 自动波特率探测、Wi-Fi 入网和 UDP 数据接收
- VS1053 播放开机、工作、等待、失败、完成五类语音
- Windows Web 控制台，可切换状态、模式、语音并发送留言
- 支持从本机任务记录提取状态，并向设备发送完整仪表盘快照
- 配套动画转换、资源上传、语音包制作和串口上传工具

## 硬件与软件

### 硬件

- STM32F103ZE 开发板
- ILI9341 2.8/3.2 英寸 TFT LCD
- XPT2046 电阻触摸控制器
- W25Q64 SPI Flash
- ESP8266 Wi-Fi 模块（USART3）
- VS1053 音频模块
- 可选：HC-05 蓝牙模块、雷达传感器

工程中的 LCD 引脚按野火 F103 霸道开发板配置。其他开发板需要修改 `miku_pet/User/lcd`、`flash`、`audio`、`wifi` 等目录中的 GPIO 定义。

### 软件

- Keil MDK-ARM，工程当前使用 ARM Compiler 5
- Python 3.9 或更高版本
- Windows 10/11
- 串口工具依赖：`pyserial`
- 动画转换工具依赖：`Pillow`

安装 Python 依赖：

```powershell
python -m pip install pyserial pillow
```

## 目录结构

```text
.
├─ miku_monitor.py             # Windows Web 控制台与 UDP 发送端
├─ run_monitor.bat             # 启动控制台
├─ upload_voice.bat            # 自动探测串口并上传语音包
├─ miku_pet/
│  ├─ Project/RVMDK（uv5）/    # Keil 工程
│  ├─ User/                    # STM32 应用与各硬件驱动
│  ├─ Libraries/               # STM32F10x CMSIS/标准外设库
│  ├─ assets/                  # 动画包、语音包及源音频
│  └─ tools/                   # 转换、上传与状态桥接工具
└─ *.bat / *.vbs               # Windows 服务与开机启动脚本
```

## 快速开始

### 1. 配置 Wi-Fi

创建以下文件：

```text
miku_pet/User/pet_wifi_config.h
```

参考格式：

```c
#ifndef __PET_WIFI_CONFIG_H
#define __PET_WIFI_CONFIG_H

#define PET_WIFI_SSID     "你的 Wi-Fi 名称"
#define PET_WIFI_PASSWORD "你的 Wi-Fi 密码"

#endif
```

该文件已被 `.gitignore` 排除，请勿将真实 Wi-Fi 密码提交到仓库。建议使用 2.4 GHz Wi-Fi。

### 2. 编译并烧录固件

1. 使用 Keil 打开 `miku_pet/Project/RVMDK（uv5）/BH-F103.uvprojx`。
2. 选择 `LDC` Target。
3. 执行 Rebuild。
4. 将生成的固件烧录到 STM32F103ZE。

已验证的构建环境为 ARMCC 5.06 update 7。最近一次完整构建结果为 0 Error、0 Warning。

### 3. 上传动画资源

仓库已包含可直接上传的 `miku_pet/assets/miku_pet.bin`。需要替换动画时，可先从宠物图集重新生成资源包：

```powershell
python miku_pet/tools/convert_pet.py <atlas.png> miku_pet/assets/miku_pet.bin
```

然后按实际串口运行：

```powershell
powershell -ExecutionPolicy Bypass -File miku_pet/tools/upload_asset.ps1 -Port COM7
```

### 4. 制作并上传语音包

重新构建语音包：

```powershell
python miku_pet/tools/voice_manager.py --build
```

自动探测串口并上传：

```powershell
upload_voice.bat
```

也可以显式指定串口：

```powershell
python miku_pet/tools/upload_voice.py --port COM7
```

语音包写入 W25Q64 的 `0x200000` 区域。默认包含以下槽位：

| ID | 场景 | 文件 |
|---:|---|---|
| 0 | 工作中 | `working.wav` |
| 1 | 等待输入 | `waiting.wav` |
| 2 | 执行失败 | `failed.wav` |
| 3 | 执行完成 | `complete.wav` |
| 4 | 开机问候 | `boot.wav` |

### 5. 启动 Web 控制台

运行：

```powershell
run_monitor.bat
```

随后打开：

```text
http://localhost:18900
```

控制台默认通过 UDP `43210` 端口向局域网中的设备发送数据。如果 Windows 防火墙阻止通信，可以管理员身份运行：

```powershell
allow_firewall.bat
```

确保电脑和 ESP8266 位于同一局域网，并允许 UDP 广播。

## 通信说明

| 通道 | 默认值 | 用途 |
|---|---:|---|
| HTTP | `18900` | 本机 Web 控制台 |
| UDP | `43210` | PC 向 STM32 发送仪表盘快照 |
| USART1 | `115200` | 调试、资源和语音上传 |
| USART2 | `9600` | HC-05 蓝牙通信 |
| USART3 | 自动探测 | ESP8266 AT 指令与 UDP 数据 |

仪表盘数据带有会话 ID、递增序号和 CRC32。同一会话中的旧序号会被设备忽略，切换会话时则原子替换当前快照。更多说明见 [`miku_pet/tools/DASHBOARD_PROTOCOL.md`](miku_pet/tools/DASHBOARD_PROTOCOL.md)。

## 自定义宠物

`convert_pet.py` 可将 Codex v2 的 8 × 11 精灵图集转换为适合 STM32 流式读取的 RGB565 RLE 包：

```powershell
python miku_pet/tools/convert_pet.py <atlas.png> <output.bin> `
  --width 96 --height 104 --background F7F7F7
```

生成文件由 `MPET` 头、动画帧索引和压缩后的像素数据组成。透明像素会先与指定背景色合成。

## 注意事项

- `pet_wifi_config.h` 是本地私有配置，不在仓库中；首次编译前必须自行创建。
- `start_service.bat`、`start_silent.vbs` 和 `install_startup.bat` 目前仍包含原开发目录的绝对路径。使用开机自启前，请先将其中路径改为你的仓库实际位置。
- `stop_service.bat` 会结束匹配到的 Python/Pythonw 监控进程，执行前请确认没有需要保留的同名进程。
- 项目没有提交 Keil 的 `Output`、`Listing`、日志和本地用户配置，需要在本机重新构建。
- 仓库目前未声明开源许可证；在添加许可证前，默认保留全部权利。

## 相关文档

- [资源转换说明](miku_pet/tools/README.md)
- [仪表盘协议](miku_pet/tools/DASHBOARD_PROTOCOL.md)
- [LCD 与 STM32 接线表](miku_pet/3.2_2.8寸液晶与STM32接线方式.xlsx)
