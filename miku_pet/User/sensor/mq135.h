#ifndef __MQ135_H
#define __MQ135_H

#include "stm32f10x.h"

void MQ135_Init(void);
void MQ135_Update(void);
uint16_t MQ135_GetRaw(void);
uint16_t MQ135_GetMillivolts(void);
uint8_t MQ135_GetQuality(void);
uint16_t MQ135_GetBaseline(void);
uint8_t MQ135_IsWarmingUp(void);
const char *MQ135_GetLevel(void);

#endif
