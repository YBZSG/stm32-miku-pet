#include "./audio/vs1053_voice.h"
#include "./flash/bsp_spi_flash.h"
#include "./SysTick/bsp_SysTick.h"

#define VOICE_BASE 0x200000UL
#define VOICE_HEADER 64U

#define XCS_LO()   GPIO_ResetBits(GPIOB, GPIO_Pin_12)
#define XCS_HI()   GPIO_SetBits(GPIOB, GPIO_Pin_12)
#define XDCS_LO()  GPIO_ResetBits(GPIOE, GPIO_Pin_6)
#define XDCS_HI()  GPIO_SetBits(GPIOE, GPIO_Pin_6)
#define SCLK_LO()  GPIO_ResetBits(GPIOB, GPIO_Pin_13)
#define SCLK_HI()  GPIO_SetBits(GPIOB, GPIO_Pin_13)
#define MOSI_LO()  GPIO_ResetBits(GPIOB, GPIO_Pin_15)
#define MOSI_HI()  GPIO_SetBits(GPIOB, GPIO_Pin_15)

static volatile uint32_t s_voice_addr = 0;
static volatile uint32_t s_voice_remaining = 0;
static volatile uint8_t  s_voice_playing = 0;

static uint32_t U32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint8_t SpiByte(uint8_t out) {
    uint8_t i, in = 0;
    for (i = 0; i < 8; i++) {
        if (out & 0x80) MOSI_HI(); else MOSI_LO();
        SCLK_LO();
        __NOP(); __NOP();
        SCLK_HI();
        in = (uint8_t)((in << 1) | (GPIO_ReadInputDataBit(GPIOB, GPIO_Pin_14) ? 1 : 0));
        __NOP(); __NOP();
        out <<= 1;
    }
    return in;
}

static uint8_t WaitDreq(uint32_t n) {
    while (n-- && GPIO_ReadInputDataBit(GPIOE, GPIO_Pin_3) == Bit_RESET) {}
    return GPIO_ReadInputDataBit(GPIOE, GPIO_Pin_3) != Bit_RESET;
}

static void WriteSci(uint8_t reg, uint16_t v) {
    if (!WaitDreq(500000UL)) return;
    XCS_LO();
    SpiByte(2);
    SpiByte(reg);
    SpiByte((uint8_t)(v >> 8));
    SpiByte((uint8_t)v);
    XCS_HI();
}

static uint16_t ReadSci(uint8_t reg) {
    uint16_t v;
    if (!WaitDreq(500000UL)) return 0xFFFF;
    XCS_LO();
    SpiByte(3);
    SpiByte(reg);
    v = (uint16_t)SpiByte(0xFF) << 8;
    v |= SpiByte(0xFF);
    XCS_HI();
    return v;
}

static uint8_t EndFillByte(void) {
    WriteSci(7, 0x1E06);
    return (uint8_t)ReadSci(6);
}

static uint8_t SendBlock(uint8_t value) {
    uint8_t i;
    if (!WaitDreq(500000UL)) return 0;
    XDCS_LO();
    for (i = 0; i < 32; i++) SpiByte(value);
    XDCS_HI();
    return 1;
}

static void FinishStream(void) {
    uint8_t fill;
    uint16_t block;
    fill = EndFillByte();
    for (block = 0; block < 64; block++) {
        if (!SendBlock(fill)) break;
    }
    WriteSci(0x0B, 0xFEFE); /* Absolute Hardware Mute */
}

static void AudioPins(void) {
    GPIO_InitTypeDef g;
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOB | RCC_APB2Periph_GPIOC | RCC_APB2Periph_GPIOE, ENABLE);
    g.GPIO_Speed = GPIO_Speed_50MHz;
    g.GPIO_Mode = GPIO_Mode_Out_PP;
    g.GPIO_Pin = GPIO_Pin_12 | GPIO_Pin_13 | GPIO_Pin_15;
    GPIO_Init(GPIOB, &g);
    g.GPIO_Pin = GPIO_Pin_6;
    GPIO_Init(GPIOE, &g);
    g.GPIO_Pin = GPIO_Pin_3;
    GPIO_Init(GPIOC, &g);
    g.GPIO_Mode = GPIO_Mode_IPU;
    g.GPIO_Pin = GPIO_Pin_14;
    GPIO_Init(GPIOB, &g);
    g.GPIO_Pin = GPIO_Pin_3;
    GPIO_Init(GPIOE, &g);
    XCS_HI();
    XDCS_HI();
    SCLK_HI();
    MOSI_LO();
    GPIO_SetBits(GPIOC, GPIO_Pin_3);
}

void VS1053_VoiceInit(void) {
    AudioPins();
    GPIO_ResetBits(GPIOC, GPIO_Pin_3);
    Delay_ms(2);
    GPIO_SetBits(GPIOC, GPIO_Pin_3);
    Delay_ms(5);
    WriteSci(0, 0x0800);
    WriteSci(3, 0x9800);
    WriteSci(0x0B, 0xFEFE);
}

uint8_t VS1053_PlayVoice(VoiceId voice) {
    uint8_t h[VOICE_HEADER], buf[32], i;
    uint32_t addr, length, chunk;
    uint32_t safety;
    SPI_FLASH_BufferRead(h, VOICE_BASE, VOICE_HEADER);
    if (voice > VOICE_BOOT || h[0] != 'V' || h[1] != 'O' || h[2] != 'I' || h[3] != 'C') {
        FinishStream();
        return 0;
    }
    addr = VOICE_BASE + U32(h + 8 + (uint8_t)voice * 8);
    length = U32(h + 12 + (uint8_t)voice * 8);
    if (length == 0 || length > 1000000UL) {
        FinishStream();
        return 0;
    }
    AudioPins();
    GPIO_ResetBits(GPIOC, GPIO_Pin_3);
    Delay_ms(2);
    GPIO_SetBits(GPIOC, GPIO_Pin_3);
    Delay_ms(5);
    if (!WaitDreq(500000UL)) {
        FinishStream();
        return 0;
    }
    WriteSci(0, 0x0800);
    WriteSci(2, 0x7A00);    /* Treble + Vocal clarity booster */
    WriteSci(3, 0x9800);
    WriteSci(0x0B, 0x0000); /* 0.0dB attenuation = 100% MAX HARDWARE VOLUME */

    /* Dedicated smooth audio stream with 100% pause on animation */
    while (length) {
        chunk = length > 32 ? 32 : length;
        safety = 500000UL;
        while (safety-- && GPIO_ReadInputDataBit(GPIOE, GPIO_Pin_3) == Bit_RESET) {}
        if (safety == 0) break;
        SPI_FLASH_BufferRead(buf, addr, (uint16_t)chunk);
        XDCS_LO();
        for (i = 0; i < chunk; i++) SpiByte(buf[i]);
        XDCS_HI();
        addr += chunk;
        length -= chunk;
    }
    FinishStream();
    return 1;
}
