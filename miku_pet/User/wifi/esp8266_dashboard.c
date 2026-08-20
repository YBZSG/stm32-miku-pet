#include "./wifi/esp8266_dashboard.h"
#include "./pet/pet_player.h"
#include "./SysTick/bsp_SysTick.h"
#include "pet_wifi_config.h"
#include <stdio.h>
#include <string.h>

#define WIFI_USART USART3
#define WIFI_UDP_PORT 43210U
#define WIFI_RX_BUF_SIZE 2048U

static volatile uint8_t s_wifi_rx_buf[WIFI_RX_BUF_SIZE];
static volatile uint16_t s_wifi_rx_head = 0;
static volatile uint16_t s_wifi_rx_tail = 0;

static uint8_t s_frame[64];
static uint8_t s_frame_pos;
static uint32_t s_diag_rx_count;
static char s_diag_last[13];
static uint8_t s_diag_used;
static uint8_t s_last_wait_error;
static uint8_t s_probe_bytes[16];
static uint8_t s_probe_byte_count;
static uint8_t s_probe_capture;

static void WifiRecordByte(uint8_t value)
{
    s_diag_rx_count++;
    if (s_diag_used < sizeof(s_diag_last) - 1U) s_diag_last[s_diag_used++] = (char)value;
    else {
        memmove(s_diag_last, s_diag_last + 1, sizeof(s_diag_last) - 2U);
        s_diag_last[sizeof(s_diag_last) - 2U] = (char)value;
        s_diag_used = sizeof(s_diag_last) - 1U;
    }
    s_diag_last[s_diag_used] = 0;
    if (s_probe_capture && s_probe_byte_count < sizeof(s_probe_bytes))
        s_probe_bytes[s_probe_byte_count++] = value;
}

void ESP8266_USART3_IRQHandler(void)
{
    if (USART_GetFlagStatus(WIFI_USART, USART_FLAG_ORE) != RESET) {
        (void)WIFI_USART->SR;
        (void)WIFI_USART->DR;
    }
    if (USART_GetITStatus(WIFI_USART, USART_IT_RXNE) != RESET)
    {
        uint8_t value = (uint8_t)USART_ReceiveData(WIFI_USART);
        uint16_t next = (uint16_t)((s_wifi_rx_head + 1U) % WIFI_RX_BUF_SIZE);
        if (next != s_wifi_rx_tail) {
            s_wifi_rx_buf[s_wifi_rx_head] = value;
            s_wifi_rx_head = next;
        }
        WifiRecordByte(value);
    }
}

void ESP8266_FlushRx(void)
{
    __disable_irq();
    s_wifi_rx_tail = s_wifi_rx_head;
    s_frame_pos = 0;
    __enable_irq();
}

static void WifiFlushRx(void)
{
    ESP8266_FlushRx();
}

static uint8_t WifiReadByte(uint8_t *ch)
{
    if (s_wifi_rx_tail == s_wifi_rx_head) return 0;
    *ch = s_wifi_rx_buf[s_wifi_rx_tail];
    s_wifi_rx_tail = (uint16_t)((s_wifi_rx_tail + 1U) % WIFI_RX_BUF_SIZE);
    return 1;
}

static void WifiSetBaud(uint32_t baud)
{
    USART_InitTypeDef usart;
    USART_Cmd(WIFI_USART, DISABLE);
    usart.USART_BaudRate = baud;
    usart.USART_WordLength = USART_WordLength_8b;
    usart.USART_StopBits = USART_StopBits_1;
    usart.USART_Parity = USART_Parity_No;
    usart.USART_HardwareFlowControl = USART_HardwareFlowControl_None;
    usart.USART_Mode = USART_Mode_Rx | USART_Mode_Tx;
    USART_Init(WIFI_USART, &usart);
    USART_ITConfig(WIFI_USART, USART_IT_RXNE, ENABLE);
    USART_Cmd(WIFI_USART, ENABLE);
}

static void WifiSend(const char *text)
{
    while (*text) {
        USART_SendData(WIFI_USART, (uint8_t)*text++);
        while (USART_GetFlagStatus(WIFI_USART, USART_FLAG_TXE) == RESET) {}
    }
}

