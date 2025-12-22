# STM8 Bootloader Template Project

## Overview

This project provides a flexible bootloader implementation for STM8 microcontrollers using the SDCC compiler. The bootloader resides in the option bytes reserved area and enables in-application programming (IAP) capabilities via UART communication.

Note: The bootloader implementation is based on and inspired by the [STM8uLoader](https://github.com/ovsp/STM8uLoader) project, with significant modifications and enhancements for integration into this template structure.

## Features

- **Three-stage Bootloader**:
  - Boot0: Reset/TRAP isr for load boot1
  - Boot1: Minimal bootloader stored in *reserved* option bytes
  - Boot2: Full-featured bootloader loaded via serial communication
  
- **Flexible Configuration**: 
  - Enable/disable bootloader via `ENABLE_OPTION_BOOTLOADER` Makefile macro
  
- **Complete Toolchain**:
  - PC-side programming utility for firmware updates
  - Support for read, write, go and exec operations
  
- **Safe Operation**:
  - Bootloader integrity protected in option bytes
  - Fallback to application on timeout or communication failure

## Bootloader Reference

This project's bootloader implementation is derived from the excellent STM8uLoader project by ovsp. Key adaptations include:

- Integration into a modular template project structure
- Three-stage bootloader approach (Boot1 in option bytes, Boot2 loaded dynamically)
- Enhanced Makefile system with configuration macros
- Extended command set and error handling

## Bootloader Operation Flow

1. **Power-on/Reset**:
   - MCU starts execution at reset vector(0x8000)
   - Control transfers to `bootloader_enter()`
   
2. **Stage 1 (Boot1)**:
   - Copies Boot1 from option bytes (0x480E-0x483F) to RAM and Run
   - Sends synchronization sequence `0x00 0x0D` via UART
   - Waits for PC to send Boot2 code
   
3. **Stage 2 (Boot2)**:
   - Receives and validates Boot2 code from PC
   - Executes Boot2 which provides full command interface
   - Processes PC commands for programming, reading, and device control

4. **Application Start**:
   - On successful programming or timeout, jumps to main application(0x8004)
   - Option to stay in bootloader mode for debugging

## Bootloader Integration

1. The main application includes `bootloader.h`, which redirects the TRAP interrupt vector to `bootloader_enter()` in `bsp/boot0.c`.

2. During the build process, the Makefile swaps the reset vector (0x8000) and trap vector (0x8004) positions. This ensures that upon startup, the bootloader entry routine executes first.

3. It sends a handshake signal (`0x00 0x0D`) via UART1 and waits approximately 200ms for a response. Within the timeout period, execution proceeds to the main application.

## Building the Project

### Prerequisites
- SDCC (Small Device C Compiler) installed
- stm8flash or similar programming tool
- Python 3.x (for PC tools)

### Compilation Options

Enable bootloader support:
```bash
make ENABLE_OPTION_BOOTLOADER=1
```

Disable bootloader (direct application execution):
```bash
make ENABLE_OPTION_BOOTLOADER=0
```

### Build Targets
```bash
# Build both application and bootloader option
make all

# Program device (requires stm8flash)
make flash
```

## Option Bytes Configuration

The bootloader uses the reserved option byte area for storage:

| Address Range | Content                  | Size  |
|---------------|--------------------------|-------|
| 0x4800-0x480A | Device option bytes      | 11 bytes |
| 0x480D-0x483F | Boot1 code               | 51 bytes |

**Important**: These addresses are specific to STM8S103/003. Adjust for other STM8 variants.

## PC Communication Protocol

### Connection Parameters
- **Baud Rate**: 128000 bps
- **Data Bits**: 8
- **Parity**: None
- **Stop Bits**: 1

### Command Set
| Command   | Opcode | Description                          |
|-----------|--------|--------------------------------------|
| CMD_READ  | 0xF1   | Read memory from device              |
| CMD_WRITE | 0xF2   | Write memory to device               |
| CMD_GO    | 0xF3   | Jump address for execution           |
| CMD_EXEC  | 0xF4   | Execute Machine-Code                 |

### Communication Sequence
1. Boot1 sends sync bytes: `0x00 0x0D`
2. PC responds with Boot2 reversed bytes
3. Boot1 receves Boot2 and checksum
4. Boot2 executes and prepare to receive cmd
5. PC sends commands with appropriate parameters

## Usage Example

### Programming New Firmware
```bash
# 1. Build the application
make flash

# 2. Enter interactive mode
python scripts/stm8loader.py /dev/ttyUSB0

# 3. Use command line:
python scripts/stm8loader.py /dev/ttyUSB0 --write 0x8000 firmware.bin
```

## Supported Devices

Currently tested with:
- STM8S103/003 (default configuration)

**Important**: To port to other STM8 variants need verify peripheral register definitions

## Troubleshooting

### Common Issues

1. **No response from device**:
   - Verify baud rate settings
   - Check UART pin connections (TX/RX swapped?)
   - Ensure option bytes are correctly programmed

2. **Bootloader not starting**:
   - Verify `ENABLE_OPTION_BOOTLOADER` is set during compilation
   - Check main.c include `bootloader.h`
   - Check `bsp/boot0.c`
   - Confirm option bytes

## Safety Considerations

1. **Power Stability**: Ensure stable power supply during programming
2. **Watchdog Timer**: Disable or properly handle watchdog in bootloader
3. **Interrupts**: Save/restore interrupt context during bootloader operations
4. **Memory Protection**: Never overwrite bootloader area in option bytes

## References

- [STM8uLoader](https://github.com/ovsp/STM8uLoader)
- [STM8S Reference Manual](https://www.st.com/resource/en/reference_manual/cd00190271-stm8s-series-and-stm8af-series-8bit-microcontrollers-stmicroelectronics.pdf)
- [SDCC User Guide](http://sdcc.sourceforge.net/doc/sdccman.pdf)
- [STM8 Bootloader AN2659](https://www.st.com/resource/en/application_note/cd00173937-stm8-swim-communication-protocol-and-debug-module-stmicroelectronics.pdf)
- [STM8 CPU programming manual](https://www.st.com/resource/en/programming_manual/cd00161709-stm8-cpu-programming-manual-stmicroelectronics.pdf)

---

**Note**: This implementation is for educational and development purposes. Always verify bootloader behavior in your specific application context before deployment.
