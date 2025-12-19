#!/usr/bin/env python3
"""
STM8 RAM Bootloader测试脚本
用于测试bootloader功能

工作流程：
1. 默认加载同级目录下的boot2.bin发送，可通过选项指定
2. 执行后，等待用户按下开发板的复位键
3. MCU复位后，会以波特率9600发送0x00 0x0D到python
4. 收到后开始发送boot2.bin，从最后一块开始向前发送，每发送128字节后，MCU会应答一个0x01
5. 发送完成后进入交互shell，用户可以输入命令执行响应的操作（先不实现）

用法：
python3 stm8_bootloader_test.py [-p PORT] [-b BAUDRATE] [--bin BIN_FILE]
"""

import sys
import os
import time
import argparse
import serial
import struct
import colorama
from colorama import Fore, Style
from typing import Optional, List

colorama.init(autoreset=True)

class STM8BootloaderTester:
    def __init__(self, port: str, baudrate: int = 9600, bin_file: str = None):
        self.port = port
        self.baudrate = baudrate
        
        # 如果未指定bin文件，使用脚本同级目录下的boot2.bin
        if bin_file is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            self.bin_file = os.path.join(script_dir, "boot2.bin")
        else:
            self.bin_file = bin_file
            
        self.ser = None
        self.bootloader_size = 0
        
    def open_serial(self) -> bool:
        """打开串口"""
        try:
            print(f"{Fore.CYAN}打开串口 {self.port}, 波特率 {self.baudrate}...")
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1.0,  # 读取超时1秒
                write_timeout=1.0  # 写入超时1秒
            )
            
            if self.ser.is_open:
                print(f"{Fore.GREEN}串口打开成功!")
                return True
            else:
                print(f"{Fore.RED}串口打开失败!")
                return False
                
        except serial.SerialException as e:
            print(f"{Fore.RED}串口错误: {e}")
            return False
            
    def close_serial(self):
        """关闭串口"""
        if self.ser and self.ser.is_open:
            self.ser.close()
            print(f"{Fore.YELLOW}串口已关闭")
            
    def check_file_size(self, file_size: int, chunk_size: int = 128) -> bool:
        """检查文件大小是否为chunk_size的整数倍"""
        if file_size % chunk_size != 0:
            print(f"{Fore.RED}错误: 文件大小 {file_size} 不是 {chunk_size} 的整数倍!")
            print(f"{Fore.YELLOW}请确保bootloader大小为 {chunk_size} 字节的整数倍")
            return False
        return True
            
    def read_bin_file(self) -> Optional[bytes]:
        """读取bin文件"""
        try:
            if not os.path.exists(self.bin_file):
                print(f"{Fore.RED}错误: 文件 {self.bin_file} 不存在!")
                return None
                
            with open(self.bin_file, 'rb') as f:
                data = f.read()
                
            self.bootloader_size = len(data)
            print(f"{Fore.GREEN}读取 {self.bootloader_size} 字节来自 {self.bin_file}")
            
            # 检查文件大小是否为128的整数倍
            if not self.check_file_size(self.bootloader_size):
                return None
            
            # 显示文件信息
            if self.bootloader_size > 0:
                print(f"{Fore.CYAN}文件首16字节: {data[:16].hex(' ')}")
                if self.bootloader_size > 16:
                    print(f"{Fore.CYAN}文件尾16字节: {data[-16:].hex(' ')}")
                    
            return data
            
        except Exception as e:
            print(f"{Fore.RED}读取文件错误: {e}")
            return None
            
    def wait_for_mcu_ready(self, timeout: int = 30) -> bool:
        """等待MCU发送就绪信号 0x00 0x0D"""
        print(f"\n{Fore.YELLOW}等待MCU就绪信号...")
        print(f"{Fore.YELLOW}请按下开发板上的复位键!")
        print(f"{Fore.YELLOW}等待超时: {timeout} 秒")
        
        start_time = time.time()
        last_print_time = start_time
        expected_bytes = b'\x00\x0D'
        buffer = b''
        
        try:
            while time.time() - start_time < timeout:
                current_time = time.time()
                elapsed = int(current_time - start_time)
                
                # 每5秒打印一次状态
                if current_time - last_print_time >= 5:
                    print(f"{Fore.YELLOW}已等待 {elapsed} 秒...")
                    last_print_time = current_time
                
                # 检查串口是否有数据
                if self.ser.in_waiting > 0:
                    # 读取一个字节
                    byte = self.ser.read(self.ser.in_waiting)
                    if byte:
                        buffer += byte
                        
                        # 检查是否匹配就绪信号
                        if buffer[-2:] == expected_bytes:
                            print(f"{Fore.GREEN}收到MCU就绪信号: {buffer.hex(' ')}")
                            return True
                            
                        # 显示接收到的数据（调试用）
                        if buffer:
                            print(f"{Fore.CYAN}[调试] 接收缓冲区: {buffer.hex(' ')}")
                            # 保留缓冲区最后一个字节
                            buffer = buffer[-1:]
                            
                            
                time.sleep(0.01)
                
        except Exception as e:
            print(f"{Fore.RED}等待MCU就绪时出错: {e}")
            
        print(f"{Fore.RED}超时! 未收到MCU就绪信号")
        return False
        
    def reverse_bytes_within_chunks(self, data: bytes, chunk_size: int = 128) -> bytes:
        """在每个128字节块内反转字节顺序"""
        if len(data) % chunk_size != 0:
            raise ValueError(f"数据长度({len(data)})必须是{chunk_size}的整数倍")
            
        result = bytearray()
        num_chunks = len(data) // chunk_size
        
        for i in range(num_chunks):
            start_idx = i * chunk_size
            end_idx = start_idx + chunk_size
            chunk = data[start_idx:end_idx]
            # 反转块内字节顺序
            reversed_chunk = bytes(reversed(chunk))
            result.extend(reversed_chunk)
            
        return bytes(result)
        
    def send_bootloader_reverse(self, data: bytes, chunk_size: int = 128) -> bool:
        """反向发送bootloader数据（从最后一块开始，每块内字节也反转）"""
        if not data:
            print(f"{Fore.RED}错误: 没有数据可发送")
            return False
            
        # 首先在每个128字节块内反转字节顺序
        reversed_data = self.reverse_bytes_within_chunks(data, chunk_size)
        
        total_size = len(reversed_data)
        num_chunks = total_size // chunk_size
        
        print(f"\n{Fore.CYAN}开始反向发送bootloader...")
        print(f"{Fore.CYAN}总大小: {total_size} 字节")
        print(f"{Fore.CYAN}分块大小: {chunk_size} 字节")
        print(f"{Fore.CYAN}总块数: {num_chunks}")
        print(f"{Fore.CYAN}发送顺序: 从最后一块到第一块，每块内字节顺序已反转")
        
        success_count = 0
        fail_count = 0
        
        try:
            # 从最后一块开始发送
            for i in range(num_chunks - 1, -1, -1):
                start_idx = i * chunk_size
                end_idx = start_idx + chunk_size
                chunk = reversed_data[start_idx:end_idx]
                
                # 原始块索引（反转前）
                original_chunk_index = i
                original_start_addr = original_chunk_index * chunk_size
                
                print(f"\n{Fore.YELLOW}[块 {num_chunks-i}/{num_chunks}]")
                print(f"{Fore.CYAN}  原始位置: 0x{original_start_addr:04X}-0x{original_start_addr+chunk_size-1:04X}")
                print(f"{Fore.CYAN}  发送大小: {len(chunk)} 字节")
                print(f"{Fore.CYAN}  数据(已反转): {chunk[:16].hex(' ')}" + 
                      ("..." if len(chunk) > 16 else ""))
                
                # 发送数据块
                bytes_sent = self.ser.write(chunk)
                
                if bytes_sent != len(chunk):
                    print(f"{Fore.RED}  发送失败! 期望 {len(chunk)} 字节, 实际 {bytes_sent} 字节")
                    fail_count += 1
                    continue
                    
                print(f"{Fore.GREEN}  发送成功: {bytes_sent} 字节")
                
                # 等待MCU应答
                print(f"{Fore.YELLOW}  等待MCU应答...")
                
                try:
                    # 读取应答
                    ack = self.ser.read(1)
                    if ack == b'\x00':
                        print(f"{Fore.GREEN}  收到确认: 0x00")
                        success_count += 1
                    elif ack:
                        print(f"{Fore.RED}  收到错误应答: {ack.hex()}")
                        fail_count += 1
                    else:
                        print(f"{Fore.RED}  应答超时!")
                        fail_count += 1
                        
                except Exception as e:
                    print(f"{Fore.RED}  读取应答时出错: {e}")
                    fail_count += 1
                    
                # 显示进度
                progress = (num_chunks - i) / num_chunks * 100
                print(f"{Fore.CYAN}  进度: {progress:.1f}% ({num_chunks-i}/{num_chunks})")
                
        except Exception as e:
            print(f"{Fore.RED}发送过程中出错: {e}")
            return False
            
        print(f"\n{Fore.CYAN}=== 发送完成 ===")
        print(f"{Fore.GREEN}成功块数: {success_count}")
        print(f"{Fore.RED}失败块数: {fail_count}")
        
        return fail_count == 0
        
    def interactive_shell(self):
        """交互式命令行"""
        print(f"\n{Fore.CYAN}{'='*60}")
        print(f"{Fore.CYAN}进入交互模式")
        print(f"{Fore.CYAN}输入 'help' 查看可用命令")
        print(f"{Fore.CYAN}输入 'exit' 退出")
        print(f"{Fore.CYAN}{'='*60}")
        
        commands = {
            'help': self._cmd_help,
            'read': self._cmd_read,
            'write': self._cmd_write,
            'erase': self._cmd_erase,
            'reset': self._cmd_reset,
            'go': self._cmd_go,
            'echo': self._cmd_echo,
            'info': self._cmd_info,
        }
        
        while True:
            try:
                # 获取用户输入
                cmd_input = input(f"\n{Fore.GREEN}boot> ").strip()
                
                if not cmd_input:
                    continue
                    
                # 检查是否为退出命令
                if cmd_input.lower() in ['exit', 'quit', 'q']:
                    print(f"{Fore.YELLOW}退出交互模式")
                    break
                    
                # 分割命令和参数
                parts = cmd_input.split()
                cmd = parts[0].lower()
                args = parts[1:] if len(parts) > 1 else []
                
                # 执行命令
                if cmd in commands:
                    commands[cmd](args)
                else:
                    print(f"{Fore.RED}未知命令: {cmd}")
                    print(f"{Fore.YELLOW}输入 'help' 查看可用命令")
                    
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}检测到Ctrl+C，退出交互模式")
                break
            except Exception as e:
                print(f"{Fore.RED}命令执行错误: {e}")
                
    def _cmd_help(self, args):
        """显示帮助"""
        print(f"{Fore.CYAN}可用命令:")
        print(f"{Fore.YELLOW}  help             显示此帮助信息")
        print(f"{Fore.YELLOW}  read <addr> <len> 读取内存")
        print(f"{Fore.YELLOW}  write <addr> <data> 写入内存")
        print(f"{Fore.YELLOW}  erase             擦除Flash")
        print(f"{Fore.YELLOW}  reset             复位MCU")
        print(f"{Fore.YELLOW}  go <addr>         跳转到指定地址执行")
        print(f"{Fore.YELLOW}  echo <text>       回显文本")
        print(f"{Fore.YELLOW}  info              显示信息")
        print(f"{Fore.YELLOW}  exit              退出交互模式")
        
    def _cmd_read(self, args):
        """读取内存命令"""
        if len(args) < 2:
            print(f"{Fore.RED}用法: read <地址> <长度>")
            print(f"{Fore.YELLOW}示例: read 0x8000 16")
            return
            
        try:
            addr = int(args[0], 0)
            length = int(args[1], 0)
            
            print(f"{Fore.CYAN}读取内存:")
            print(f"{Fore.CYAN}  地址: 0x{addr:04X}")
            print(f"{Fore.CYAN}  长度: {length} 字节")
            
            # TODO: 实现读取命令
            print(f"{Fore.YELLOW}[待实现] 读取功能")
            
        except ValueError as e:
            print(f"{Fore.RED}参数错误: {e}")
            
    def _cmd_write(self, args):
        """写入内存命令"""
        if len(args) < 2:
            print(f"{Fore.RED}用法: write <地址> <数据>")
            print(f"{Fore.YELLOW}示例: write 0x8000 0x01 0x02 0x03")
            return
            
        try:
            addr = int(args[0], 0)
            data = [int(x, 0) for x in args[1:]]
            
            print(f"{Fore.CYAN}写入内存:")
            print(f"{Fore.CYAN}  地址: 0x{addr:04X}")
            print(f"{Fore.CYAN}  数据: {bytes(data).hex(' ')}")
            print(f"{Fore.CYAN}  长度: {len(data)} 字节")
            
            # TODO: 实现写入命令
            print(f"{Fore.YELLOW}[待实现] 写入功能")
            
        except ValueError as e:
            print(f"{Fore.RED}参数错误: {e}")
            
    def _cmd_erase(self, args):
        """擦除Flash命令"""
        print(f"{Fore.YELLOW}擦除Flash...")
        # TODO: 实现擦除命令
        print(f"{Fore.YELLOW}[待实现] 擦除功能")
        
    def _cmd_reset(self, args):
        """复位命令"""
        print(f"{Fore.YELLOW}复位MCU...")
        # TODO: 实现复位命令
        print(f"{Fore.YELLOW}[待实现] 复位功能")
        
    def _cmd_go(self, args):
        """跳转执行命令"""
        if len(args) < 1:
            print(f"{Fore.RED}用法: go <地址>")
            print(f"{Fore.YELLOW}示例: go 0x8000")
            return
            
        try:
            addr = int(args[0], 0)
            print(f"{Fore.YELLOW}跳转到地址: 0x{addr:04X}")
            # TODO: 实现跳转命令
            print(f"{Fore.YELLOW}[待实现] 跳转功能")
            
        except ValueError as e:
            print(f"{Fore.RED}参数错误: {e}")
            
    def _cmd_echo(self, args):
        """回显命令"""
        if args:
            text = ' '.join(args)
            print(f"{Fore.CYAN}回显: {text}")
        else:
            print(f"{Fore.RED}用法: echo <文本>")
            
    def _cmd_info(self, args):
        """显示信息命令"""
        print(f"{Fore.CYAN}Bootloader测试工具信息:")
        print(f"{Fore.CYAN}  串口: {self.port}")
        print(f"{Fore.CYAN}  波特率: {self.baudrate}")
        print(f"{Fore.CYAN}  Bootloader文件: {self.bin_file}")
        print(f"{Fore.CYAN}  Bootloader大小: {self.bootloader_size} 字节")
        
    def run(self):
        """运行测试"""
        print(f"{Fore.CYAN}{'='*60}")
        print(f"{Fore.CYAN}STM8 RAM Bootloader 测试工具")
        print(f"{Fore.CYAN}{'='*60}")
        
        # 1. 打开串口
        if not self.open_serial():
            return False
            
        try:
            # 2. 读取bin文件
            bin_data = self.read_bin_file()
            if not bin_data:
                return False
                
            # 3. 等待MCU就绪
            if not self.wait_for_mcu_ready():
                return False
                
            # 4. 发送bootloader（反向发送）
            if not self.send_bootloader_reverse(bin_data):
                print(f"{Fore.RED}Bootloader发送失败!")
                return False
                
            # 5. 进入交互模式
            self.interactive_shell()
            
            return True
            
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}用户中断!")
            return False
            
        except Exception as e:
            print(f"{Fore.RED}运行时错误: {e}")
            import traceback
            traceback.print_exc()
            return False
            
        finally:
            self.close_serial()