static uint8_t WifiWait(const char *wanted, uint32_t timeout_ms)
{
    char window[64];
    uint8_t used = 0;
    uint32_t start = SysTick_GetTick();
    s_last_wait_error = 0;
    memset(window, 0, sizeof(window));

    while ((SysTick_GetTick() - start) < timeout_ms) {
        uint8_t b;
        while (WifiReadByte(&b)) {
            char ch = (char)b;
            if (used < sizeof(window) - 1U) {
                window[used++] = ch;
            } else {
                memmove(window, window + 1, sizeof(window) - 2U);
                window[sizeof(window) - 2U] = ch;
                used = sizeof(window) - 1U;
            }
            window[used] = 0;
            if (strstr(window, wanted)) return 1;
            if (strstr(window, "ERROR") || strstr(window, "FAIL")) {
                s_last_wait_error = 1;
                return 0;
            }
        }
    }
    return 0;
}

static uint8_t WifiCommand(const char *command, const char *answer, uint32_t timeout_ms)
{
    WifiFlushRx();
    WifiSend(command);
    WifiSend("\r\n");
    return WifiWait(answer, timeout_ms);
}

static void WifiExitTransparentMode(void)
{
    Delay_us(1000);
    WifiSend("+++");
    Delay_us(1000);
    WifiFlushRx();
}

static void WifiHardwareInit(void)
{
    GPIO_InitTypeDef gpio;
    NVIC_InitTypeDef nvic;

    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOB | RCC_APB2Periph_GPIOG, ENABLE);
    RCC_APB1PeriphClockCmd(RCC_APB1Periph_USART3, ENABLE);

    gpio.GPIO_Pin = GPIO_Pin_10;
    gpio.GPIO_Mode = GPIO_Mode_AF_PP;
    gpio.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(GPIOB, &gpio);
    gpio.GPIO_Pin = GPIO_Pin_11;
    gpio.GPIO_Mode = GPIO_Mode_IN_FLOATING;
    GPIO_Init(GPIOB, &gpio);

    gpio.GPIO_Pin = GPIO_Pin_13 | GPIO_Pin_14;
    gpio.GPIO_Mode = GPIO_Mode_Out_PP;
    gpio.GPIO_Speed = GPIO_Speed_2MHz;
    GPIO_Init(GPIOG, &gpio);

    NVIC_PriorityGroupConfig(NVIC_PriorityGroup_2);
    nvic.NVIC_IRQChannel = USART3_IRQn;
    nvic.NVIC_IRQChannelPreemptionPriority = 1;
    nvic.NVIC_IRQChannelSubPriority = 2;
    nvic.NVIC_IRQChannelCmd = ENABLE;
    NVIC_Init(&nvic);

    GPIO_SetBits(GPIOG, GPIO_Pin_14);  /* RST = High */
    GPIO_ResetBits(GPIOG, GPIO_Pin_13);/* CH_PD = Low */
    WifiSetBaud(115200);
    Delay_us(50);
    GPIO_SetBits(GPIOG, GPIO_Pin_13);  /* CH_PD = High */
    Delay_us(1500);
    WifiFlushRx();
}

static void WifiHardReset(void)
{
    GPIO_ResetBits(GPIOG, GPIO_Pin_14);
    Delay_us(200);
    GPIO_SetBits(GPIOG, GPIO_Pin_14);
    Delay_us(1500);
    WifiFlushRx();
}

