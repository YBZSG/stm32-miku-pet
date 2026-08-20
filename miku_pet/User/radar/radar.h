#ifndef __RADAR_H
#define __RADAR_H
#include "stm32f10x.h"
void Radar_Init(void);
void Radar_Poll(void);
uint8_t Radar_OT1(void);
uint8_t Radar_OT2(void);
#endif
