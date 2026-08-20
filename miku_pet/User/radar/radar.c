#include "./radar/radar.h"
#include <stdio.h>

static uint8_t s_ot1;
static uint8_t s_ot2;

void Radar_Init(void)
{
    GPIO_InitTypeDef gpio;
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOC, ENABLE);
    gpio.GPIO_Pin = GPIO_Pin_6 | GPIO_Pin_7;
    gpio.GPIO_Speed = GPIO_Speed_2MHz;
    gpio.GPIO_Mode = GPIO_Mode_IPD;
    GPIO_Init(GPIOC, &gpio);
    s_ot1 = GPIO_ReadInputDataBit(GPIOC, GPIO_Pin_6) ? 1 : 0;
    s_ot2 = GPIO_ReadInputDataBit(GPIOC, GPIO_Pin_7) ? 1 : 0;
    printf("RADAR_READY OT1=%u OT2=%u\r\n", s_ot1, s_ot2);
}

uint8_t Radar_OT1(void) { return GPIO_ReadInputDataBit(GPIOC, GPIO_Pin_6) ? 1 : 0; }
uint8_t Radar_OT2(void) { return GPIO_ReadInputDataBit(GPIOC, GPIO_Pin_7) ? 1 : 0; }

void Radar_Poll(void)
{
    uint8_t ot1 = Radar_OT1();
    uint8_t ot2 = Radar_OT2();
    if (ot1 != s_ot1 || ot2 != s_ot2) {
        s_ot1 = ot1; s_ot2 = ot2;
        printf("RADAR OT1=%u OT2=%u\r\n", ot1, ot2);
    }
}
