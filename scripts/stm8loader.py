#!/usr/bin/env python3
"""
STM8 Bootloader 交互工具
支持自动检测并上传boot2程序，以及读写内存、执行等操作
"""

import sys
import os
import time
import struct
import argparse
import serial
from serial.tools import list_ports
from typing import Optional, List, Tuple, Union, BinaryIO

# ============ 协议常量定义 ============
CMD_READ = 0xF1      # 读内存命令
CMD_WRITE = 0xF2     # 写内存命令
CMD_GO = 0xF3        # 跳转执行命令

CMD_HEADER = 0x5A    # 发送给MCU的帧头
ACK_HEADER = 0xA5    # MCU应答的帧头

HANDSHAKE_ADDR = 0x8000  # 握手检测地址
HANDSHAKE_SIZE = 8       # 握手数据长度

BOOT1_BAUDRATE = 9600    # boot1波特率
BOOT2_BAUDRATE = 128000  # boot2波特率

FRAME_SIZE = 70          # 命令帧总大小
MAX_DATA_SIZE = 64       # 单次最大数据长度

class STM8BootloaderError(Exception):
    """STM8 Bootloader异常基类"""
    pass

class STM8Bootloader:
    def __init__(self, port: str, verbose: bool = False, reset_pin: str = 'rts'):
        """
        初始化STM8 Bootloader
        
        Args:
            port: 串口号
            verbose: 是否显示详细调试信息
            reset_pin: 复位引脚类型 ('rts', 'dtr' 或 'none')
        """
        self.port = port
        self.verbose = verbose
        self.reset_pin = reset_pin.lower()
        if self.reset_pin not in ['rts', 'dtr', 'none']:
            raise ValueError("reset_pin 必须是 'rts', 'dtr' 或 'none'")
        self.serial = None
        self.in_boot2 = False
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        
    def log(self, message: str, level: str = "INFO"):
        """
        打印日志信息
        
        Args:
            message: 日志消息
            level: 日志级别 (DEBUG, INFO, ERROR, WARNING)
        """
        if level == "DEBUG" and not self.verbose:
            return
            
        prefix = f"[{level}] {message}"
        print(prefix)
    
    def open(self, baudrate: int = BOOT2_BAUDRATE):
        """打开串口连接"""
        if self.serial is None or not self.serial.is_open:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0  # 设置为0，非阻塞模式
            )
            self.log(f"串口 {self.port} 已打开，波特率 {baudrate}", "DEBUG")
    
    def close(self):
        """关闭串口连接"""
        if self.serial and self.serial.is_open:
            self.serial.close()
            self.log("串口已关闭", "DEBUG")
    
    def reset_mcu(self) -> bool:
        """
        通过RTS或DTR复位MCU
        
        Returns:
            True: 复位成功, False: 复位失败或未配置
        """
        if self.reset_pin == 'none':
            self.log("未配置自动复位引脚，跳过自动复位", "INFO")
            return True
            
        if not self.serial or not self.serial.is_open:
            return False
        
        self.log(f"使用 {self.reset_pin.upper()} 引脚复位MCU...", "DEBUG")
        
        try:
            if self.reset_pin == 'rts':
                # RTS复位序列: True -> False -> True -> 等待150ms -> False
                self.serial.setRTS(True)
                time.sleep(0.01)  # 等待10ms稳定
                
                self.serial.setRTS(False)
                time.sleep(0.01)  # 等待10ms稳定
                
                self.serial.setRTS(True)
                time.sleep(0.15)  # 等待150ms，让MCU复位
                
                self.serial.setRTS(False)
            else:  # dtr
                # DTR复位序列: True -> False -> True -> 等待150ms -> False
                self.serial.setDTR(True)
                time.sleep(0.01)  # 等待10ms稳定
                
                self.serial.setDTR(False)
                time.sleep(0.01)  # 等待10ms稳定
                
                self.serial.setDTR(True)
                time.sleep(0.15)  # 等待150ms，让MCU复位
                
                self.serial.setDTR(False)
            
            # 等待MCU稳定
            time.sleep(0.05)
            self.log("MCU复位完成", "DEBUG")
            return True
            
        except Exception as e:
            self.log(f"复位失败: {e}", "ERROR")
            return False
    
    def wait_for_boot1_signal_and_send_boot2(self, bin_file: str) -> bool:
        """
        等待boot1的握手信号 (0x00 0x0D)，收到后立即发送boot2.bin
        
        Args:
            bin_file: boot2二进制文件路径
            
        Returns:
            True: 成功, False: 失败
        """
        if not self.serial or not self.serial.is_open:
            return False
        
        self.log("等待boot1握手信号(0x00 0x0D)...", "DEBUG")
        
        # 清除输入缓冲区
        self.serial.reset_input_buffer()
        
        try:
            # 持续读取，最多等待200ms
            start_time = time.time()
            buffer = bytearray()
            
            while time.time() - start_time < 0.2:  # 200ms超时
                # 读取所有可用数据
                if self.serial.in_waiting > 0:
                    data = self.serial.read(self.serial.in_waiting)
                    buffer.extend(data)
                    
                    # 检查是否有0x00 0x0D
                    if len(buffer) >= 2 and buffer[-2:] == b'\x00\x0d':
                        self.log("收到boot1握手信号: 0x00 0x0D", "DEBUG")
                        
                        # 立即发送boot2.bin
                        return self.send_boot2_binary(bin_file)
                
                # 短暂延时，避免CPU占用过高
                time.sleep(0.001)  # 1ms
            
            # 超时，未收到信号
            self.log("200ms内未收到boot1信号", "DEBUG")
            return False
            
        except Exception as e:
            self.log(f"等待boot1信号时出错: {e}", "ERROR")
            return False
    
    def wait_for_boot1_signal_blocking(self, bin_file: str) -> bool:
        """
        阻塞等待boot1的握手信号，直到收到并发送boot2或用户中断
        
        Returns:
            True: 成功, False: 用户中断或失败
        """
        self.log("等待boot1握手信号，请手动按下MCU复位键", "INFO")
        self.log("按 Ctrl+C 退出程序", "INFO")
        
        # 清除输入缓冲区
        self.serial.reset_input_buffer()
        
        try:
            while True:
                # 检查是否有数据
                if self.serial.in_waiting > 0:
                    data = self.serial.read(self.serial.in_waiting)
                    
                    # 简单检查：如果数据包含0x00 0x0D
                    if b'\x00\x0d' in data:
                        self.log("收到boot1握手信号: 0x00 0x0D", "INFO")
                        
                        # 立即发送boot2.bin
                        return self.send_boot2_binary(bin_file)
                
                # 短暂延时
                time.sleep(0.001)
                
        except KeyboardInterrupt:
            self.log("用户中断等待", "INFO")
            return False
        except Exception as e:
            self.log(f"等待时出错: {e}", "ERROR")
            return False
    
    def send_boot2_binary(self, bin_file: str) -> bool:
        """
        发送boot2.bin文件到MCU（字节倒序）
        
        Args:
            bin_file: boot2二进制文件路径
            
        Returns:
            True: 发送成功, False: 发送失败
        """
        try:
            # 如果文件路径不是绝对路径，则相对于脚本目录
            if not os.path.isabs(bin_file):
                bin_file = os.path.join(self.script_dir, bin_file)
            
            with open(bin_file, 'rb') as f:
                data = f.read()
            
            if not data:
                self.log(f"文件 {bin_file} 为空", "ERROR")
                return False
            
            self.log(f"读取到 {len(data)} 字节的boot2程序", "DEBUG")
            
            # 字节倒序
            reversed_data = bytes(reversed(data))
            
            # 发送数据（不添加校验和）
            self.serial.write(reversed_data)
            self.serial.flush()

            self.log(f"已发送 {len(data)} 字节 (倒序)", "DEBUG")
            return True
            
        except FileNotFoundError:
            self.log(f"文件不存在: {bin_file}", "ERROR")
            return False
        except Exception as e:
            self.log(f"发送boot2.bin时出错: {e}", "ERROR")
            return False
    
    def calculate_checksum(self, data: bytes) -> int:
        """计算XOR校验和"""
        checksum = 0
        for byte in data:
            checksum ^= byte
        return checksum
    
    def create_command_frame(self, cmd: int, addr: int, data: bytes = b'') -> bytes:
        """
        创建命令帧
        
        Args:
            cmd: 命令类型
            addr: 目标地址
            data: 数据内容
            
        Returns:
            完整的命令帧
        """
        if len(data) > MAX_DATA_SIZE:
            raise STM8BootloaderError(f"数据长度超过{MAX_DATA_SIZE}字节限制")
        
        # 构建帧
        frame = bytearray(FRAME_SIZE)
        frame[0] = CMD_HEADER                    # 帧头
        frame[1] = cmd                          # 命令类型
        frame[2] = (addr >> 8) & 0xFF          # 地址高字节
        frame[3] = addr & 0xFF                  # 地址低字节
        frame[4] = len(data)                    # 数据长度
        
        # 填充数据
        if data:
            frame[5:5+len(data)] = data
        
        # 计算校验和（从帧头到数据结束）
        checksum_data = frame[:5+len(data)]
        frame[5+len(data)] = self.calculate_checksum(checksum_data)
        
        return bytes(frame[:5+len(data)+1])
    
    def parse_response_frame(self, frame: bytes) -> Tuple[int, int, bytes]:
        """
        解析应答帧
        
        Args:
            frame: 接收到的帧数据
            
        Returns:
            (命令类型, 地址, 数据)
        """
        if len(frame) < 6:
            raise STM8BootloaderError("应答帧长度不足")
        
        if frame[0] != ACK_HEADER:
            raise STM8BootloaderError(f"无效的应答帧头: 0x{frame[0]:02X}")
        
        # 验证校验和
        received_checksum = frame[-1]
        calculated_checksum = self.calculate_checksum(frame[:-1])
        
        if received_checksum != calculated_checksum:
            raise STM8BootloaderError(f"校验和错误: 收到0x{received_checksum:02X}, 计算0x{calculated_checksum:02X}")
        
        cmd = frame[1]
        addr = (frame[2] << 8) | frame[3]
        data_len = frame[4]
        
        if len(frame) < 5 + data_len + 1:
            raise STM8BootloaderError("应答帧数据长度不匹配")
        
        data = frame[5:5+data_len]
        
        return cmd, addr, data
    
    def read_with_timeout(self, size: int, timeout: float) -> bytes:
        """
        读取指定数量的字节，带超时
        
        Args:
            size: 要读取的字节数
            timeout: 超时时间（秒）
            
        Returns:
            读取到的数据
        """
        data = bytearray()
        start_time = time.time()
        
        while len(data) < size and time.time() - start_time < timeout:
            if self.serial.in_waiting > 0:
                chunk = self.serial.read(min(self.serial.in_waiting, size - len(data)))
                data.extend(chunk)
            else:
                time.sleep(0.001)  # 短暂休眠，避免CPU占用过高
        
        return bytes(data)
    
    def send_command(self, cmd: int, addr: int, data: bytes = b'', 
                    wait_response: bool = True, timeout: float = 0.5) -> Optional[Tuple[int, int, bytes]]:
        """
        发送命令并接收响应
        
        Args:
            cmd: 命令类型
            addr: 目标地址
            data: 数据内容
            wait_response: 是否等待响应
            timeout: 超时时间
            
        Returns:
            解析后的响应帧，或None
        """
        if not self.serial or not self.serial.is_open:
            raise STM8BootloaderError("串口未打开")
        
        # 清除输入缓冲区
        self.serial.reset_input_buffer()
        
        # 创建并发送命令帧
        frame = self.create_command_frame(cmd, addr, data)
        self.serial.write(frame)
        self.serial.flush()
        
        if not wait_response:
            return None
        
        # 等待响应
        response = self.read_with_timeout(FRAME_SIZE, timeout)
        
        if not response:
            raise STM8BootloaderError("未收到响应")
        
        return self.parse_response_frame(response)
    
    def check_boot2(self) -> bool:
        """
        检查是否已经在boot2中
        
        Returns:
            True: 在boot2中, False: 不在boot2中
        """
        try:
            self.log("检查是否在boot2中...", "DEBUG")
            # 发送读取命令，数据字段为要读取的长度（8字节）
            response = self.send_command(CMD_READ, HANDSHAKE_ADDR, b'\x08', timeout=0.5)
            
            if response:
                cmd, addr, data = response
                if cmd == CMD_READ and addr == HANDSHAKE_ADDR and len(data) >= HANDSHAKE_SIZE:
                    self.in_boot2 = True
                    self.log("已在boot2中", "DEBUG")
                    return True
                    
        except STM8BootloaderError as e:
            self.log(f"不在boot2中: {e}", "DEBUG")
        except Exception as e:
            self.log(f"检查boot2时出错: {e}", "DEBUG")
        
        self.in_boot2 = False
        return False
    
    def upload_boot2(self, boot2_file: str = "boot2.bin") -> bool:
        """
        上传boot2程序到MCU
        
        Args:
            boot2_file: boot2二进制文件路径
            
        Returns:
            True: 上传成功, False: 上传失败
        """
        self.log("开始上传boot2程序...", "INFO")
        
        # 1. 切换到9600bps
        self.close()
        self.open(baudrate=BOOT1_BAUDRATE)
        time.sleep(0.05)  # 等待串口稳定
        
        # 2. 尝试复位MCU（如果配置了复位引脚）
        if self.reset_pin != 'none':
            if self.reset_mcu():
                self.log("自动复位MCU成功", "INFO")
            else:
                self.log("自动复位失败，继续尝试...", "WARNING")
        else:
            self.log("未配置自动复位，等待手动复位...", "INFO")
        
        # 3. 尝试自动等待并发送boot2（200ms窗口期）
        if self.reset_pin != 'none':
            self.log("尝试在200ms窗口期内接收boot1信号...", "INFO")
            if self.wait_for_boot1_signal_and_send_boot2(boot2_file):
                self.log("boot1信号接收成功，已发送boot2程序", "INFO")
            else:
                self.log("200ms窗口期内未收到boot1信号，请手动复位", "WARNING")
                
                # 手动复位等待
                if not self.wait_for_boot1_signal_blocking(boot2_file):
                    self.log("等待被用户中断", "ERROR")
                    return False
        else:
            # 直接等待手动复位
            if not self.wait_for_boot1_signal_blocking(boot2_file):
                self.log("等待被用户中断", "ERROR")
                return False
        
        # 4. 等待1s
        time.sleep(1)
        
        # 5. 切换到128000bps并检查是否在boot2中
        self.log("验证boot2程序...", "INFO")
        self.close()
        self.open(baudrate=BOOT2_BAUDRATE)
        time.sleep(0.05)  # 额外等待50ms稳定
        
        if self.check_boot2():
            self.log("boot2上传成功", "INFO")
            return True
        else:
            self.log("boot2上传后验证失败", "ERROR")
            return False
    
    def read_memory(self, addr: int, size: int) -> bytes:
        """
        读取内存
        
        Args:
            addr: 起始地址
            size: 读取大小
            
        Returns:
            读取到的数据
        """
        if not self.in_boot2:
            raise STM8BootloaderError("不在boot2模式中")
        
        result = bytearray()
        remaining = size
        current_addr = addr
        
        while remaining > 0:
            chunk_size = min(remaining, MAX_DATA_SIZE)
            
            try:
                # 发送读取命令，数据字段为要读取的长度
                response = self.send_command(CMD_READ, current_addr, 
                                           struct.pack('B', chunk_size))
                
                if not response:
                    raise STM8BootloaderError(f"读取地址 0x{current_addr:04X} 失败")
                
                cmd, resp_addr, data = response
                
                if cmd != CMD_READ or resp_addr != current_addr:
                    raise STM8BootloaderError(f"读取响应不匹配")
                
                if len(data) != chunk_size:
                    raise STM8BootloaderError(f"读取长度不匹配: 期望{chunk_size}, 实际{len(data)}")
                
                result.extend(data)
                remaining -= chunk_size
                current_addr += chunk_size
                
                self.log(f"已读取 0x{current_addr-chunk_size:04X} - 0x{current_addr-1:04X} ({chunk_size}字节)", "DEBUG")
                
            except Exception as e:
                raise STM8BootloaderError(f"读取过程中出错: {e}")
        
        return bytes(result)
    
    def write_memory(self, addr: int, data: bytes) -> bool:
        """
        写入内存
        
        Args:
            addr: 起始地址
            data: 要写入的数据
            
        Returns:
            True: 写入成功, False: 写入失败
        """
        if not self.in_boot2:
            raise STM8BootloaderError("不在boot2模式中")
        
        remaining = len(data)
        current_addr = addr
        offset = 0
        
        while remaining > 0:
            chunk_size = min(remaining, MAX_DATA_SIZE)
            chunk_data = data[offset:offset+chunk_size]
            
            try:
                response = self.send_command(CMD_WRITE, current_addr, chunk_data)
                
                if not response:
                    raise STM8BootloaderError(f"写入地址 0x{current_addr:04X} 失败")
                
                cmd, resp_addr, resp_data = response
                
                if cmd != CMD_WRITE or resp_addr != current_addr:
                    raise STM8BootloaderError(f"写入响应不匹配")
                
                self.log(f"已写入 0x{current_addr:04X} - 0x{current_addr+chunk_size-1:04X} ({chunk_size}字节)", "DEBUG")
                
                remaining -= chunk_size
                current_addr += chunk_size
                offset += chunk_size
                
            except Exception as e:
                raise STM8BootloaderError(f"写入过程中出错: {e}")
        
        return True
    
    def go_execute(self, addr: int) -> bool:
        """
        跳转到指定地址执行
        
        Args:
            addr: 执行地址
            
        Returns:
            True: 命令发送成功
        """
        if not self.in_boot2:
            raise STM8BootloaderError("不在boot2模式中")
        
        try:
            # go命令不需要等待响应
            self.send_command(CMD_GO, addr, b'', wait_response=False)
            self.log(f"已发送跳转到 0x{addr:04X} 的命令", "DEBUG")
            return True
        except Exception as e:
            raise STM8BootloaderError(f"发送跳转命令失败: {e}")
    
    def get_info(self) -> dict:
        """
        获取MCU信息
        
        Returns:
            包含MCU信息的字典
        """
        if not self.in_boot2:
            raise STM8BootloaderError("不在boot2模式中")
        
        try:
            data = self.read_memory(HANDSHAKE_ADDR, HANDSHAKE_SIZE)
            
            if len(data) < HANDSHAKE_SIZE:
                raise STM8BootloaderError("信息数据长度不足")
            
            # 解析握手数据
            boot0_addr = (data[1] << 8) | data[0]  # 注意字节序
            main_addr = (data[7] << 8) | data[6]    # 注意字节序
            
            info = {
                'boot0_address': boot0_addr,
                'main_program_address': main_addr,
                'raw_data': data.hex(' '),
                'in_boot2': self.in_boot2
            }
            
            return info
            
        except Exception as e:
            raise STM8BootloaderError(f"获取信息失败: {e}")
    
    @staticmethod
    def list_directory(path: str = "."):
        """列出目录内容"""
        try:
            items = os.listdir(path)
            
            # 分离目录和文件
            dirs = []
            files = []
            
            for item in items:
                full_path = os.path.join(path, item)
                if os.path.isdir(full_path):
                    dirs.append(item + "/")
                else:
                    files.append(item)
            
            # 排序
            dirs.sort()
            files.sort()
            
            # 显示
            print(f"目录: {os.path.abspath(path)}")
            print()
            
            if dirs or files:
                # 显示目录
                for d in dirs:
                    print(f"  {d}")
                
                # 显示文件
                for f in files:
                    # 获取文件大小
                    file_path = os.path.join(path, f)
                    size = os.path.getsize(file_path)
                    
                    # 格式化文件大小
                    if size < 1024:
                        size_str = f"{size} B"
                    elif size < 1024 * 1024:
                        size_str = f"{size/1024:.1f} KB"
                    else:
                        size_str = f"{size/(1024*1024):.1f} MB"
                    
                    print(f"  {f:30} {size_str:>10}")
            else:
                print("  空目录")
                
        except Exception as e:
            print(f"[ERROR] 无法列出目录: {e}")
    
    def interactive_mode(self):
        """交互模式"""
        self.log("\n=== STM8 Bootloader 交互模式 ===", "INFO")
        self.log("可用命令: read, write, go, info, ls, help, exit", "INFO")
        self.log("输入 'help' 查看详细用法\n", "INFO")
        
        while True:
            try:
                cmd_input = input("stm8loader> ").strip()
                if not cmd_input:
                    continue
                
                args = cmd_input.split()
                cmd = args[0].lower()
                
                if cmd == 'exit' or cmd == 'quit':
                    self.log("退出交互模式", "INFO")
                    break
                    
                elif cmd == 'help':
                    self.show_help()
                    
                elif cmd == 'ls':
                    # 列出目录
                    path = "." if len(args) < 2 else args[1]
                    self.list_directory(path)
                    
                elif cmd == 'info':
                    try:
                        info = self.get_info()
                        self.log("MCU信息:", "INFO")
                        self.log(f"  Boot0启动地址: 0x{info['boot0_address']:04X}", "INFO")
                        self.log(f"  主程序启动地址: 0x{info['main_program_address']:04X}", "INFO")
                        self.log(f"  原始数据: {info['raw_data']}", "INFO")
                        self.log(f"  当前模式: {'boot2' if info['in_boot2'] else '未知'}", "INFO")
                    except Exception as e:
                        self.log(f"错误: {e}", "ERROR")
                        
                elif cmd == 'read':
                    if len(args) < 3:
                        self.log("用法: read <addr> <size> [file]", "ERROR")
                        continue
                    
                    try:
                        addr = int(args[1], 0)
                        size = int(args[2], 0)
                        
                        data = self.read_memory(addr, size)
                        
                        # 显示数据
                        self.print_hex_dump(addr, data)
                        
                        # 保存到文件（如果指定）
                        if len(args) >= 4:
                            filename = args[3]
                            with open(filename, 'wb') as f:
                                f.write(data)
                            self.log(f"数据已保存到 {filename}", "INFO")
                            
                    except Exception as e:
                        self.log(f"错误: {e}", "ERROR")
                        
                elif cmd == 'write':
                    if len(args) < 3:
                        self.log("用法: write <addr> <file/hex_string>", "ERROR")
                        self.log("示例: write 0x8000 firmware.bin", "INFO")
                        self.log("示例: write 0x8000 AABBCCDDEEFF", "INFO")
                        continue
                    
                    try:
                        addr = int(args[1], 0)
                        source = args[2]
                        
                        # 判断是文件还是hex字符串
                        if os.path.exists(source):
                            # 从文件读取
                            with open(source, 'rb') as f:
                                data = f.read()
                        else:
                            # 尝试解析为hex字符串
                            source = source.replace('0x', '').replace(' ', '')
                            if len(source) % 2 != 0:
                                raise ValueError("Hex字符串长度必须是偶数")
                            data = bytes.fromhex(source)
                        
                        if self.write_memory(addr, data):
                            self.log(f"写入成功: {len(data)} 字节到 0x{addr:04X}", "INFO")
                            
                    except Exception as e:
                        self.log(f"错误: {e}", "ERROR")
                        
                elif cmd == 'go':
                    if len(args) < 2:
                        self.log("用法: go <addr>", "ERROR")
                        continue
                    
                    try:
                        addr = int(args[1], 0)
                        if self.go_execute(addr):
                            self.log(f"已发送跳转到 0x{addr:04X} 的命令", "INFO")
                    except Exception as e:
                        self.log(f"错误: {e}", "ERROR")
                        
                else:
                    self.log(f"未知命令: {cmd}", "ERROR")
                    self.log("输入 'help' 查看可用命令", "INFO")
                    
            except KeyboardInterrupt:
                self.log("\n退出交互模式", "INFO")
                break
            except Exception as e:
                self.log(f"错误: {e}", "ERROR")
    
    def print_hex_dump(self, start_addr: int, data: bytes, bytes_per_line: int = 16):
        """以hexdump格式打印数据"""
        for i in range(0, len(data), bytes_per_line):
            chunk = data[i:i+bytes_per_line]
            hex_str = ' '.join(f'{b:02X}' for b in chunk)
            ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
            addr = start_addr + i
            print(f"{addr:04X}: {hex_str:<48} {ascii_str}")
    
    @staticmethod
    def show_help():
        """显示帮助信息"""
        help_text = """
命令列表:
  read <addr> <size> [file]    - 读取内存，可选保存到文件
                                 示例: read 0x8000 256 dump.bin
  
  write <addr> <file/hex_str>  - 写入内存，支持文件或hex字符串
                                 示例: write 0x8000 firmware.bin
                                 示例: write 0x8000 AABBCCDDEEFF
  
  go <addr>                    - 跳转到指定地址执行
                                 示例: go 0x8000
  
  info                         - 显示MCU信息
  
  ls [path]                    - 列出目录内容
  
  help                         - 显示此帮助信息
  
  exit / quit                  - 退出交互模式
        """
        print(help_text)


