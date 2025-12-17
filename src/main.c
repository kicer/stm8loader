#include <stdint.h>
#include <stm8s.h>
#include <delay.h>

#define LED_PIN     5

void main(void) {
    PB_DDR |= (1 << LED_PIN);
    PB_CR1 |= (1 << LED_PIN);

    while (1) {
        PB_ODR ^= (1 << LED_PIN);
        delay_ms(1000);
    }
}
