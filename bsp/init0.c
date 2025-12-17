/* Exec after reset  */
void bootloader_enter(void) __trap __naked {
__asm
    // ldw X, #0x03FF
    // ldw SP, X
    ldw X, #0x483F      ; [AE 48 3F]
    _cycle:
        decw X          ; [5A]
        push A          ; [88]
        ld A, (X)       ; [F6]
        jrne _cycle     ; [26 FB]
        // check 
        ldw X, SP       ; [96]
        addw X, #3      ; [1C 00 03]
        cpw X, (1,SP)   ; [13 01]
        jrne _exit      ; [26 01]
        // jump to ram
        ret             ; [81]
    _exit:
        jp 0x8004       ; [cc 80 04]
__endasm;
}
