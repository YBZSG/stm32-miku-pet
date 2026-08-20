#include "stm32f10x_it.h"
#include "./SysTick/bsp_SysTick.h"
#include "./lcd/bsp_xpt2046_lcd.h"
#include "./led/bsp_led.h"   
#include "./usart/bsp_usart.h"

extern void TimingDelay_Decrement(void);
extern void ESP8266_USART3_IRQHandler(void);

void NMI_Handler(void) {}
void HardFault_Handler(void) { while (1); }
void MemManage_Handler(void) { while (1); }
void BusFault_Handler(void) { while (1); }
void UsageFault_Handler(void) { while (1); }
void SVC_Handler(void) {}
void DebugMon_Handler(void) {}
void PendSV_Handler(void) {}

void SysTick_Handler(void)
{
	TimingDelay_Decrement();
}

void USART3_IRQHandler(void)
{
	ESP8266_USART3_IRQHandler();
}
