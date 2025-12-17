#ifndef _BOOTLOADER_H_
#define _BOOTLOADER_H_


#ifdef ENABLE_OPTION_BOOTLOADER
extern void bootloader_enter(void) __trap __naked;
#endif /* ENABLE_OPTION_BOOTLOADER */


#endif /* _BOOTLOADER_H_ */
