; ================================================
; STM8 RAM Bootloader for SDCC - Optimized Version
;
; 命令帧格式:
;   字节0: 帧头 (0x5A/0xA5)
;   字节1: 命令类型 (见CMD_*常量)
;   字节2-3: 目标地址 (高字节在前)
;   字节4: 数据长度 (0-64)
;   字节5-68: 数据内容 (最多64字节)
;   字节69: 校验和 (所有字节XOR)
; ================================================

;; Register address definitions
UART1_SR    = 0x5230   ; Status register
UART1_DR    = 0x5231   ; Data register
UART1_BRR1  = 0x5232   ; Baud rate register 1
UART1_BRR2  = 0x5233   ; Baud rate register 2
UART1_CR2   = 0x5235   ; Control register 2

FLASH_DUKR  = 0x5064   ; Data EEPROM unprotect
FLASH_PUKR  = 0x5062   ; Flash unprotect
FLASH_CR2   = 0x505B   ; Flash control 2
FLASH_NCR2  = 0x505C   ; Flash control 2 complement
FLASH_IAPSR = 0x505F   ; Flash in-application program status

OPT0_ROP    = 0x4800   ; Option byte: ROP
WWDG_CR     = 0x50D1   ; WWDG control register

;; Const vars
CMD_READ    = 0xF1     ; 读内存命令
CMD_WRITE   = 0xF2     ; 写内存命令
CMD_GO      = 0xF3     ; 跳转执行命令
CMD_EXEC    = 0xF4     ; 直接执行机器码命令

CMD_HEADER   = 0x5A    ; 帧头
ACK_HEADER   = 0xA5    ; 应答帧头

SUCCESS_CODE = 0x00    ; 成功响应码
ERR_CHECKSUM = 0xE1    ; 校验错误
ERR_INVCMD   = 0xE2    ; 非法命令
ERR_PGDIS    = 0xE3    ; 编程受保护的地址

MAX_DATA_SIZE = 64     ; 最大数据长度

;; Global vars
;; After an MCU reset the Stack Pointer is set to its upper limit value
DEFAULT_SP_H = 0x0000  ; Saved with SP value
DEFAULT_SP_L = 0x0001  ;
rx_state          = 2  ; 接收状态
rx_length         = 3  ; 接收长度
tx_data_length    = 4  ; 待发送的数据长度
calc_checksum     = 5  ; 计算的校验和
temp_var1         = 6  ; 临时变量
temp_var2         = 7  ; 临时变量
tx_buffer    = 0x0008  ; protocol tx buffer
rx_buffer    = 0x0008  ; protocol rx buffer

BOOT2_ULA   = 0x03CF   ; boot2 ram Upper-Limit-Address

    .area   DATA
    .area   HOME
    .area   RAM_BOOT

    .db     (BOOT2_ULA-(_end-_start)+1)>>8
    .db     (BOOT2_ULA-(_end-_start)+1)&0xFF

_start:
    ; 配置UART1: 128000波特率, 8N1, 启用TX/RX
    mov UART1_BRR1, #1
    ;mov UART1_BRR2, #0
    ;mov UART1_CR2, #0x0C  ; TEN=1, REN=1
_main_loop:
    ; 接收命令帧
    callr receive_frame

    ; 验证校验和
    callr verify_checksum
    jrne _checksum_error

    ; 根据命令类型跳转
    ld A, rx_buffer+1  ; 命令类型

    cp A, #CMD_READ
    jreq _cmd_read

    cp A, #CMD_WRITE
    jreq _cmd_write

    cp A, #CMD_GO
    jreq _cmd_go

    cp A, #CMD_EXEC
    jreq _cmd_exec

_invalid_cmd_error:
    ; 未知命令，发送错误响应
    ld A, #ERR_INVCMD
_ack_then_back:
    call send_ack_state_response
    jra _main_loop

_checksum_error:
    ; 校验和错误响应
    ld A, #ERR_CHECKSUM
    jra _ack_then_back

_cmd_read:
    ; 读取内存命令
    call read_memory
    jra _main_loop

_cmd_write:
    ; 写入内存命令
    call write_memory
    jra _main_loop

_cmd_go:
    ; 跳转执行命令
    ldw X, rx_buffer+2
    jp (X)
    ; 注意: jump_to_address 不返回

_cmd_exec:
    ; 直接执行收到的机器码
    ld A, #0x81     ; ret code
    ld (X), A       ; X point to checksum already
    call rx_buffer+5
    ld A, #SUCCESS_CODE
    jra _ack_then_back

receive_frame:
    ; 初始化接收状态
    clr rx_state
    mov rx_length, #6
    ldw X, #rx_buffer

_receive_data:
    ; 接收数据部分, 等待RXNE=1
    btjf UART1_SR, #5, _receive_data

    ; 根据状态接收不同部分
    ld A, rx_state

    cp A, #0
    jreq _receive_header

    cp A, #4
    jreq _receive_length

    ld A, UART1_DR
_save_data:
    ld (X), A
    incw X
    inc rx_state

    dec rx_length
    jrne _receive_data  ; 还有数据，继续接收

    ; 数据接收完成
    mov rx_length, rx_state
    ret

_receive_header:
    ld A, UART1_DR
    cp A, #CMD_HEADER
    jrne _receive_data
    jra _save_data