def list_serial_ports():
    """列出可用串口"""
    import serial.tools.list_ports
    
    ports = serial.tools.list_ports.comports()
    
    if not ports:
        print(f"{Fore.YELLOW}未找到可用串口!")
        return []
        
    print(f"{Fore.CYAN}可用串口:")
    for i, port in enumerate(ports):
        print(f"{Fore.GREEN}  [{i}] {port.device}: {port.description}")
        
    return ports

def main():
    parser = argparse.ArgumentParser(description="STM8 RAM Bootloader测试工具")
    parser.add_argument("-p", "--port", help="串口号 (如 COM3, /dev/ttyUSB0)")
    parser.add_argument("-b", "--baudrate", type=int, default=9600, 
                       help="串口波特率 (默认: 9600)")
    parser.add_argument("--bin", default=None, 
                       help="Bootloader bin文件路径 (默认: 脚本目录下的boot2.bin)")
    parser.add_argument("--list", action="store_true", 
                       help="列出可用串口")
    
    args = parser.parse_args()
    
    # 如果指定了--list，列出串口后退出
    if args.list:
        list_serial_ports()
        return
        
    # 如果没有指定串口，列出并让用户选择
    if not args.port:
        ports = list_serial_ports()
        if not ports:
            print(f"{Fore.RED}请使用 -p 参数指定串口!")
            return
            
        try:
            choice = input(f"\n{Fore.CYAN}请选择串口号 [0-{len(ports)-1}]: ")
            idx = int(choice)
            if 0 <= idx < len(ports):
                args.port = ports[idx].device
            else:
                print(f"{Fore.RED}无效的选择!")
                return
        except (ValueError, IndexError):
            print(f"{Fore.RED}无效的输入!")
            return
    
    # 创建测试器并运行
    tester = STM8BootloaderTester(
        port=args.port,
        baudrate=args.baudrate,
        bin_file=args.bin
    )
    
    success = tester.run()
    
    if success:
        print(f"\n{Fore.GREEN}测试完成!")
    else:
        print(f"\n{Fore.RED}测试失败!")
        
    # 等待用户按键退出
    input(f"\n{Fore.YELLOW}按Enter键退出...")

if __name__ == "__main__":
    main()
