#include "stm32f10x.h"
#include "./usart/bsp_usart.h"
#include "./lcd/bsp_ili9341_lcd.h"
#include "./pet/pet_player.h"
#include "./audio/vs1053_voice.h"
#include "./SysTick/bsp_SysTick.h"
#include "./lcd/bsp_xpt2046_lcd.h"
#include "./radar/radar.h"
#include "./wifi/esp8266_dashboard.h"
#include <stdio.h>

static void Bluetooth_USART_Config(void)
{
    GPIO_InitTypeDef gpio;
    USART_InitTypeDef usart;
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA, ENABLE);
    RCC_APB1PeriphClockCmd(RCC_APB1Periph_USART2, ENABLE);
    gpio.GPIO_Pin = GPIO_Pin_2;
    gpio.GPIO_Mode = GPIO_Mode_AF_PP;
    gpio.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(GPIOA, &gpio);
    gpio.GPIO_Pin = GPIO_Pin_3;
    gpio.GPIO_Mode = GPIO_Mode_IN_FLOATING;
    GPIO_Init(GPIOA, &gpio);
    usart.USART_BaudRate = 9600;
    usart.USART_WordLength = USART_WordLength_8b;
    usart.USART_StopBits = USART_StopBits_1;
    usart.USART_Parity = USART_Parity_No;
    usart.USART_HardwareFlowControl = USART_HardwareFlowControl_None;
    usart.USART_Mode = USART_Mode_Rx | USART_Mode_Tx;
    USART_Init(USART2, &usart);
    USART_Cmd(USART2, ENABLE);
}

int main(void)
{
    SysTick_Init();
    USART_Config();
    Bluetooth_USART_Config();
    ILI9341_Init();
    LCD_SetBackColor(0xF7BE);
    ILI9341_Clear(0, 0, LCD_X_LENGTH, LCD_Y_LENGTH);
    XPT2046_Init();
    Radar_Init();
    Calibrate_or_Get_TouchParaWithFlash(0, 0);
    ILI9341_GramScan(6);
    ILI9341_Clear(0, 0, LCD_X_LENGTH, LCD_Y_LENGTH);
    printf("\r\nMiku Pet pure animation player\r\n");
    PetPlayer_Init();
    PetPlayer_SetState(PET_IDLE);
    PetPlayer_Update(); /* 立刻绘制初音初始画面 */
    PetPlayer_PlayVoice(VOICE_BOOT); /* 开机播报: こんにちは、私の名前は初音ミクです! */
    ESP8266_DashboardInit();
    while (1)
        PetPlayer_Update();
}
