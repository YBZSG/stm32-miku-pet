#include "./sensor/dht.h"
#include "./SysTick/bsp_SysTick.h"
#include "./pet/pet_player.h"
#include <stdio.h>

#define DHT_GPIO       GPIOB
#define DHT_PIN        GPIO_Pin_8
#define DHT_PERIOD_MS  2500UL
#define DHT_DWT_CTRL   (*((volatile uint32_t *)0xE0001000UL))
#define DHT_DWT_CYCCNT (*((volatile uint32_t *)0xE0001004UL))

static int16_t s_temperature10;
static uint16_t s_humidity10;
static uint32_t s_last_read;
static uint8_t s_valid;
static const char *s_model = "DHT11";
static const char *s_status = "WAITING";

static void DHT_DelayUs(uint32_t us)
{
    uint32_t start = DHT_DWT_CYCCNT;
    uint32_t ticks = (SystemCoreClock / 1000000UL) * us;
    while ((uint32_t)(DHT_DWT_CYCCNT - start) < ticks) {}
}

static void DHT_Output(void)
{
    GPIO_InitTypeDef gpio;
    gpio.GPIO_Pin = DHT_PIN;
    gpio.GPIO_Speed = GPIO_Speed_2MHz;
    gpio.GPIO_Mode = GPIO_Mode_Out_OD;
    GPIO_Init(DHT_GPIO, &gpio);
}

static void DHT_Input(void)
{
    GPIO_InitTypeDef gpio;
    gpio.GPIO_Pin = DHT_PIN;
    gpio.GPIO_Speed = GPIO_Speed_2MHz;
    gpio.GPIO_Mode = GPIO_Mode_IPU;
    GPIO_Init(DHT_GPIO, &gpio);
}

static uint8_t DHT_WaitWhile(uint8_t level, uint32_t timeout_us, uint32_t *width_us)
{
    uint32_t start = DHT_DWT_CYCCNT;
    uint32_t ticks_per_us = SystemCoreClock / 1000000UL;
    uint32_t timeout_ticks = ticks_per_us * timeout_us;
    while ((GPIO_ReadInputDataBit(DHT_GPIO, DHT_PIN) ? 1U : 0U) == level) {
        if ((uint32_t)(DHT_DWT_CYCCNT - start) >= timeout_ticks) return 0U;
    }
    if (width_us) *width_us = (uint32_t)(DHT_DWT_CYCCNT - start) / ticks_per_us;
    return 1U;
}

static uint8_t DHT_ReadFrame(uint8_t data[5])
{
    uint8_t i;
    uint32_t high_us;
    for (i = 0; i < 5U; i++) data[i] = 0U;

    DHT_Output();
    GPIO_ResetBits(DHT_GPIO, DHT_PIN);
    Delay_ms(20);
    GPIO_SetBits(DHT_GPIO, DHT_PIN);
    DHT_DelayUs(30);
    DHT_Input();

    if (!DHT_WaitWhile(1U, 120U, 0)) return 0U;
    if (!DHT_WaitWhile(0U, 120U, 0)) return 0U;
    if (!DHT_WaitWhile(1U, 120U, 0)) return 0U;

    for (i = 0; i < 40U; i++) {
        if (!DHT_WaitWhile(0U, 90U, 0)) return 0U;
        if (!DHT_WaitWhile(1U, 120U, &high_us)) return 0U;
        data[i / 8U] <<= 1;
        if (high_us > 45U) data[i / 8U] |= 1U;
    }
    return (uint8_t)(data[4] == (uint8_t)(data[0] + data[1] + data[2] + data[3]));
}

void DHT_Init(void)
{
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOB, ENABLE);
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DHT_DWT_CYCCNT = 0U;
    DHT_DWT_CTRL |= 1UL;
    DHT_Output();
    GPIO_SetBits(DHT_GPIO, DHT_PIN);
    s_last_read = SysTick_GetTick() - DHT_PERIOD_MS;
    printf("DHT_READY PB8\r\n");
}

void DHT_Update(void)
{
    uint8_t data[5];
    uint32_t now = SysTick_GetTick();
    if ((now - s_last_read) < DHT_PERIOD_MS) return;
    s_last_read = now;

    if (!DHT_ReadFrame(data)) {
        s_valid = 0U;
        s_status = "NO DATA";
        printf("DHT valid=0 status=NO_DATA\r\n");
        PetPlayer_RefreshDHTPage();
        return;
    }

    /* DHT11: integral humidity, decimal humidity, integral temperature,
       decimal temperature. Newer DHT11 revisions may provide a decimal. */
    s_humidity10 = (uint16_t)data[0] * 10U + (uint16_t)(data[1] % 10U);
    s_temperature10 = (int16_t)data[2] * 10 + (int16_t)(data[3] & 0x7FU);
    if (data[3] & 0x80U) s_temperature10 = -s_temperature10;
    s_valid = 1U;
    s_status = "OK";
    printf("DHT valid=1 model=%s temp10=%d hum10=%u\r\n",
           s_model, s_temperature10, s_humidity10);
    PetPlayer_RefreshDHTPage();
}

uint8_t DHT_IsValid(void) { return s_valid; }
int16_t DHT_GetTemperature10(void) { return s_temperature10; }
uint16_t DHT_GetHumidity10(void) { return s_humidity10; }
const char *DHT_GetModel(void) { return s_model; }
const char *DHT_GetStatus(void) { return s_status; }
