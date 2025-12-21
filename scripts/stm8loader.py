#!/usr/bin/env python3
"""
STM8 Bootloader interaction tool
Supports automatic detection and upload of boot2 program, as well as read/write memory, execute, etc.
"""

import sys
import os
import time
import struct
import argparse
import serial
from serial.tools import list_ports
from typing import Optional, List, Tuple, Union, BinaryIO

# ============ Protocol Constants Definition ============
CMD_READ = 0xF1      # Read memory command
CMD_WRITE = 0xF2     # Write memory command
CMD_GO = 0xF3        # Jump execution command
CMD_EXEC = 0xF4      # Execute machine code command

CMD_HEADER = 0x5A    # Frame header sent to MCU
ACK_HEADER = 0xA5    # MCU response frame header

HANDSHAKE_ADDR = 0x8000  # Handshake detection address
HANDSHAKE_SIZE = 8       # Handshake data length

BOOT1_BAUDRATE = 9600    # boot1 baud rate
BOOT2_BAUDRATE = 128000  # boot2 baud rate

FRAME_SIZE = 70          # Command frame total size
MAX_DATA_SIZE = 64       # Maximum single data length

class STM8BootloaderError(Exception):
    """STM8 Bootloader base exception class"""
    pass

class STM8Bootloader:
    def __init__(self, port: str, verbose: bool = False, reset_pin: str = 'rts+dtr', boot2_file: str = None):
        """
        Initialize STM8 Bootloader

        Args:
            port: Serial port name
            verbose: Whether to display detailed debug information
            reset_pin: Reset pin type ('rts+dtr', 'rts', 'dtr' or 'none')
            boot2_file: boot2 binary file path
        """
        self.port = port
        self.verbose = verbose
        self.reset_pin = reset_pin.lower()
        if self.reset_pin not in ['rts+dtr', 'rts', 'dtr', 'none']:
            raise ValueError("reset_pin must be 'rts+dtr', 'rts', 'dtr' or 'none'")
        self.serial = None
        self.in_boot2 = False
        self.script_dir = os.path.dirname(os.path.abspath(__file__))

        # Store boot2 file path
        self.default_boot2_file = boot2_file

    def log(self, message: str, level: str = "INFO"):
        """
        Print log information

        Args:
            message: Log message
            level: Log level (DEBUG, INFO, ERROR, WARNING)
        """
        if level == "DEBUG" and not self.verbose:
            return

        prefix = f"[{level}] {message}"
        print(prefix)

    def open(self, baudrate: int = BOOT2_BAUDRATE):
        """Open serial connection"""
        if self.serial is None or not self.serial.is_open:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0  # Set to 0, non-blocking mode
            )
            self.log(f"Serial port {self.port} opened, baud rate {baudrate}", "DEBUG")

    def close(self):
        """Close serial connection"""
        if self.serial and self.serial.is_open:
            self.serial.close()
            self.log("Serial port closed", "DEBUG")

    def reset_mcu(self) -> bool:
        """
        Reset MCU via RTS and/or DTR

        Returns:
            True: Reset successful, False: Reset failed or not configured
        """
        if self.reset_pin == 'none':
            self.log("No automatic reset pin configured, skipping auto reset", "INFO")
            return True

        if not self.serial or not self.serial.is_open:
            return False

        self.log(f"Using {self.reset_pin.upper()} pin(s) to reset MCU...", "DEBUG")

        try:
            # Reset sequence: True -> False -> True -> wait 150ms -> False
            # Apply to selected pin(s)
            if 'rts' in self.reset_pin:
                self.serial.setRTS(True)
            if 'dtr' in self.reset_pin:
                self.serial.setDTR(True)
            time.sleep(0.01)  # Wait 10ms for stability

            if 'rts' in self.reset_pin:
                self.serial.setRTS(False)
            if 'dtr' in self.reset_pin:
                self.serial.setDTR(False)
            time.sleep(0.01)  # Wait 10ms for stability

            if 'rts' in self.reset_pin:
                self.serial.setRTS(True)
            if 'dtr' in self.reset_pin:
                self.serial.setDTR(True)
            time.sleep(0.15)  # Wait 150ms for MCU reset

            if 'rts' in self.reset_pin:
                self.serial.setRTS(False)
            if 'dtr' in self.reset_pin:
                self.serial.setDTR(False)

            self.log("MCU reset completed", "DEBUG")
            return True

        except Exception as e:
            self.log(f"Reset failed: {e}", "ERROR")
            return False

    def wait_for_boot1_signal_and_send_boot2(self, bin_file: str) -> bool:
        """
        Wait for boot1 handshake signal (0x00 0x0D), send boot2.bin immediately upon receipt

        Args:
            bin_file: boot2 binary file path

        Returns:
            True: Success, False: Failure
        """
        if not self.serial or not self.serial.is_open:
            return False

        self.log("Waiting for boot1 handshake signal (0x00 0x0D)...", "DEBUG")

        # Clear input buffer
        self.serial.reset_input_buffer()

        try:
            # Continuous reading, wait up to 250ms
            start_time = time.time()
            buffer = bytearray()

            while time.time() - start_time < 0.25:  # 250ms timeout
                # Read all available data
                if self.serial.in_waiting > 0:
                    data = self.serial.read(self.serial.in_waiting)
                    buffer.extend(data)

                    # Check for 0x00 0x0D
                    if len(buffer) >= 2 and buffer[-2:] == b'\x00\x0d':
                        self.log("Received boot1 handshake signal: 0x00 0x0D", "DEBUG")

                        # Immediately send boot2.bin
                        return self.send_boot2_binary(bin_file)

                # Short delay to avoid high CPU usage
                time.sleep(0.001)  # 1ms

            # Timeout, no signal received
            self.log("No boot1 signal received within 200ms", "DEBUG")
            return False

        except Exception as e:
            self.log(f"Error waiting for boot1 signal: {e}", "ERROR")
            return False

    def wait_for_boot1_signal_blocking(self, bin_file: str) -> bool:
        """
        Blocking wait for boot1 handshake signal until received and send boot2 or user interrupt

        Returns:
            True: Success, False: User interrupt or failure
        """
        self.log("Waiting for boot1 handshake signal, please manually press MCU reset button", "INFO")
        self.log("Press Ctrl+C to exit program", "INFO")

        # Clear input buffer
        self.serial.reset_input_buffer()

        try:
            while True:
                # Check if there's data
                if self.serial.in_waiting > 0:
                    data = self.serial.read(self.serial.in_waiting)

                    # Simple check: if data contains 0x00 0x0D
                    if b'\x00\x0d' in data:
                        self.log("Received boot1 handshake signal: 0x00 0x0D", "INFO")

                        # Immediately send boot2.bin
                        return self.send_boot2_binary(bin_file)

                # Short delay
                time.sleep(0.001)

        except KeyboardInterrupt:
            self.log("User interrupted wait", "INFO")
            return False
        except Exception as e:
            self.log(f"Error during wait: {e}", "ERROR")
            return False

    def send_boot2_binary(self, bin_file: str) -> bool:
        """
        Send boot2.bin file to MCU (byte reversed)

        Args:
            bin_file: boot2 binary file path

        Returns:
            True: Send successful, False: Send failed
        """
        try:
            # If file path is not absolute, make it relative to current working directory
            if not os.path.isabs(bin_file):
                # Try to find file in current directory first
                current_dir_file = os.path.join(os.getcwd(), bin_file)
                if os.path.exists(current_dir_file):
                    bin_file = current_dir_file
                else:
                    # Fallback to script directory
                    bin_file = os.path.join(self.script_dir, bin_file)

            with open(bin_file, 'rb') as f:
                data = f.read()

            if not data:
                self.log(f"File {bin_file} is empty", "ERROR")
                return False

            self.log(f"Read {len(data)} bytes of boot2 program from {bin_file}", "DEBUG")

            # Byte reversal
            reversed_data = bytes(reversed(data))

            # Send data (no checksum added)
            self.serial.write(reversed_data)
            self.serial.flush()

            # Log sent data in hex format
            if self.verbose:
                # Show first and last 64 bytes to avoid too much output
                if len(reversed_data) <= 128:
                    self.log(f"Sent data (hex): {reversed_data.hex()}", "DEBUG")
                else:
                    first_part = reversed_data[:64].hex()
                    last_part = reversed_data[-64:].hex()
                    self.log(f"Sent data (first 64 bytes): {first_part}", "DEBUG")
                    self.log(f"Sent data (last 64 bytes): {last_part}", "DEBUG")

            self.log(f"Sent {len(data)} bytes (reversed)", "DEBUG")
            return True

        except FileNotFoundError:
            self.log(f"File does not exist: {bin_file}", "ERROR")
            return False
        except Exception as e:
            self.log(f"Error sending boot2.bin: {e}", "ERROR")
            return False

    def calculate_checksum(self, data: bytes) -> int:
        """Calculate XOR checksum"""
        checksum = 0
        for byte in data:
            checksum ^= byte
        return checksum

    def create_command_frame(self, cmd: int, addr: int, data: bytes = b'') -> bytes:
        """
        Create command frame

        Args:
            cmd: Command type
            addr: Target address
            data: Data content

        Returns:
            Complete command frame
        """
        if len(data) > MAX_DATA_SIZE:
            raise STM8BootloaderError(f"Data length exceeds {MAX_DATA_SIZE} byte limit")

        # Build frame
        frame = bytearray(FRAME_SIZE)
        frame[0] = CMD_HEADER                    # Frame header
        frame[1] = cmd                          # Command type
        frame[2] = (addr >> 8) & 0xFF          # Address high byte
        frame[3] = addr & 0xFF                  # Address low byte
        frame[4] = len(data)                    # Data length

        # Fill data
        if data:
            frame[5:5+len(data)] = data

        # Calculate checksum (from frame header to data end)
        checksum_data = frame[:5+len(data)]
        frame[5+len(data)] = self.calculate_checksum(checksum_data)

        return bytes(frame[:5+len(data)+1])

    def parse_response_frame(self, frame: bytes) -> Tuple[int, int, bytes]:
        """
        Parse response frame

        Args:
            frame: Received frame data

        Returns:
            (command type, address, data)
        """
        if len(frame) < 6:
            raise STM8BootloaderError("Response frame length insufficient")

        if frame[0] != ACK_HEADER:
            raise STM8BootloaderError(f"Invalid response frame header: 0x{frame[0]:02X}")

        # Verify checksum
        received_checksum = frame[-1]
        calculated_checksum = self.calculate_checksum(frame[:-1])

        if received_checksum != calculated_checksum:
            raise STM8BootloaderError(f"Checksum error: received 0x{received_checksum:02X}, calculated 0x{calculated_checksum:02X}")

        cmd = frame[1]
        addr = (frame[2] << 8) | frame[3]
        data_len = frame[4]

        if len(frame) < 5 + data_len + 1:
            raise STM8BootloaderError("Response frame data length mismatch")

        data = frame[5:5+data_len]

        return cmd, addr, data

    def read_with_timeout(self, size: int, timeout: float) -> bytes:
        """
        Read specified number of bytes with timeout

        Args:
            size: Number of bytes to read
            timeout: Timeout time (seconds)

        Returns:
            Read data
        """
        data = bytearray()
        start_time = time.time()

        while len(data) < size and time.time() - start_time < timeout:
            if self.serial.in_waiting > 0:
                chunk = self.serial.read(min(self.serial.in_waiting, size - len(data)))
                data.extend(chunk)
            else:
                time.sleep(0.001)  # Short sleep to avoid high CPU usage

        return bytes(data)

    def send_command(self, cmd: int, addr: int, data: bytes = b'', 
                    wait_response: bool = True, timeout: float = 0.5) -> Optional[Tuple[int, int, bytes]]:
        """
        Send command and receive response

        Args:
            cmd: Command type
            addr: Target address
            data: Data content
            wait_response: Whether to wait for response
            timeout: Timeout time

        Returns:
            Parsed response frame, or None
        """
        if not self.serial or not self.serial.is_open:
            raise STM8BootloaderError("Serial port not open")

        # Clear input buffer
        self.serial.reset_input_buffer()

        # Create and send command frame
        frame = self.create_command_frame(cmd, addr, data)

        # Log sent frame in hex format
        if self.verbose:
            self.log(f"Sending command frame (hex): {frame.hex()}", "DEBUG")

        self.serial.write(frame)
        self.serial.flush()

        if not wait_response:
            return None

        # Wait for response
        response = self.read_with_timeout(FRAME_SIZE, timeout)

        if not response:
            raise STM8BootloaderError("No response received")

        # Log received response in hex format
        if self.verbose:
            self.log(f"Received response (hex): {response.hex()}", "DEBUG")

        return self.parse_response_frame(response)

    def check_boot2(self) -> bool:
        """
        Check if already in boot2

        Returns:
            True: In boot2, False: Not in boot2
        """
        try:
            self.log("Checking if in boot2...", "DEBUG")
            # Send read command, data field is length to read (8 bytes)
            response = self.send_command(CMD_READ, HANDSHAKE_ADDR, b'\x08', timeout=0.5)

            if response:
                cmd, addr, data = response
                if cmd == CMD_READ and addr == HANDSHAKE_ADDR and len(data) >= HANDSHAKE_SIZE:
                    self.in_boot2 = True
                    self.log("Already in boot2", "DEBUG")
                    return True

        except STM8BootloaderError as e:
            self.log(f"Not in boot2: {e}", "DEBUG")
        except Exception as e:
            self.log(f"Error checking boot2: {e}", "DEBUG")

        self.in_boot2 = False
        return False

    def upload_boot2(self, boot2_file: str = None) -> bool:
        """
        Upload boot2 program to MCU

        Args:
            boot2_file: boot2 binary file path (if None, use default)

        Returns:
            True: Upload successful, False: Upload failed
        """
        # Use provided file or default
        if boot2_file is None:
            if self.default_boot2_file:
                boot2_file = self.default_boot2_file
            else:
                # Fallback to script directory
                boot2_file = os.path.join(self.script_dir, "boot2.bin")

        self.log("Starting boot2 program upload...", "INFO")

        # 1. Switch to 9600 bps
        self.close()
        self.open(baudrate=BOOT1_BAUDRATE)
        time.sleep(0.05)  # Wait for serial port stabilization

        # 2. Try to reset MCU (if reset pin configured)
        if self.reset_pin != 'none':
            if self.reset_mcu():
                self.log("Auto MCU reset successful", "INFO")
            else:
                self.log("Auto reset failed, continuing...", "WARNING")
        else:
            self.log("No auto reset configured, waiting for manual reset...", "INFO")

        # 3. Try auto wait and send boot2 (200ms window)
        if self.reset_pin != 'none':
            self.log("Attempting to receive boot1 signal within 200ms window...", "INFO")
            if self.wait_for_boot1_signal_and_send_boot2(boot2_file):
                self.log("Boot1 signal received successfully, boot2 program sent", "INFO")
            else:
                self.log("No boot1 signal received within 200ms window, please manually reset", "WARNING")

                # Manual reset wait
                if not self.wait_for_boot1_signal_blocking(boot2_file):
                    self.log("Wait interrupted by user", "ERROR")
                    return False
        else:
            # Direct wait for manual reset
            if not self.wait_for_boot1_signal_blocking(boot2_file):
                self.log("Wait interrupted by user", "ERROR")
                return False

        # 4. Wait 1 second
        time.sleep(1.0)

        # 5. Switch to 128000 bps and check if in boot2
        self.log("Verifying boot2 program...", "INFO")
        self.close()
        self.open(baudrate=BOOT2_BAUDRATE)
        time.sleep(0.05)  # Extra 50ms wait for stabilization

        if self.check_boot2():
            self.log("boot2 upload verification success", "INFO")
            return True
        else:
            self.log("boot2 upload verification failed", "ERROR")
            return False

    def read_memory(self, addr: int, size: int) -> bytes:
        """
        Read memory

        Args:
            addr: Start address
            size: Read size

        Returns:
            Read data
        """
        if not self.in_boot2:
            raise STM8BootloaderError("Not in boot2 mode")

        result = bytearray()
        remaining = size
        current_addr = addr

        while remaining > 0:
            chunk_size = min(remaining, MAX_DATA_SIZE)

            try:
                # Send read command, data field is length to read
                response = self.send_command(CMD_READ, current_addr, 
                                           struct.pack('B', chunk_size))

                if not response:
                    raise STM8BootloaderError(f"Read address 0x{current_addr:04X} failed")

                cmd, resp_addr, data = response

                if cmd != CMD_READ or resp_addr != current_addr:
                    raise STM8BootloaderError(f"Read response mismatch")

                if len(data) != chunk_size:
                    raise STM8BootloaderError(f"Read length mismatch: expected {chunk_size}, actual {len(data)}")

                result.extend(data)
                remaining -= chunk_size
                current_addr += chunk_size

                self.log(f"Read 0x{current_addr-chunk_size:04X} - 0x{current_addr-1:04X} ({chunk_size} bytes)", "DEBUG")

            except Exception as e:
                raise STM8BootloaderError(f"Error during read: {e}")

        return bytes(result)

    def write_memory(self, addr: int, data: bytes) -> bool:
        """
        Write memory

        Args:
            addr: Start address
            data: Data to write

        Returns:
            True: Write successful, False: Write failed
        """
        if not self.in_boot2:
            raise STM8BootloaderError("Not in boot2 mode")

        remaining = len(data)
        current_addr = addr
        offset = 0

        while remaining > 0:
            chunk_size = min(remaining, MAX_DATA_SIZE)
            chunk_data = data[offset:offset+chunk_size]

            try:
                response = self.send_command(CMD_WRITE, current_addr, chunk_data)

                if not response:
                    raise STM8BootloaderError(f"Write address 0x{current_addr:04X} failed")

                cmd, resp_addr, resp_data = response

                if cmd != CMD_WRITE or resp_addr != current_addr:
                    raise STM8BootloaderError(f"Write response mismatch")

                self.log(f"Written 0x{current_addr:04X} - 0x{current_addr+chunk_size-1:04X} ({chunk_size} bytes)", "DEBUG")

                remaining -= chunk_size
                current_addr += chunk_size
                offset += chunk_size

            except Exception as e:
                raise STM8BootloaderError(f"Error during write: {e}")

        return True

    def exec_machine_code(self, addr: int, machine_code: bytes) -> bool:
        """
        Execute machine code at specified address

        Args:
            addr: Execution address
            machine_code: Machine code to execute

        Returns:
            True: Command sent successfully
        """
        if not self.in_boot2:
            raise STM8BootloaderError("Not in boot2 mode")

        if len(machine_code) > MAX_DATA_SIZE:
            raise STM8BootloaderError(f"Machine code length exceeds {MAX_DATA_SIZE} byte limit")

        try:
            # exec command doesn't care wait for response
            self.send_command(CMD_EXEC, addr, machine_code, wait_response=True)
            self.log(f"Sent execute machine code at 0x{addr:04X} command", "DEBUG")
            return True
        except Exception as e:
            raise STM8BootloaderError(f"Failed to send execute command: {e}")

    def go_execute(self, addr: int) -> bool:
        """
        Jump to specified address for execution

        Args:
            addr: Execution address

        Returns:
            True: Command sent successfully
        """
        if not self.in_boot2:
            raise STM8BootloaderError("Not in boot2 mode")

        try:
            # go command doesn't need to wait for response
            self.send_command(CMD_GO, addr, b'', wait_response=False)
            self.log(f"Sent jump to 0x{addr:04X} command", "DEBUG")
            return True
        except Exception as e:
            raise STM8BootloaderError(f"Failed to send jump command: {e}")

    def get_info(self) -> dict:
        """
        Get MCU information

        Returns:
            Dictionary containing MCU information
        """
        if not self.in_boot2:
            raise STM8BootloaderError("Not in boot2 mode")

        try:
            data = self.read_memory(HANDSHAKE_ADDR, HANDSHAKE_SIZE)

            if len(data) < HANDSHAKE_SIZE:
                raise STM8BootloaderError("Info data length insufficient")

            # Correct address parsing
            boot0_addr = (data[2] << 8) | data[3]  # Note byte order
            main_addr = (data[6] << 8) | data[7]    # Note byte order

            info = {
                'boot0_address': boot0_addr,
                'main_program_address': main_addr,
                'raw_data': data.hex(' '),
                'in_boot2': self.in_boot2
            }

            return info

        except Exception as e:
            raise STM8BootloaderError(f"Failed to get info: {e}")

    @staticmethod
    def list_directory(path: str = "."):
        """List directory contents"""
        try:
            # If path is a file, only show file info
            if os.path.isfile(path):
                size = os.path.getsize(path)
                # Format file size
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size/1024:.1f} KB"
                else:
                    size_str = f"{size/(1024*1024):.1f} MB"

                print(f"File: {os.path.abspath(path)}")
                print(f"Size: {size_str}")
                return

            # Path is a directory
            items = os.listdir(path)

            # Separate directories and files
            dirs = []
            files = []

            for item in items:
                full_path = os.path.join(path, item)
                if os.path.isdir(full_path):
                    dirs.append(item + "/")
                else:
                    files.append(item)

            # Sort
            dirs.sort()
            files.sort()

            # Display
            print(f"Directory: {os.path.abspath(path)}")
            print()

            # Display items in columns (space separated)
            all_items = dirs + files

            # Display in multiple columns
            if all_items:
                # Calculate column width based on longest item name
                max_len = max(len(item) for item in all_items) + 2
                terminal_width = 80  # Default terminal width
                items_per_line = max(1, terminal_width // max_len)

                for i, item in enumerate(all_items):
                    print(f"{item:<{max_len}}", end='')
                    if (i + 1) % items_per_line == 0:
                        print()

                # Print newline if last line wasn't complete
                if len(all_items) % items_per_line != 0:
                    print()
            else:
                print("  Empty directory")

        except Exception as e:
            print(f"[ERROR] Unable to list directory: {e}")

    def interactive_mode(self):
        """Interactive mode"""
        self.log("\n=== STM8 Bootloader Interactive Mode ===", "INFO")
        self.log("Available commands: read, write, exec, go, info, ls, reload, help, exit", "INFO")
        self.log("Type 'help' for detailed usage\n", "INFO")

        while True:
            try:
                cmd_input = input("stm8loader> ").strip()
                if not cmd_input:
                    continue

                args = cmd_input.split()
                cmd = args[0].lower()

                if cmd == 'exit' or cmd == 'quit':
                    self.log("Exiting interactive mode", "INFO")
                    break

                elif cmd == 'help':
                    self.show_help()

                elif cmd == 'ls':
                    # List directory
                    path = "." if len(args) < 2 else args[1]
                    self.list_directory(path)

                elif cmd == 'reload':
                    # Reset and upload boot2 with optional file path
                    boot2_file = args[1] if len(args) > 1 else None
                    self.log("Executing reset and to upload boot2...", "INFO")
                    if not self.upload_boot2(boot2_file):
                        self.log("Reset upload failed", "ERROR")
                    else:
                        self.log("Reset upload successful", "INFO")

                elif cmd == 'info':
                    try:
                        info = self.get_info()
                        self.log("MCU Information:", "INFO")
                        self.log(f"  Boot0 start address: 0x{info['boot0_address']:04X}", "INFO")
                        self.log(f"  Main program start address: 0x{info['main_program_address']:04X}", "INFO")
                        self.log(f"  Raw data: {info['raw_data']}", "INFO")
                        self.log(f"  Current mode: {'boot2' if info['in_boot2'] else 'unknown'}", "INFO")
                    except Exception as e:
                        self.log(f"Error: {e}", "ERROR")

                elif cmd == 'read' or cmd == 'r':
                    if len(args) < 3:
                        self.log("Usage: read <addr> <size> [file]", "ERROR")
                        continue

                    try:
                        addr = int(args[1], 0)
                        size = int(args[2], 0)

                        data = self.read_memory(addr, size)

                        # Display data
                        self.print_hex_dump(addr, data)

                        # Save to file (if specified)
                        if len(args) >= 4:
                            filename = args[3]
                            with open(filename, 'wb') as f:
                                f.write(data)
                            self.log(f"Data saved to {filename}", "INFO")

                    except Exception as e:
                        self.log(f"Error: {e}", "ERROR")

                elif cmd == 'write' or cmd == 'w':
                    if len(args) < 3:
                        self.log("Usage: write <addr> <file/hex_string>", "ERROR")
                        self.log("Example: write 0x8000 firmware.bin", "INFO")
                        self.log("Example: write 0x8000 AABBCCDDEEFF", "INFO")
                        continue

                    try:
                        addr = int(args[1], 0)
                        source = args[2]

                        # Determine if it's a file or hex string
                        if os.path.exists(source):
                            # Read from file
                            with open(source, 'rb') as f:
                                data = f.read()
                        else:
                            # Try to parse as hex string
                            source = source.replace('0x', '').replace(' ', '')
                            if len(source) % 2 != 0:
                                raise ValueError("Hex string length must be even")
                            data = bytes.fromhex(source)

                        if self.write_memory(addr, data):
                            self.log(f"Write successful: {len(data)} bytes to 0x{addr:04X}", "INFO")

                    except Exception as e:
                        self.log(f"Error: {e}", "ERROR")

                elif cmd == 'exec' or cmd == 'x':
                    if len(args) < 2:
                        self.log("Usage: exec <hex_string>", "ERROR")
                        self.log("Example: exec 4F9D (CLR A; NOP)", "INFO")
                        continue

                    try:
                        addr = 0 # run in #boot2.rx_buffer
                        hex_str = args[1]

                        # Parse hex string
                        hex_str = hex_str.replace('0x', '').replace(' ', '')
                        if len(hex_str) % 2 != 0:
                            raise ValueError("Hex string length must be even")
                        machine_code = bytes.fromhex(hex_str)

                        if len(machine_code) > MAX_DATA_SIZE:
                            self.log(f"Error: Machine code too long (max {MAX_DATA_SIZE} bytes)", "ERROR")
                            continue

                        if self.exec_machine_code(addr, machine_code):
                            self.log(f"Execute command sent: {len(machine_code)} bytes at 0x{addr:04X}", "INFO")

                    except Exception as e:
                        self.log(f"Error: {e}", "ERROR")

                elif cmd == 'go' or cmd == 'g':
                    if len(args) < 2:
                        self.log("Usage: go <addr>", "ERROR")
                        continue

                    try:
                        addr = int(args[1], 0)
                        if self.go_execute(addr):
                            self.log(f"Sent jump to 0x{addr:04X} command", "INFO")
                    except Exception as e:
                        self.log(f"Error: {e}", "ERROR")

                else:
                    self.log(f"Unknown command: {cmd}", "ERROR")
                    self.log("Type 'help' for available commands", "INFO")

            except KeyboardInterrupt:
                self.log("\nExiting interactive mode", "INFO")
                break
            except Exception as e:
                self.log(f"Error: {e}", "ERROR")

    def print_hex_dump(self, start_addr: int, data: bytes, bytes_per_line: int = 16):
        """Print data in hexdump format"""
        for i in range(0, len(data), bytes_per_line):
            chunk = data[i:i+bytes_per_line]
            hex_str = ' '.join(f'{b:02X}' for b in chunk)
            ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
            addr = start_addr + i
            print(f"{addr:04X}: {hex_str:<48} {ascii_str}")

    @staticmethod
    def show_help():
        """Display help information"""
        help_text = """
Command List:
  r/read <addr> <size> [file]  - Read memory, optionally save to file
                                 Example: read 0x8000 256 dump.bin

  w/write <addr> <file/hexstr> - Write memory, supports file or hex string
                                 Example: write 0x8000 firmware.bin
                                 Example: write 0x8000 AABBCCDDEEFF

  x/exec <hexstr>              - Execute machine code at *fixed* address
                                 Example: exec 4F9D (CLR A; NOP;)

  g/go <addr>                  - Jump to specified address for execution
                                 Example: go 0x8000

  info                         - Display MCU information

  ls [path]                    - List directory contents, files show size

  reload [file]                - Reset MCU and upload boot2 program

  help                         - Display this help information

  exit/quit                    - Exit interactive mode
        """
        print(help_text)


def list_serial_ports():
    """List available serial ports"""
    ports = list_ports.comports()
    if not ports:
        print("[INFO] No serial ports found")
        return

    print("[INFO] Available serial ports:")
    for i, port in enumerate(ports):
        print(f"  {i+1}. {port.device} - {port.description}")


def main():
    parser = argparse.ArgumentParser(
        description='STM8 Bootloader interaction tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /dev/ttyUSB0                      # Enter interactive mode
  %(prog)s /dev/ttyUSB0 -r 0x8000 256        # Read memory
  %(prog)s /dev/ttyUSB0 -w 0x8000 firmware.bin    # Write file
  %(prog)s /dev/ttyUSB0 -w 0x8000 "AABBCC"   # Write hex string
  %(prog)s /dev/ttyUSB0 -g 0x8000            # Jump execution
  %(prog)s --list-ports                      # List available serial ports
        """
    )

    # Serial port related parameters
    parser.add_argument('port', nargs='?', help='Serial port name (e.g., /dev/ttyUSB0, COM3)')
    parser.add_argument('-b', '--baudrate', type=int, default=BOOT2_BAUDRATE,
                       help=f'Serial port baud rate (default: {BOOT2_BAUDRATE})')

    # boot2 upload parameters
    parser.add_argument('--boot2', default='boot2.bin',
                       help='boot2 program file path (default: boot2.bin in current directory or script directory)')
    parser.add_argument('--skip-boot2', action='store_true',
                       help='Skip automatic boot2 upload, directly enter interactive mode')

    # Reset parameters
    parser.add_argument('--reset-pin', choices=['rts+dtr', 'rts', 'dtr', 'none'], default='rts+dtr',
                       help='Reset pin type, none means no auto reset (default: rts+dtr)')

    # Operation commands
    parser.add_argument('-r', '--read', nargs=2, metavar=('ADDR', 'SIZE'),
                       help='Read memory: ADDR is start address, SIZE is read size')
    parser.add_argument('-w', '--write', nargs=2, metavar=('ADDR', 'FILE/HEX'),
                       help='Write memory: ADDR is start address, FILE/HEX is file or hex string')
    parser.add_argument('-g', '--go', metavar='ADDR',
                       help='Jump to address for execution')
    parser.add_argument('-x', '--exec', metavar='HEX',
                       help='Execute machine code')

    # Other options
    parser.add_argument('--list-ports', action='store_true',
                       help='List available serial ports')
    parser.add_argument('-o', '--output',
                       help='File to save read operation output to')
    parser.add_argument('-i', '--interactive', action='store_true',
                       help='Enter interactive mode after executing command')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Display detailed debug information including serial data hex dumps')

    args = parser.parse_args()

    # List serial ports
    if args.list_ports:
        list_serial_ports()
        return

    # Check serial port parameter
    if not args.port:
        print("[ERROR] Must specify serial port name")
        print("[INFO] Use --list-ports to view available serial ports")
        parser.print_help()
        return 1

    try:
        # Handle boot2 file path
        boot2_file = args.boot2

        # Create bootloader instance
        loader = STM8Bootloader(args.port, verbose=args.verbose, 
                               reset_pin=args.reset_pin, boot2_file=boot2_file)

        # Open serial port
        loader.open(baudrate=args.baudrate)

        # Check if already in boot2
        in_boot2 = loader.check_boot2()

        # If not in boot2 and not skipping boot2 upload, must upload boot2
        if not in_boot2 and not args.skip_boot2:
            print("[INFO] Not in boot2 mode, starting boot2 program upload...")
            if not loader.upload_boot2():
                print("[ERROR] boot2 upload failed")
                loader.close()
                return 1
            print("[INFO] boot2 upload successful")
        elif args.skip_boot2 and not in_boot2:
            print("[WARNING] Skipping boot2 upload, but not in boot2 mode")
            print("[INFO] Please use 'reload' command in interactive mode to upload boot2")

        # Execute command line specified operations
        command_executed = False

        if args.read:
            command_executed = True
            try:
                addr = int(args.read[0], 0)
                size = int(args.read[1], 0)

                data = loader.read_memory(addr, size)

                # Print data
                loader.print_hex_dump(addr, data)

                # Save to file (if specified)
                if args.output:
                    with open(args.output, 'wb') as f:
                        f.write(data)
                    print(f"[INFO] Data saved to {args.output}")

            except Exception as e:
                print(f"[ERROR] Read failed: {e}")
                loader.close()
                return 1

        elif args.write:
            command_executed = True
            try:
                addr = int(args.write[0], 0)
                source = args.write[1]

                # Determine if it's a file or hex string
                if os.path.exists(source):
                    # Read from file
                    with open(source, 'rb') as f:
                        data = f.read()
                else:
                    # Try to parse as hex string
                    source = source.replace('0x', '').replace(' ', '')
                    if len(source) % 2 != 0:
                        raise ValueError("Hex string length must be even")
                    data = bytes.fromhex(source)

                if loader.write_memory(addr, data):
                    print(f"[INFO] Write successful: {len(data)} bytes to 0x{addr:04X}")

            except Exception as e:
                print(f"[ERROR] Write failed: {e}")
                loader.close()
                return 1

        elif args.go:
            command_executed = True
            try:
                addr = int(args.go, 0)
                if loader.go_execute(addr):
                    print(f"[INFO] Sent jump to 0x{addr:04X} command")
            except Exception as e:
                print(f"[ERROR] Jump failed: {e}")
                loader.close()
                return 1

        elif args.exec:
            command_executed = True
            try:
                addr = 0
                hex_str = args.exec.replace('0x', '').replace(' ', '')
                if len(hex_str) % 2 != 0:
                    raise ValueError("Hex string length must be even")
                machine_code = bytes.fromhex(hex_str)
                if len(machine_code) > MAX_DATA_SIZE:
                    raise ValueError("Machine code too long (max {MAX_DATA_SIZE} bytes)")
                if loader.exec_machine_code(addr, machine_code):
                    print(f"[INFO] Exec {len(machine_code)} bytes")
            except Exception as e:
                print(f"[ERROR] Exec failed: {e}")
                loader.close()
                return 1

        # If no command specified or need to enter interactive mode
        if not command_executed or args.interactive:
            loader.interactive_mode()

        # Close serial port
        loader.close()

    except KeyboardInterrupt:
        print("\n[INFO] Program interrupted by user")
        return 1
    except Exception as e:
        print(f"[ERROR] Error: {e}")
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
