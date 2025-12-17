#include <bootloader.h>

#ifdef ENABLE_OPTION_BOOTLOADER
void bootloader_enter(void) __trap __naked {
    /* Exec after reset  */
__asm
    ldw Y, SP           ; [90 96] 
    ldw X, #0x483F      ; [AE 48 3F]
    _cycle:
        decw X          ; [5A]
        push A          ; [88]
        ld A, (X)       ; [F6]
        jrne _cycle     ; [26 FB]
        // check address
        ldw X, SP       ; [96]
        addw X, #3      ; [1C 00 03]
        cpw X, (1,SP)   ; [13 01]
        jrne _exit      ; [26 01]
        // jump to ram
        ret             ; [81]
    _exit:
        ldw SP,Y        ; [90 94]
        jp 0x8004       ; [cc 80 04]
__endasm;
}
#endif /* ENABLE_OPTION_BOOTLOADER */
