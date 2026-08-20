#ifndef __SYSTICK_H
#define __SYSTICK_H

#include "stm32f10x.h"

void SysTick_Init(void);
void Delay_us(__IO u32 nTime);
uint32_t SysTick_GetTick(void);

#define Delay_ms(x) Delay_us(x)

#endif /* __SYSTICK_H */