def list_serial_ports():
    """列出可用串口"""
    ports = list_ports.comports()
    if not ports:
        print("[INFO] 未找到可用串口")
        return
    
    print("[INFO] 可用串口:")
    for i, port in enumerate(ports):
        print(f"  {i+1}. {port.device} - {port.description}")


def main():
    parser = argparse.ArgumentParser(
        description='STM8 Bootloader 交互工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s COM3                           # 进入交互模式
  %(prog)s COM3 -r 0x8000 256             # 读取内存
  %(prog)s COM3 -w 0x8000 firmware.bin    # 写入文件
  %(prog)s COM3 -w 0x8000 "AABBCC"        # 写入hex字符串
  %(prog)s COM3 -g 0x8000                 # 跳转执行
  %(prog)s --list-ports                   # 列出可用串口
        """
    )
    
    # 串口相关参数
    parser.add_argument('port', nargs='?', help='串口号 (如 COM3, /dev/ttyUSB0)')
    parser.add_argument('-b', '--baudrate', type=int, default=BOOT2_BAUDRATE,
                       help=f'串口波特率 (默认: {BOOT2_BAUDRATE})')
    
    # boot2上传参数
    parser.add_argument('--boot2', default='boot2.bin',
                       help='boot2程序文件路径 (默认: 脚本目录下的boot2.bin)')
    
    # 复位参数
    parser.add_argument('--reset-pin', choices=['rts', 'dtr', 'none'], default='rts',
                       help='复位引脚类型，none表示不自动复位 (默认: rts)')
    
    # 操作命令
    parser.add_argument('-r', '--read', nargs=2, metavar=('ADDR', 'SIZE'),
                       help='读取内存: ADDR为起始地址，SIZE为读取大小')
    parser.add_argument('-w', '--write', nargs=2, metavar=('ADDR', 'FILE/HEX'),
                       help='写入内存: ADDR为起始地址，FILE/HEX为文件或hex字符串')
    parser.add_argument('-g', '--go', metavar='ADDR',
                       help='跳转到地址执行')
    
    # 其他选项
    parser.add_argument('--list-ports', action='store_true',
                       help='列出可用串口')
    parser.add_argument('-o', '--output',
                       help='读取操作时保存到的文件')
    parser.add_argument('-i', '--interactive', action='store_true',
                       help='执行命令后进入交互模式')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='显示详细调试信息')
    
    args = parser.parse_args()
    
    # 列出串口
    if args.list_ports:
        list_serial_ports()
        return
    
    # 检查串口参数
    if not args.port:
        print("[ERROR] 必须指定串口号")
        print("[INFO] 使用 --list-ports 查看可用串口")
        parser.print_help()
        return 1
    
    try:
        # 创建bootloader实例
        loader = STM8Bootloader(args.port, verbose=args.verbose, reset_pin=args.reset_pin)
        
        # 打开串口
        loader.open(baudrate=args.baudrate)
        
        # 检查是否已在boot2中
        in_boot2 = loader.check_boot2()
        
        # 如果不在boot2中，则必须上传boot2
        if not in_boot2:
            print("[INFO] 不在boot2模式中，开始上传boot2程序...")
            if not loader.upload_boot2(args.boot2):
                print("[ERROR] boot2上传失败")
                loader.close()
                return 1
            print("[INFO] boot2上传成功")
        
        # 执行命令行指定的操作
        command_executed = False
        
        if args.read:
            command_executed = True
            try:
                addr = int(args.read[0], 0)
                size = int(args.read[1], 0)
                
                data = loader.read_memory(addr, size)
                
                # 打印数据
                loader.print_hex_dump(addr, data)
                
                # 保存到文件（如果指定）
                if args.output:
                    with open(args.output, 'wb') as f:
                        f.write(data)
                    print(f"[INFO] 数据已保存到 {args.output}")
                    
            except Exception as e:
                print(f"[ERROR] 读取失败: {e}")
                loader.close()
                return 1
        
        elif args.write:
            command_executed = True
            try:
                addr = int(args.write[0], 0)
                source = args.write[1]
                
                # 判断是文件还是hex字符串
                if os.path.exists(source):
                    # 从文件读取
                    with open(source, 'rb') as f:
                        data = f.read()
                else:
                    # 尝试解析为hex字符串
                    source = source.replace('0x', '').replace(' ', '')
                    if len(source) % 2 != 0:
                        raise ValueError("Hex字符串长度必须是偶数")
                    data = bytes.fromhex(source)
                
                if loader.write_memory(addr, data):
                    print(f"[INFO] 写入成功: {len(data)} 字节到 0x{addr:04X}")
                    
            except Exception as e:
                print(f"[ERROR] 写入失败: {e}")
                loader.close()
                return 1
        
        elif args.go:
            command_executed = True
            try:
                addr = int(args.go, 0)
                if loader.go_execute(addr):
                    print(f"[INFO] 已发送跳转到 0x{addr:04X} 的命令")
            except Exception as e:
                print(f"[ERROR] 跳转失败: {e}")
                loader.close()
                return 1
        
        # 如果没有指定命令或需要进入交互模式
        if not command_executed or args.interactive:
            loader.interactive_mode()
        
        # 关闭串口
        loader.close()
        
    except KeyboardInterrupt:
        print("\n[INFO] 程序被用户中断")
        return 1
    except Exception as e:
        print(f"[ERROR] 错误: {e}")
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
