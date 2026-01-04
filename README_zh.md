# STM8 Bootloader 模板项目

([English](README.md) | 中文)

## 概述

本项目为 STM8 微控制器提供了一个灵活的 Bootloader 实现，使用 SDCC 编译器进行编译。Bootloader 存储在选项字节保留区域，支持通过 UART 通信进行在应用编程（IAP）功能。

注意：本 Bootloader 实现基于并受 [STM8uLoader](https://github.com/ovsp/STM8uLoader) 项目的启发，为了集成到本模板结构中进行了重大修改和增强。

## 特性

- **三阶段 Bootloader**：
  - Boot0：用于加载 Boot1 的复位/TRAP 中断服务程序
  - Boot1：存储在选项字节保留区的最小化 Bootloader
  - Boot2：通过串口通信加载的完整功能 Bootloader

- **灵活配置**：
  - 通过 Makefile 宏 `ENABLE_OPTION_BOOTLOADER` 启用/禁用 Bootloader

- **完整工具链**：
  - PC 端编程工具，支持固件更新
  - 支持读、写、跳转和执行操作

- **安全操作**：
  - Bootloader 完整性受选项字节保护
  - 超时或通信失败时回退到主应用程序

## Bootloader 参考

本项目的 Bootloader 实现源自 ovsp 开发的优秀 STM8uLoader 项目。主要改进包括：

- 集成到模块化的模板项目结构中
- 三阶段 Bootloader 方法（Boot1 在选项字节中，Boot2 动态加载）
- 增强的 Makefile 系统和配置宏
- 扩展的命令集和错误处理

## Bootloader 操作流程

1. **上电/复位**：
   - MCU 从复位向量（0x8000）开始执行
   - 控制权转移到 `bootloader_enter()`

2. **阶段 1（Boot1）**：
   - 从选项字节（0x480E-0x483F）复制 Boot1 到 RAM 并运行
   - 通过 UART 发送同步序列 `0x00 0x0D`
   - 等待 PC 端发送 Boot2 代码

3. **阶段 2（Boot2）**：
   - 接收并验证来自 PC 的 Boot2 代码
   - 执行 Boot2，提供完整的命令接口
   - 处理 PC 端的编程、读取和设备控制命令

4. **应用程序启动**：
   - 在成功编程或超时后，跳转到主应用程序（0x8004）
   - 可选择停留在 Bootloader 模式进行调试

## Bootloader 集成

1. 主应用程序包含 `bootloader.h`，该文件将 TRAP 中断向量重定向到 `bsp/boot0.c` 中的 `bootloader_enter()`。

2. 在构建过程中，Makefile 交换复位向量（0x8000）和陷阱向量（0x8004）的位置。这确保启动时首先执行 Bootloader 入口程序。

3. 它通过 UART1 发送握手信号（`0x00 0x0D`）并等待约 200ms 获取响应。在超时期限内，执行流程将进入主应用程序。

## 项目构建

### 先决条件
- 已安装 SDCC（Small Device C 编译器）
- stm8flash 或类似的编程工具
- Python 3.x（用于 PC 端工具）

### 编译选项

启用 Bootloader 支持：
```bash
make ENABLE_OPTION_BOOTLOADER=1
```

禁用 Bootloader（直接执行应用程序）：
```bash
make ENABLE_OPTION_BOOTLOADER=0
```

### 构建目标
```bash
# 构建应用程序和 Bootloader 选项
make all

# 编程设备（需要 stm8flash）
make flash
```

## 选项字节配置

Bootloader 使用保留的选项字节区域进行存储：

| 地址范围      | 内容                     | 大小      |
|--------------|--------------------------|-----------|
| 0x4800-0x480A | 设备选项字节              | 11 字节   |
| 0x480D-0x483F | Boot1 代码                | 51 字节   |

**重要提示**：这些地址是针对 STM8S103/003 的。对于其他 STM8 型号需要相应调整。

## PC 通信协议

### 连接参数
- **波特率**：128000 bps
- **数据位**：8
- **校验位**：无
- **停止位**：1

### 命令集
| 命令        | 操作码  | 描述                          |
|------------|---------|-------------------------------|
| CMD_READ   | 0xF1    | 从设备读取内存                |
| CMD_WRITE  | 0xF2    | 向设备写入内存                |
| CMD_GO     | 0xF3    | 跳转到指定地址执行            |
| CMD_EXEC   | 0xF4    | 执行机器码                    |

### 通信序列
1. Boot1 发送同步字节：`0x00 0x0D`
2. PC 响应 Boot2 反向字节
3. Boot1 接收 Boot2 并校验和
4. Boot2 执行并准备接收命令
5. PC 发送带有适当参数的命令

## 使用示例

### 编程新固件
```bash
# 1. 构建应用程序
make flash

# 2. 进入交互模式
python scripts/stm8loader.py /dev/ttyUSB0

# 3. 使用命令行：
python scripts/stm8loader.py /dev/ttyUSB0 --write 0x8000 firmware.bin
```

## 支持的设备

当前已测试：
- STM8S103/003（默认配置）

**重要提示**：移植到其他 STM8 型号需要验证外设寄存器定义

## 故障排除

### 常见问题

1. **设备无响应**：
   - 验证波特率设置
   - 检查 UART 引脚连接（TX/RX 是否接反？）
   - 确保选项字节已正确编程

2. **Bootloader 未启动**：
   - 验证编译时是否设置了 `ENABLE_OPTION_BOOTLOADER`
   - 检查 main.c 是否包含 `bootloader.h`
   - 检查 `bsp/boot0.c`
   - 确认选项字节配置

## 安全注意事项

1. **电源稳定性**：确保编程期间电源稳定
2. **看门狗定时器**：在 Bootloader 中禁用或正确处理看门狗
3. **中断**：在 Bootloader 操作期间保存/恢复中断上下文
4. **内存保护**：切勿覆盖选项字节中的 Bootloader 区域

## 参考资料

- [STM8uLoader](https://github.com/ovsp/STM8uLoader)
- [STM8S 参考手册](https://www.st.com/resource/en/reference_manual/cd00190271-stm8s-series-and-stm8af-series-8bit-microcontrollers-stmicroelectronics.pdf)
- [STM8 CPU 编程手册](https://www.st.com/resource/en/programming_manual/cd00161709-stm8-cpu-programming-manual-stmicroelectronics.pdf)
- [SDCC 用户指南](http://sdcc.sourceforge.net/doc/sdccman.pdf)
- [STM8 Bootloader AN2659](https://www.st.com/resource/en/application_note/cd00173937-stm8-swim-communication-protocol-and-debug-module-stmicroelectronics.pdf)

---

**注意**：本实现用于教育和开发目的。在部署前，请务必在您的具体应用场景中验证 Bootloader 行为。
