#ifndef __VS1053_VOICE_H
#define __VS1053_VOICE_H

#include "stm32f10x.h"

typedef enum {
    VOICE_WORKING = 0,
    VOICE_WAITING = 1,
    VOICE_FAILED = 2,
    VOICE_COMPLETE = 3,
    VOICE_BOOT = 4
} VoiceId;

void VS1053_VoiceInit(void);
uint8_t VS1053_PlayVoice(VoiceId voice);

#endif
