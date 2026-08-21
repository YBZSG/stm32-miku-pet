#ifndef __MPU6050_H
#define __MPU6050_H

#include "stm32f10x.h"

void MPU6050_Init(void);
void MPU6050_Update(void);
uint8_t MPU6050_IsValid(void);
int16_t MPU6050_GetAccelXmg(void);
int16_t MPU6050_GetAccelYmg(void);
int16_t MPU6050_GetAccelZmg(void);
int16_t MPU6050_GetGyroX10(void);
int16_t MPU6050_GetGyroY10(void);
int16_t MPU6050_GetGyroZ10(void);
int16_t MPU6050_GetPitch10(void);
int16_t MPU6050_GetRoll10(void);
const char *MPU6050_GetGesture(void);

#endif
