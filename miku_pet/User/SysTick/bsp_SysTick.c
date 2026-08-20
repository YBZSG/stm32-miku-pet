#include "./SysTick/bsp_SysTick.h"

static __IO u32 TimingDelay;
static volatile uint32_t s_tick_ms = 0;

void SysTick_Init(void)
{
	if (SysTick_Config(SystemCoreClock / 1000))
	{ 
		while (1);
	}
}

void Delay_us(__IO u32 nTime)
{ 
	TimingDelay = nTime;	
	SysTick->CTRL |=  SysTick_CTRL_ENABLE_Msk;
	while(TimingDelay != 0);
}

void TimingDelay_Decrement(void)
{
	s_tick_ms++;
	if (TimingDelay != 0x00)
	{ 
		TimingDelay--;
	}
}

uint32_t SysTick_GetTick(void)
{
	return s_tick_ms;
}
