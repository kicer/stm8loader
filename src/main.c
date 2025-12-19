#include <stdint.h>
#include <stm8s.h>
#include <delay.h>
#include <bootloader.h>

#define LED_PIN     5

void main(void) {
    PB_DDR |= (1 << LED_PIN);
    PB_CR1 |= (1 << LED_PIN);

    UART1_BRR1 = 0x0D;
    UART1_BRR2 = 0x00;
    UART1_CR2 = 0x0D;

    while(1) {
        PB_ODR ^= (1 << LED_PIN);
        UART1_DR = *ptr++;
        delay_ms(500);
    }
}