_receive_length:
    ld A, UART1_DR
    cp A, #MAX_DATA_SIZE
    ; length<=MAX_DATA_SIZE
    jrugt receive_frame
    ; save length
    ld rx_length, A
    inc rx_length
    inc rx_length
    jra _save_data

verify_checksum:
    ; 初始化
    clr calc_checksum

    ; 计算需要校验的字节数
    ld A, rx_length
    dec A
    ld temp_var1, A

    ; 设置指针
    ldw X, #rx_buffer

_verify_loop:
    ld A, (X)
    xor A, calc_checksum
    ld calc_checksum, A
    incw X
    dec temp_var1 
    jrne _verify_loop

    ; 比较校验和
    ld A, calc_checksum
    cp A, (X)            ; X现在指向校验和位置

    ret

send_response_pkg:
    ; set header
    ldw X, #tx_buffer
    ld A, #ACK_HEADER
    ld (X), A

    ; tx_data_length += 5
    ld A, tx_data_length
    add A, #5
    ld temp_var1, A

    ; send data
    clr calc_checksum
_send_loop:
    ld A, (X)
    ld UART1_DR, A
    ; calc checksum
    xor A, calc_checksum
    ld calc_checksum, A
_wait_tx1:
    btjf UART1_SR, #7, _wait_tx1
    ; move to next
    incw X
    dec temp_var1
    jrne _send_loop

    ; send checksum
    ld A, calc_checksum
    ld UART1_DR, A
_wait_tx2:
    btjf UART1_SR, #7, _wait_tx2

    ; finish
    ret

; 发送应答状态帧
send_ack_state_response:
    ; set data
    ldw X, #tx_buffer+5
    ld (X), A

    ; set length
    decw X
    ld A, #1
    ld (X), A
    ld tx_data_length, A

    callr send_response_pkg
    ret

; 发送应答数据帧
send_ack_data_response:
    ; set length
    ldw X, #tx_buffer+4
    ld A, tx_data_length
    ld (X), A

    ; already set data
    callr send_response_pkg
    ret

read_memory:
    ; A = 读取长度 
    ldw X, #rx_buffer+5
    ld A, (X)
    ld tx_data_length, A
    ld temp_var1, A

    ; Y = 缓存地址
    ldw Y, X

    ; X = 读取地址
    ldw X, #rx_buffer+2
    ldw X, (X)

_read_loop:
    ; 读取字节
    ld A, (X)
    ld (Y), A

    incw X
    incw Y
    dec temp_var1
    jrne _read_loop

    callr send_ack_data_response
    ret

; temp_var1: 待写入长度
; temp_var2: FLASH_IAPSR
write_memory:
    ; A = 写入长度 
    ldw X, #rx_buffer+4
    ld A, (X)
    ld temp_var1, A
    ; 检查长度为0直接返回
    tnz A
    jreq _flash_write_success

    ; Y = src
    incw X
    ldw Y, X

    ; X = dst
    ldw X, #rx_buffer+2
    ldw X, (X)

    ; 检查是否为ram地址 (0x0000-0x3FFF)
    ld A, XH
    cp A, #0x40
    jrult _mem_write
    ; 检查是否为flash地址 (0x8000-0xFFFF)
    cp A, #0x80
    jruge _flash_write
    ; 检查是否为eeprom/opt地址 (0x4000-0x4FFF)
    cp A, #0x50
    jrult _flash_write

_mem_write:
    ld A, (Y)
    ld (X), A
    incw X
    incw Y
    dec temp_var1
    jrne _mem_write
    jra _flash_write_success

_flash_write:
    ; unlock FLASH/DATA
    callr unlock_flash

_flash_byte_write:
    ld A, (Y)
    ld (X), A
    ; Wait write done
_wait_flash_done:
    mov temp_var2, FLASH_IAPSR
    btjt   temp_var2, #0, _flash_write_error
    btjf   temp_var2, #2, _wait_flash_done
    incw X
    incw Y
    dec temp_var1
    jrne _flash_byte_write

    callr lock_flash
_flash_write_success:
    ld A, #SUCCESS_CODE
    call send_ack_state_response
    ret

_flash_write_error:
    callr lock_flash
    ld A, #ERR_PGDIS
    call send_ack_state_response
    ret

unlock_flash:
    ; 检查是否为Flash地址 (0x8000-0xFFFF)
    ld A, XH
    cp A, #0x80
    jrult _do_unlock_data
_do_unlock_flash:
    mov FLASH_PUKR, #0x56    ; KEY1
    mov FLASH_PUKR, #0xAE    ; KEY2
    ret
_do_unlock_data:
    mov FLASH_DUKR, #0xAE    ; KEY1
    mov FLASH_DUKR, #0x56    ; KEY2
    ; option byte programming on
    mov FLASH_CR2, #0x80
    mov FLASH_NCR2, #0x7F
    ret

lock_flash:
    ; 检查是否为Flash地址 (0x8000-0xFFFF)
    ld A, XH
    cp A, #0x80
    jrult _do_lock_data
_do_lock_flash:
    bres FLASH_IAPSR, #1
    ret
_do_lock_data:
    ; option byte programming off
    mov FLASH_CR2, #0x00
    mov FLASH_NCR2, #0xFF
    bres FLASH_IAPSR, #3
    ret

_end:
