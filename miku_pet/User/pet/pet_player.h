#ifndef __PET_PLAYER_H
#define __PET_PLAYER_H

#include "stm32f10x.h"

typedef enum {
    PET_IDLE = 0, PET_RUN_RIGHT, PET_RUN_LEFT, PET_WAVE, PET_JUMP,
    PET_FAILED, PET_WAITING, PET_WORKING, PET_REVIEW,
    PET_LOOK_0_157, PET_LOOK_180_337
} PetState;

typedef enum {
    PET_WIFI_OFF = 0,
    PET_WIFI_CONNECTING,
    PET_WIFI_READY,
    PET_WIFI_AT_ERROR,
    PET_WIFI_JOIN_ERROR,
    PET_WIFI_UDP_ERROR
} PetWifiStatus;

typedef enum {
    DASHBOARD_MODE_AI = 1,
    DASHBOARD_MODE_WEATHER = 2,
    DASHBOARD_MODE_MESSAGE = 3,
    DASHBOARD_MODE_GEEK = 4,
    DASHBOARD_MODE_AIR = 5,
    DASHBOARD_MODE_DHT = 6,
    DASHBOARD_MODE_MPU = 7
} DashboardMode;

uint8_t PetPlayer_Init(void);
void PetPlayer_ApplyDashboardFrame(const uint8_t *frame);
void PetPlayer_SetWifiStatus(PetWifiStatus status);
void PetPlayer_SetWifiDiagnostic(uint32_t rx_count, const char *last_rx);
void PetPlayer_SetWifiBaud(uint32_t baud);
void PetPlayer_SetWifiProbe(uint8_t index, uint32_t baud, uint16_t rx_count, uint8_t result);
void PetPlayer_SetWifiProbeHex(uint8_t index, const uint8_t *bytes, uint8_t count);
void PetPlayer_SetState(PetState state);
void PetPlayer_SetMode(DashboardMode mode);
void PetPlayer_RefreshAirPage(void);
void PetPlayer_RefreshDHTPage(void);
void PetPlayer_RefreshMPUPage(void);
void PetPlayer_PlayVoice(uint8_t voice_id);
void PetPlayer_Update(void);
void PetPlayer_PollSerial(void);
void PetPlayer_OnTouch(int16_t x, int16_t y, uint8_t pressed);

#endif
