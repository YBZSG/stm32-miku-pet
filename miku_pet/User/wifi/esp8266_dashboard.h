#ifndef __ESP8266_DASHBOARD_H
#define __ESP8266_DASHBOARD_H

#include "stm32f10x.h"

uint8_t ESP8266_DashboardInit(void);
void ESP8266_DashboardPoll(void);
void ESP8266_FlushRx(void);

#endif
