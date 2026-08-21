#ifndef __DHT_H
#define __DHT_H

#include "stm32f10x.h"

/* DHT1 data pin: PB8 on the WildFire STM32F103 BaDao V2 board. */
void DHT_Init(void);
void DHT_Update(void);
uint8_t DHT_IsValid(void);
int16_t DHT_GetTemperature10(void);
uint16_t DHT_GetHumidity10(void);
const char *DHT_GetModel(void);
const char *DHT_GetStatus(void);

#endif
