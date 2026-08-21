#include "./sensor/mq135.h"
#include "./sensor/dht.h"
#include "./sensor/mpu6050.h"
#include "./SysTick/bsp_SysTick.h"
#include "./lcd/bsp_ili9341_lcd.h"
#include "./pet/pet_player.h"
#include <stdio.h>

#define MQ135_WARMUP_MS 180000UL

static uint16_t s_raw;
static uint16_t s_mv;
static uint8_t s_quality;
static uint32_t s_started_at;
static uint32_t s_last_update;
static uint8_t s_filter_ready;
static uint16_t s_baseline_raw;
static uint8_t s_warming = 1U;
static const char *s_level = "WARMUP";

static uint16_t MQ135_ReadAdc(void)
{
    uint8_t i;
    uint32_t sum = 0;
    for (i = 0; i < 16U; i++) {
        ADC_RegularChannelConfig(ADC1, ADC_Channel_1, 1, ADC_SampleTime_239Cycles5);
        ADC_SoftwareStartConvCmd(ADC1, ENABLE);
        while (ADC_GetFlagStatus(ADC1, ADC_FLAG_EOC) == RESET) {}
        sum += ADC_GetConversionValue(ADC1);
    }
    return (uint16_t)(sum / 16U);
}

void MQ135_Init(void)
{
    GPIO_InitTypeDef gpio;
    ADC_InitTypeDef adc;

    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA | RCC_APB2Periph_ADC1, ENABLE);
    RCC_ADCCLKConfig(RCC_PCLK2_Div6);

    gpio.GPIO_Pin = GPIO_Pin_1;
    gpio.GPIO_Speed = GPIO_Speed_2MHz;
    gpio.GPIO_Mode = GPIO_Mode_AIN;
    GPIO_Init(GPIOA, &gpio);

    ADC_DeInit(ADC1);
    adc.ADC_Mode = ADC_Mode_Independent;
    adc.ADC_ScanConvMode = DISABLE;
    adc.ADC_ContinuousConvMode = DISABLE;
    adc.ADC_ExternalTrigConv = ADC_ExternalTrigConv_None;
    adc.ADC_DataAlign = ADC_DataAlign_Right;
    adc.ADC_NbrOfChannel = 1;
    ADC_Init(ADC1, &adc);
    ADC_Cmd(ADC1, ENABLE);
    ADC_ResetCalibration(ADC1);
    while (ADC_GetResetCalibrationStatus(ADC1)) {}
    ADC_StartCalibration(ADC1);
    while (ADC_GetCalibrationStatus(ADC1)) {}

    s_started_at = SysTick_GetTick();
    s_last_update = s_started_at - 1000UL;
    printf("MQ135_READY PA1 ADC1_IN1\r\n");
    DHT_Init();
    MPU6050_Init();
}

void MQ135_Update(void)
{
    uint16_t sample;
    uint32_t now = SysTick_GetTick();
    const char *level;
    uint8_t warming;

    DHT_Update();
    MPU6050_Update();
    if ((now - s_last_update) < 1000UL) return;
    s_last_update = now;
    sample = MQ135_ReadAdc();
    if (!s_filter_ready) {
        s_raw = sample;
        s_filter_ready = 1U;
    } else {
        s_raw = (uint16_t)(((uint32_t)s_raw * 7U + sample) / 8U);
    }
    s_mv = (uint16_t)(((uint32_t)s_raw * 3300U) / 4095U);
    if (s_baseline_raw == 0U) s_baseline_raw = s_raw;
    if ((now - s_started_at) < MQ135_WARMUP_MS) {
        /* Learn a slowly moving clean-air baseline during the warm-up period. */
        s_baseline_raw = (uint16_t)(((uint32_t)s_baseline_raw * 31U + s_raw) / 32U);
    }
    if (s_raw <= s_baseline_raw) s_quality = 100U;
    else {
        uint32_t loss = ((uint32_t)(s_raw - s_baseline_raw) * 100U) /
                        (s_baseline_raw ? s_baseline_raw : 1U);
        s_quality = (uint8_t)(loss >= 100U ? 0U : 100U - loss);
    }
    warming = (now - s_started_at) < MQ135_WARMUP_MS;
    s_warming = warming;

    if (warming) level = "WARMUP";
    else if (s_quality >= 75U) level = "GOOD";
    else if (s_quality >= 50U) level = "FAIR";
    else if (s_quality >= 25U) level = "POOR";
    else level = "BAD";
    s_level = level;

    printf("MQ135 raw=%u mv=%u quality=%u level=%s warmup=%u baseline=%u delta=%d\r\n",
           s_raw, s_mv, s_quality, level, warming, s_baseline_raw,
           (int16_t)s_raw - (int16_t)s_baseline_raw);
    PetPlayer_RefreshAirPage();
}

uint16_t MQ135_GetRaw(void) { return s_raw; }
uint16_t MQ135_GetMillivolts(void) { return s_mv; }
uint8_t MQ135_GetQuality(void) { return s_quality; }
uint16_t MQ135_GetBaseline(void) { return s_baseline_raw; }
uint8_t MQ135_IsWarmingUp(void) { return s_warming; }
const char *MQ135_GetLevel(void) { return s_level; }