uint8_t ESP8266_DashboardInit(void)
{
    char command[160];
    static const uint32_t baud_list[] = {
        115200UL, 9600UL, 57600UL, 38400UL, 19200UL, 74880UL
    };
    uint8_t baud_index, attempt, at_ok = 0;
    uint32_t active_baud = 0;
    uint32_t rx_before;
    uint16_t probe_rx;

    PetPlayer_SetWifiStatus(PET_WIFI_CONNECTING);
    WifiHardwareInit();

    for (baud_index = 0; baud_index < sizeof(baud_list) / sizeof(baud_list[0]); baud_index++) {
        WifiSetBaud(baud_list[baud_index]);
        Delay_us(50);
        rx_before = s_diag_rx_count;
        s_probe_byte_count = 0;
        s_probe_capture = 1;
        for (attempt = 0; attempt < 2; attempt++) {
            if (WifiCommand("AT", "OK", 200)) {
                at_ok = 1;
                active_baud = baud_list[baud_index];
                break;
            }
            Delay_us(50);
        }
        probe_rx = (uint16_t)(s_diag_rx_count - rx_before);
        s_probe_capture = 0;
        PetPlayer_SetWifiProbe(baud_index, baud_list[baud_index], probe_rx,
                               at_ok ? 1U : (s_last_wait_error ? 2U : 0U));
        PetPlayer_SetWifiProbeHex(baud_index, s_probe_bytes, s_probe_byte_count);
        if (at_ok) break;
    }
    if (!at_ok) {
        WifiSetBaud(115200);
        WifiExitTransparentMode();
        WifiHardReset();
        for (baud_index = 0; baud_index < sizeof(baud_list) / sizeof(baud_list[0]); baud_index++) {
            WifiSetBaud(baud_list[baud_index]);
            Delay_us(50);
            rx_before = s_diag_rx_count;
            s_probe_byte_count = 0;
            s_probe_capture = 1;
            for (attempt = 0; attempt < 2; attempt++) {
                if (WifiCommand("AT", "OK", 200)) {
                    at_ok = 1;
                    active_baud = baud_list[baud_index];
                    break;
                }
                Delay_us(50);
            }
            probe_rx = (uint16_t)(s_diag_rx_count - rx_before);
            s_probe_capture = 0;
            PetPlayer_SetWifiProbe(baud_index, baud_list[baud_index], probe_rx,
                                   at_ok ? 1U : (s_last_wait_error ? 2U : 0U));
            PetPlayer_SetWifiProbeHex(baud_index, s_probe_bytes, s_probe_byte_count);
            if (at_ok) break;
        }
    }
    if (!at_ok) {
        PetPlayer_SetWifiDiagnostic(s_diag_rx_count, s_diag_last);
        PetPlayer_SetWifiStatus(PET_WIFI_AT_ERROR);
        printf("WIFI_AT_FAIL\r\n");
        return 0;
    }
    PetPlayer_SetWifiBaud(active_baud);
    printf("WIFI_AT_OK %lu\r\n", active_baud);
    WifiCommand("ATE0", "OK", 1000);
    if (!WifiCommand("AT+CWMODE=1", "OK", 1500)) {
        PetPlayer_SetWifiStatus(PET_WIFI_AT_ERROR);
        printf("WIFI_MODE_FAIL\r\n");
        return 0;
    }
    sprintf(command, "AT+CWJAP=\"%s\",\"%s\"", PET_WIFI_SSID, PET_WIFI_PASSWORD);
    if (!WifiCommand(command, "OK", 20000)) {
        PetPlayer_SetWifiStatus(PET_WIFI_JOIN_ERROR);
        printf("WIFI_JOIN_FAIL\r\n");
        return 0;
    }
    WifiCommand("AT+CIPCLOSE", "OK", 1000);
    sprintf(command, "AT+CIPSTART=\"UDP\",\"255.255.255.255\",%u,%u,2",
            WIFI_UDP_PORT, WIFI_UDP_PORT);
    if (!WifiCommand(command, "OK", 5000) &&
        !WifiWait("ALREADY CONNECTED", 1000)) {
        PetPlayer_SetWifiStatus(PET_WIFI_UDP_ERROR);
        printf("WIFI_UDP_FAIL\r\n");
        return 0;
    }
    PetPlayer_SetWifiStatus(PET_WIFI_READY);
    printf("WIFI_READY UDP %u\r\n", WIFI_UDP_PORT);
    return 1;
}

void ESP8266_DashboardPoll(void)
{
    uint8_t value;
    while (WifiReadByte(&value)) {
        if (s_frame_pos == 0U) {
            if (value == 0xA5U) s_frame[s_frame_pos++] = value;
        } else if (s_frame_pos == 1U) {
            if (value == 0x5AU) s_frame[s_frame_pos++] = value;
            else s_frame_pos = (value == 0xA5U) ? 1U : 0U;
        } else {
            s_frame[s_frame_pos++] = value;
            if (s_frame_pos == sizeof(s_frame)) {
                PetPlayer_ApplyDashboardFrame(s_frame);
                s_frame_pos = 0;
            }
        }
    }
}
