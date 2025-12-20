#include <stdint.h>
#include <stm8s.h>
#include <delay.h>
#include <bootloader.h>

#define LED_PIN     5

void main(void) {
    PB_DDR |= (1 << LED_PIN);
    PB_CR1 |= (1 << LED_PIN);

    /* 9600bps, 8N1, TEN, REN */
    UART1_BRR1 = 0x0D;
    UART1_BRR2 = 0x00;
    UART1_CR2 = 0x0C;

    while(1) {
        volatile uint8_t *ptr = (volatile uint8_t *)0x0230;
        delay_ms(2000);
        for(int i=0; i<16; i++) {
            for(int k=0; k<16; k++) {
                UART1_DR = *ptr++;
                while(!(UART1_SR&0x80));
            }
            delay_ms(100);
            PB_ODR ^= (1 << LED_PIN);
        }
    }

    while(1) {
        PB_ODR ^= (1 << LED_PIN);
        UART1_DR = PB_ODR;
        delay_ms(500);
    }
}
