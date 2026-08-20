#include "./pet/pet_player.h"
#include "./flash/bsp_spi_flash.h"
#include "./lcd/bsp_ili9341_lcd.h"
#include "./usart/bsp_usart.h"
#include "./SysTick/bsp_SysTick.h"
#include "./lcd/bsp_xpt2046_lcd.h"
#include "./font/fonts.h"
#include "./audio/vs1053_voice.h"
#include "./radar/radar.h"
#include "./wifi/esp8266_dashboard.h"
#include <stdio.h>
#include <string.h>

#define PET_FLASH_BASE       0x000000UL
#define PET_VALID_MARKER     0x7FF000UL
#define VOICE_FLASH_BASE     0x200000UL
#define PET_HEADER_SIZE      20U
#define PET_ENTRY_SIZE       16U
#define PET_MAX_FRAME_BYTES  19000U
#define LCD_CMD_REG          (*((volatile uint16_t *)0x6C000000UL))
#define LCD_DATA_REG         (*((volatile uint16_t *)0x6D000000UL))

static const uint8_t s_frame_counts[11] = {7,8,8,4,5,8,12,8,6,8,8};
/* WORKING uses the normalized right-running animation row. */
static const uint8_t s_first_frames[11] = {0,7,15,23,27,32,40,7,52,58,66};
static uint8_t s_frame_data[PET_MAX_FRAME_BYTES];
static PetState s_state = PET_IDLE;
static DashboardMode s_dashboard_mode = DASHBOARD_MODE_AI;
static DashboardMode s_last_drawn_mode = DASHBOARD_MODE_AI;
static uint8_t s_frame = 0;
static uint16_t s_width = 0;
static uint16_t s_height = 0;
static uint8_t s_ready = 0;
static uint8_t s_touch_active = 0;
static uint16_t s_touch_hold_ms = 0;
static uint8_t s_touch_one_shot = 0;
static uint8_t s_dashboard_dirty = 1;
static volatile uint8_t s_state_changed = 0;
static uint8_t s_usage_valid = 0;
static uint8_t s_remaining_percent = 0;
static uint32_t s_total_tokens = 0;
static uint32_t s_reset_minutes = 0;
static char s_session_title[40] = "STM32 PET";
static uint32_t s_dashboard_session = 0;
static uint32_t s_dashboard_sequence = 0;
static uint8_t s_chinese_ui = 0;
static uint8_t s_facing_left = 0;
static PetWifiStatus s_wifi_status = PET_WIFI_OFF;
static uint32_t s_wifi_rx_count = 0;
static char s_wifi_last_rx[13] = "-";
static uint32_t s_wifi_baud = 0;
static uint32_t s_probe_baud[6];
static uint16_t s_probe_rx[6];
static uint8_t s_probe_result[6];
static char s_probe_hex[6][9];

/* Mode 2: Weather & Clock fields */
static char s_weather_date[16] = "2026-08-17";
static char s_weather_time[16] = "12:00:00";
static char s_weather_info[24] = "Sunny 26C";
static char s_weather_tip[24] = "Daily Clock";

/* Mode 3: Custom Message Memo */
static char s_memo_sender[16] = "WEB";
static char s_memo_text1[30] = "Drink water & rest!";
static char s_memo_text2[30] = "";

/* Mode 4: Pomodoro & Geek */
static uint32_t s_pomo_seconds = 1500;
static uint32_t s_geek_commits = 0;
static uint32_t s_geek_stars = 0;

static const char *s_wifi_names[6] = {"OFF ", "JOIN", "OK  ", "AT! ", "KEY!", "UDP!"};
static const char *s_state_names[11] = {
    "IDLE", "RUN RIGHT", "RUN LEFT", "WAVING", "JUMPING",
    "FAILED", "WAITING", "WORKING", "REVIEWING", "LOOK RIGHT", "LOOK LEFT"
};
static const char *s_state_names_zh[11] = {
    "\xB4\xFD\xBB\xFA", "\xCF\xF2\xD3\xD2\xC5\xDC", "\xCF\xF2\xD7\xF3\xC5\xDC",
    "\xBB\xD3\xCA\xD6", "\xCC\xF8\xD4\xBE", "\xCA\xA7\xB0\xDC",
    "\xB5\xC8\xB4\xFD", "\xB9\xA4\xD7\xF7\xD6\xD0", "\xC9\xF3\xD4\xC4",
    "\xCF\xF2\xD3\xD2\xBF\xB4", "\xCF\xF2\xD7\xF3\xBF\xB4"
};
static uint32_t ReadU32(const uint8_t *p);

static void DrawWifiBadge(void)
{
    char line[24];
    uint16_t color = GREY;
    if (s_wifi_status == PET_WIFI_CONNECTING) color = YELLOW;
    else if (s_wifi_status == PET_WIFI_READY) color = GREEN;
    else if (s_wifi_status >= PET_WIFI_AT_ERROR) color = RED;
    
    LCD_SetFont(&Font8x16);
    LCD_SetBackColor(0xF7BE);
    LCD_SetTextColor(color);
    ILI9341_DrawCircle(151, 13, 4, 1);
    LCD_SetTextColor(0x2104);
    sprintf(line, "WIFI:%-4s", s_wifi_names[s_wifi_status]);
    ILI9341_DispString_EN(160, 6, line);
    if (s_wifi_status == PET_WIFI_AT_ERROR) {
        sprintf(line, "RX:%-5lu", s_wifi_rx_count);
        ILI9341_DispString_EN(136, 26, line);
        sprintf(line, "%-10s", s_wifi_last_rx);
        ILI9341_DispString_EN(136, 46, line);
    } else if (s_wifi_status == PET_WIFI_READY && s_wifi_baud) {
        sprintf(line, "%-8lu", s_wifi_baud);
        ILI9341_DispString_EN(168, 26, line);
    }
}

void PetPlayer_SetWifiBaud(uint32_t baud)
{
    s_wifi_baud = baud;
    s_dashboard_dirty = 1;
}

void PetPlayer_SetWifiProbe(uint8_t index, uint32_t baud, uint16_t rx_count, uint8_t result)
{
    if (index >= 6U) return;
    s_probe_baud[index] = baud;
    s_probe_rx[index] = rx_count;
    s_probe_result[index] = result;
}

void PetPlayer_SetWifiProbeHex(uint8_t index, const uint8_t *bytes, uint8_t count)
{
    static const char hex[] = "0123456789ABCDEF";
    uint8_t i, start;
    if (index >= 6U) return;
    start = count > 4U ? (uint8_t)(count - 4U) : 0U;
    for (i = 0; i < 4U && (uint8_t)(start + i) < count; i++) {
        uint8_t value = bytes[start + i];
        s_probe_hex[index][i * 2U] = hex[value >> 4];
        s_probe_hex[index][i * 2U + 1U] = hex[value & 15U];
    }
    s_probe_hex[index][i * 2U] = 0;
}

static void DrawWifiProbeTable(void)
{
    char line[32];
    uint8_t i;
    LCD_SetFont(&Font8x16);
    LCD_SetBackColor(0xF7BE);
    LCD_SetTextColor(0x2104);
    ILI9341_DispString_EN(8, 76, "WIFI BAUD DIAGNOSTIC     ");
    for (i = 0; i < 6U; i++) {
        const char *result = s_probe_result[i] == 1U ? "OK " :
                             s_probe_result[i] == 2U ? "ERR" : "TO ";
        sprintf(line, "%-6lu %2u %-3s %-8s", s_probe_baud[i], s_probe_rx[i], result,
                s_probe_hex[i]);
        ILI9341_DispString_EN(8, (uint16_t)(96U + i * 16U), line);
    }
}

void PetPlayer_SetWifiStatus(PetWifiStatus status)
{
    PetWifiStatus old_status = s_wifi_status;
    if (status > PET_WIFI_UDP_ERROR) status = PET_WIFI_OFF;
    s_wifi_status = status;
    s_dashboard_dirty = 1;
    if (old_status == PET_WIFI_AT_ERROR && status != PET_WIFI_AT_ERROR) {
        LCD_SetBackColor(0xF7BE);
        ILI9341_Clear(8, 76, 224, 112);
    } else if (status == PET_WIFI_AT_ERROR) {
        DrawWifiProbeTable();
    }
}

void PetPlayer_SetWifiDiagnostic(uint32_t rx_count, const char *last_rx)
{
    uint8_t i = 0;
    s_wifi_rx_count = rx_count;
    while (last_rx && last_rx[i] && i < sizeof(s_wifi_last_rx) - 1U) {
        char ch = last_rx[i];
        s_wifi_last_rx[i] = (ch >= 32 && ch <= 126) ? ch : '.';
        i++;
    }
    s_wifi_last_rx[i] = 0;
}

void PetPlayer_SetMode(DashboardMode mode)
{
    if (s_dashboard_mode != mode) {
        s_dashboard_mode = mode;
        s_dashboard_dirty = 1;
    }
}

void PetPlayer_PlayVoice(uint8_t voice_id)
{
    if (voice_id <= 4) {
        VS1053_PlayVoice((VoiceId)voice_id);
        s_dashboard_dirty = 1;
        ESP8266_FlushRx();
    }
}

static uint8_t ParseDashboardPacket(const char *packet, uint32_t values[4])
{
    uint8_t field = 0;
    uint8_t has_digit = 0;
    char ch;
    values[0] = values[1] = values[2] = values[3] = 0;
    while ((ch = *packet++) != 0) {
        if (ch >= '0' && ch <= '9') {
            values[field] = values[field] * 10UL + (uint32_t)(ch - '0');
            has_digit = 1;
        } else if (ch == ',' && has_digit && field < 3) {
            field++;
            has_digit = 0;
        } else {
            return 0;
        }
    }
    return field == 3 && has_digit;
}

static void DrawDashboard(void)
{
    char line[40];
    LCD_SetFont(&Font8x16);
    LCD_SetBackColor(0xF7BE);
    LCD_SetTextColor(0x2104);
    
    /* If mode switched, wipe the old bottom area once to guarantee zero residual text */
    if (s_dashboard_mode != s_last_drawn_mode) {
        s_last_drawn_mode = s_dashboard_mode;
        ILI9341_Clear(0, 232, LCD_X_LENGTH, 88);
    }
    
    /* Top Bar: y = 6, 30, 54 */
    if (s_dashboard_mode == DASHBOARD_MODE_WEATHER) {
        ILI9341_DispString_EN(8, 6, "DESK CLOCK  ");
        sprintf(line, "DATE: %-18s", s_weather_date);
        ILI9341_DispString_EN(8, 30, line);
        sprintf(line, "TIME: %-18s", s_weather_time);
        ILI9341_DispString_EN(8, 54, line);
    } else if (s_dashboard_mode == DASHBOARD_MODE_MESSAGE) {
        ILI9341_DispString_EN(8, 6, "MEMO BOARD  ");
        sprintf(line, "FROM: %-18s", s_memo_sender);
        ILI9341_DispString_EN_CH(8, 30, line);
        sprintf(line, "STATUS: %-16s", s_state_names[s_state]);
        ILI9341_DispString_EN(8, 54, line);
    } else if (s_dashboard_mode == DASHBOARD_MODE_GEEK) {
        ILI9341_DispString_EN(8, 6, "GEEK STATS  ");
        sprintf(line, "POMO: %02lu:%02lu min      ", s_pomo_seconds / 60, s_pomo_seconds % 60);
        ILI9341_DispString_EN(8, 30, line);
        sprintf(line, "STATE: %-17s", s_state_names[s_state]);
        ILI9341_DispString_EN(8, 54, line);
    } else {
        /* DASHBOARD_MODE_AI */
        if (s_chinese_ui) {
            ILI9341_DispString_EN(8, 6, "CODEX PET   ");
            ILI9341_DispString_EN_CH(8, 30, "\xD7\xB4\xCC\xAC:");
            sprintf(line, "%-16s", s_state_names_zh[s_state]);
            ILI9341_DispString_EN_CH(56, 30, line);
            ILI9341_DispString_EN_CH(8, 54, "\xBB\xE1\xBB\xB0:");
            sprintf(line, "%-22s", s_session_title);
            ILI9341_DispString_EN_CH(56, 54, line);
        } else {
            ILI9341_DispString_EN(8, 6, "CODEX PET   ");
            sprintf(line, "STATUS: %-18s", s_state_names[s_state]);
            ILI9341_DispString_EN(8, 30, line);
            ILI9341_DispString_EN(8, 54, "CHAT:");
            sprintf(line, "%-22s", s_session_title);
            ILI9341_DispString_EN_CH(56, 54, line);
        }
    }
    DrawWifiBadge();

    /* Bottom Bar: strictly unified at y = 238, 262, 286 */
    if (s_dashboard_mode == DASHBOARD_MODE_WEATHER) {
        sprintf(line, "WEATHER: %-19s", s_weather_info);
        ILI9341_DispString_EN_CH(8, 238, line);
        sprintf(line, "STATUS:  %-19s", s_weather_tip);
        ILI9341_DispString_EN_CH(8, 262, line);
        ILI9341_DispString_EN(8, 286, "HAVE A NICE DAY!            ");
    } else if (s_dashboard_mode == DASHBOARD_MODE_MESSAGE) {
        sprintf(line, "%-28s", s_memo_text1);
        ILI9341_DispString_EN_CH(8, 238, line);
        sprintf(line, "%-28s", s_memo_text2);
        ILI9341_DispString_EN_CH(8, 262, line);
        ILI9341_DispString_EN_CH(8, 286, "[NEW MESSAGE RECEIVED]      ");
    } else if (s_dashboard_mode == DASHBOARD_MODE_GEEK) {
        sprintf(line, "COMMITS: %-6lu STARS:%-5lu", s_geek_commits, s_geek_stars);
        ILI9341_DispString_EN(8, 238, line);
        ILI9341_DispString_EN(8, 262, "FOCUS MODE ACTIVE           ");
        ILI9341_DispString_EN(8, 286, "KEEP CODING & WIN!          ");
    } else {
        /* DASHBOARD_MODE_AI */
        if (s_usage_valid) {
            if (s_chinese_ui) {
                sprintf(line, "TOKENS: %-19lu", s_total_tokens);
                ILI9341_DispString_EN(8, 238, line);
                ILI9341_DispString_EN_CH(8, 262, "\xCA\xA3\xD3\xE0:");
                sprintf(line, "%-4u%%              ", s_remaining_percent);
                ILI9341_DispString_EN(56, 262, line);
                ILI9341_DispString_EN_CH(8, 286, "\xD6\xD8\xD6\xC3:");
                sprintf(line, "%-2luh %02lum            ", s_reset_minutes / 60, s_reset_minutes % 60);
                ILI9341_DispString_EN(56, 286, line);
            } else {
                sprintf(line, "TOKENS: %-20lu", s_total_tokens);
                ILI9341_DispString_EN(8, 238, line);
                sprintf(line, "REMAIN: %-4u%%            ", s_remaining_percent);
                ILI9341_DispString_EN(8, 262, line);
                sprintf(line, "RESET:  %-2luh %02lum          ", s_reset_minutes / 60, s_reset_minutes % 60);
                ILI9341_DispString_EN(8, 286, line);
            }
        } else {
            if (s_chinese_ui) {
                ILI9341_DispString_EN(8, 238, "TOKENS: --                  ");
                ILI9341_DispString_EN_CH(8, 262, "\xCA\xA3\xD3\xE0:");
                ILI9341_DispString_EN(56, 262, "--                    ");
                ILI9341_DispString_EN_CH(8, 286, "\xD6\xD8\xD6\xC3:");
                ILI9341_DispString_EN(56, 286, "--                    ");
            } else {
                ILI9341_DispString_EN(8, 238, "TOKENS: --                  ");
                ILI9341_DispString_EN(8, 262, "REMAIN: --                  ");
                ILI9341_DispString_EN(8, 286, "RESET:  --                  ");
            }
        }
    }
    s_dashboard_dirty = 0;
}

static void LanguageKey_Init(void)
{
    GPIO_InitTypeDef gpio;
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA | RCC_APB2Periph_GPIOC, ENABLE);
    gpio.GPIO_Speed = GPIO_Speed_2MHz;
    gpio.GPIO_Mode = GPIO_Mode_IN_FLOATING;

    gpio.GPIO_Pin = GPIO_Pin_0;
    GPIO_Init(GPIOA, &gpio);

    gpio.GPIO_Pin = GPIO_Pin_13;
    GPIO_Init(GPIOC, &gpio);
}

static void LanguageKey_Poll(void)
{
    static uint8_t count1 = 0, count2 = 0;
    static uint8_t key1_pressed = 0, key2_pressed = 0;
    /* Both KEY1 (PA0) and KEY2 (PC13) on WildFire STM32 boards are Active High */
    uint8_t raw1 = GPIO_ReadInputDataBit(GPIOA, GPIO_Pin_0) ? 1 : 0;
    uint8_t raw2 = GPIO_ReadInputDataBit(GPIOC, GPIO_Pin_13) ? 1 : 0;

    if (raw1) {
        if (count1 < 3) count1++;
        else if (!key1_pressed) {
            key1_pressed = 1;
            /* KEY1: Cycle Miku actions (Wave -> Jump -> Run -> Idle) */
            if (s_state == PET_IDLE) PetPlayer_SetState(PET_WAVE);
            else if (s_state == PET_WAVE) PetPlayer_SetState(PET_JUMP);
            else if (s_state == PET_JUMP) PetPlayer_SetState(PET_RUN_RIGHT);
            else if (s_state == PET_RUN_RIGHT) PetPlayer_SetState(PET_RUN_LEFT);
            else PetPlayer_SetState(PET_IDLE);
            s_touch_hold_ms = 3000;
            s_touch_one_shot = 1;
            s_dashboard_dirty = 1;
            s_state_changed = 1;
        }
    } else {
        count1 = 0;
        key1_pressed = 0;
    }

    if (raw2) {
        if (count2 < 3) count2++;
        else if (!key2_pressed) {
            key2_pressed = 1;
            /* KEY2: Cycle Dashboard Modes (AI -> Clock/Weather -> Memo -> Geek) */
            s_dashboard_mode = (DashboardMode)((s_dashboard_mode % 4) + 1);
            s_dashboard_dirty = 1;
            s_state_changed = 1;
        }
    } else {
        count2 = 0;
        key2_pressed = 0;
    }
}

static uint8_t SerialReadByte(void)
{
    uint8_t value;
    while (!USART_DebugReadByte(&value)) {}
    return value;
}

static uint32_t SerialReadU32(void)
{
    uint8_t data[4];
    uint8_t i;
    for (i = 0; i < 4; i++) data[i] = SerialReadByte();
    return ReadU32(data);
}

static uint32_t Crc32Update(uint32_t crc, uint8_t value)
{
    uint8_t bit;
    crc ^= value;
    for (bit = 0; bit < 8; bit++)
        crc = (crc >> 1) ^ ((crc & 1) ? 0xEDB88320UL : 0);
    return crc;
}

static void UploadAsset(void)
{
    uint8_t buffer[256];
    uint8_t marker[8];
    uint32_t size = SerialReadU32();
    uint32_t expected_crc = SerialReadU32();
    uint32_t address, received = 0, crc = 0xFFFFFFFFUL;
    uint16_t chunk, i;
    if (size < PET_HEADER_SIZE || size > 8UL * 1024UL * 1024UL) {
        printf("UPLOAD_BAD_SIZE\r\n");
        return;
    }
    printf("UPLOAD_ERASING\r\n");
    for (address = 0; address < size; address += 4096UL)
        SPI_FLASH_SectorErase(address);
    printf("UPLOAD_READY\r\n");
    while (received < size) {
        chunk = (uint16_t)((size - received) > sizeof(buffer) ? sizeof(buffer) : (size - received));
        for (i = 0; i < chunk; i++) {
            buffer[i] = SerialReadByte();
            crc = Crc32Update(crc, buffer[i]);
        }
        SPI_FLASH_BufferWrite(buffer, received, chunk);
        received += chunk;
        if ((received & 0xFFFFUL) == 0) printf("UPLOAD_PROGRESS %lu\r\n", received);
    }
    crc ^= 0xFFFFFFFFUL;
    if (crc != expected_crc) {
        printf("UPLOAD_CRC_ERROR %08lX %08lX\r\n", crc, expected_crc);
        s_ready = 0;
        return;
    }
    marker[0] = 'M'; marker[1] = 'P'; marker[2] = 'O'; marker[3] = 'K';
    marker[4] = (uint8_t)crc;
    marker[5] = (uint8_t)(crc >> 8);
    marker[6] = (uint8_t)(crc >> 16);
    marker[7] = (uint8_t)(crc >> 24);
    SPI_FLASH_SectorErase(PET_VALID_MARKER);
    SPI_FLASH_BufferWrite(marker, PET_VALID_MARKER, sizeof(marker));
    printf("UPLOAD_OK %lu\r\n", received);
    PetPlayer_Init();
    PetPlayer_SetState(PET_IDLE);
}

static void UploadVoice(void)
{
    uint8_t buffer[256];
    uint32_t size=SerialReadU32(),expected=SerialReadU32(),address,received=0,crc=0xFFFFFFFFUL;
    uint16_t chunk,i;
    if(size<40UL||size>0x5FD000UL){printf("AUDIO_BAD_SIZE\r\n");return;}
    printf("AUDIO_ERASING\r\n");
    for(address=0;address<size;address+=4096UL)SPI_FLASH_SectorErase(VOICE_FLASH_BASE+address);
    USART_DebugFlush();
    printf("AUDIO_READY\r\n");
    while(received<size){
        chunk=(uint16_t)((size-received)>256?256:(size-received));
        for(i=0;i<chunk;i++){
            buffer[i]=SerialReadByte();
            crc=Crc32Update(crc,buffer[i]);
        }
        SPI_FLASH_BufferWrite(buffer,VOICE_FLASH_BASE+received,chunk);
        received+=chunk;
        USART_SendData(DEBUG_USARTx, '.');
        while (USART_GetFlagStatus(DEBUG_USARTx, USART_FLAG_TXE) == RESET);
    }
    crc^=0xFFFFFFFFUL;
    if(crc!=expected){printf("\r\nAUDIO_CRC_ERROR %08lX %08lX\r\n",crc,expected);return;}
    printf("\r\nAUDIO_OK %lu\r\n",received);
}

static uint16_t ReadU16(const uint8_t *p)
{
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

static uint32_t ReadU32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint8_t RenderFrame(uint8_t absolute_frame, uint16_t *duration_ms)
{
    uint8_t entry[PET_ENTRY_SIZE];
    uint32_t offset, length, pixel_count, source = 0, pixels = 0;
    SPI_FLASH_BufferRead(entry, PET_FLASH_BASE + PET_HEADER_SIZE +
                         (uint32_t)absolute_frame * PET_ENTRY_SIZE, PET_ENTRY_SIZE);
    *duration_ms = ReadU16(entry + 2);
    offset = ReadU32(entry + 4);
    length = ReadU32(entry + 8);
    pixel_count = ReadU32(entry + 12);
    if (length > PET_MAX_FRAME_BYTES || pixel_count != (uint32_t)s_width * s_height)
        return 0;
    SPI_FLASH_BufferRead(s_frame_data, PET_FLASH_BASE + offset, (uint16_t)length);
    ILI9341_OpenWindow((LCD_X_LENGTH - s_width) / 2,
                       (LCD_Y_LENGTH - s_height) / 2,
                       s_width, s_height);
    LCD_CMD_REG = 0x2C;
    while (source + 2 < length && pixels < pixel_count) {
        uint8_t count = s_frame_data[source];
        uint16_t color = ReadU16(s_frame_data + source + 1);
        source += 3;
        while (count-- && pixels < pixel_count) {
            LCD_DATA_REG = color;
            pixels++;
        }
    }
    return pixels == pixel_count;
}

uint8_t PetPlayer_Init(void)
{
    uint8_t header[PET_HEADER_SIZE];
    uint8_t marker[4];
    SPI_FLASH_Init();
    LanguageKey_Init();
    SPI_FLASH_BufferRead(marker, PET_VALID_MARKER, sizeof(marker));
    if (marker[0]!='M' || marker[1]!='P' || marker[2]!='O' || marker[3]!='K') {
        printf("MPET asset incomplete; upload required\r\n");
        return 0;
    }
    SPI_FLASH_BufferRead(header, PET_FLASH_BASE, PET_HEADER_SIZE);
    if (header[0]!='M' || header[1]!='P' || header[2]!='E' || header[3]!='T') {
        printf("MPET asset missing in W25Q64\r\n");
        return 0;
    }
    if (ReadU16(header + 4) != 1) {
        printf("Unsupported MPET version\r\n");
        return 0;
    }
    s_width = ReadU16(header + 6);
    s_height = ReadU16(header + 8);
    if (s_width > 96 || s_height > 104) {
        printf("MPET frame is too large\r\n");
        return 0;
    }
    s_ready = 1;
    printf("MPET ready: %ux%u, 74 frames\r\n", s_width, s_height);
    return 1;
}

void PetPlayer_SetState(PetState state)
{
    PetState previous = s_state;
    if (state > PET_LOOK_180_337) return;
    if (state == previous) return;
    s_state = state;
    s_frame = 0;
    s_dashboard_dirty = 1;
    s_state_changed = 1;
}

void PetPlayer_ApplyDashboardFrame(const uint8_t *frame)
{
    uint32_t session, sequence, expected_crc, crc = 0xFFFFFFFFUL;
    uint8_t mode, i;
    if (frame[0] != 0xA5 || frame[1] != 0x5A ||
        frame[62] != 0x0D || frame[63] != 0x0A)
        return;
    for (i = 0; i < 58; i++) crc = Crc32Update(crc, frame[i]);
    crc ^= 0xFFFFFFFFUL;
    expected_crc = ReadU32(frame + 58);
    if (crc != expected_crc) {
        printf("SNAPSHOT_CRC_BAD\r\n");
        return;
    }
    session = ReadU32(frame + 4);
    sequence = ReadU32(frame + 8);
    if (session == s_dashboard_session && sequence <= s_dashboard_sequence) {
        return;
    }

    mode = frame[2];
    s_dashboard_session = session;
    s_dashboard_sequence = sequence;

    if (frame[3] <= PET_LOOK_180_337) {
        PetPlayer_SetState((PetState)frame[3]);
    }

    if (mode == 5) {
        uint8_t voice_id = frame[12];
        if (voice_id <= 4) {
            PetPlayer_PlayVoice(voice_id);
        }
        if (frame[3] <= PET_LOOK_180_337) {
            s_state = (PetState)frame[3];
            s_frame = 0;
            s_dashboard_dirty = 1;
            s_state_changed = 1;
        }
        return;
    } else if (mode == 2) {
        s_dashboard_mode = DASHBOARD_MODE_WEATHER;
        memcpy(s_weather_date, frame + 12, 10); s_weather_date[10] = 0;
        memcpy(s_weather_time, frame + 22, 8);  s_weather_time[8] = 0;
        memcpy(s_weather_info, frame + 30, 14); s_weather_info[14] = 0;
        memcpy(s_weather_tip,  frame + 44, 14); s_weather_tip[14] = 0;
    } else if (mode == 3) {
        s_dashboard_mode = DASHBOARD_MODE_MESSAGE;
        memcpy(s_memo_sender, frame + 12, 8);  s_memo_sender[8] = 0;
        memcpy(s_memo_text1,  frame + 20, 20); s_memo_text1[20] = 0;
        memcpy(s_memo_text2,  frame + 40, 18); s_memo_text2[18] = 0;
    } else if (mode == 4) {
        s_dashboard_mode = DASHBOARD_MODE_GEEK;
        s_pomo_seconds = ReadU32(frame + 12);
        s_geek_commits = ReadU32(frame + 16);
        s_geek_stars   = ReadU32(frame + 20);
    } else {
        uint8_t title_len = frame[21];
        if (title_len > 36U) title_len = 36U;
        s_dashboard_mode = DASHBOARD_MODE_AI;
        s_total_tokens = ReadU32(frame + 12);
        s_remaining_percent = frame[16] > 100U ? 100U : frame[16];
        s_reset_minutes = ReadU32(frame + 17);
        for (i = 0; i < title_len && i < sizeof(s_session_title) - 1U; i++)
            s_session_title[i] = (char)frame[22 + i];
        s_session_title[i] = 0;
        s_usage_valid = 1;
    }
    s_dashboard_dirty = 1;
}

void PetPlayer_PollSerial(void)
{
    static char packet[48];
    static uint8_t binary_frame[64];
    static uint8_t binary_pos = 0;
    static uint8_t packet_pos = 0;
    static uint8_t packet_active = 0;
    static uint8_t title_active = 0;
    USART_TypeDef *source = 0;
    uint8_t command;
    if (USART_DebugReadByte(&command))
        source = DEBUG_USARTx;
    else if (USART_GetFlagStatus(USART2, USART_FLAG_RXNE) != RESET) {
        source = USART2;
        command = (uint8_t)USART_ReceiveData(source);
    }
    if (source) {
        if (binary_pos || command == 0xA5U) {
            binary_frame[binary_pos++] = command;
            if (binary_pos == sizeof(binary_frame)) {
                PetPlayer_ApplyDashboardFrame(binary_frame);
                binary_pos = 0;
            }
            return;
        }
        if (title_active || command == '#') {
            if (command == '#') {
                packet_pos = 0;
                title_active = 1;
            } else if (command == '\r' || command == '\n') {
                packet[packet_pos] = 0;
                if (packet_pos) {
                    uint8_t i;
                    for (i = 0; i <= packet_pos && i < sizeof(s_session_title); i++)
                        s_session_title[i] = packet[i];
                    s_session_title[sizeof(s_session_title)-1] = 0;
                    s_dashboard_dirty = 1;
                    s_state_changed = 1;
                    printf("TITLE_OK %u\r\n", packet_pos);
                }
                packet_pos = 0;
                title_active = 0;
            } else if (packet_pos < sizeof(packet) - 1) {
                packet[packet_pos++] = (char)command;
            }
            return;
        }
        if (packet_active || command == '@') {
            if (command == '@') {
                packet_pos = 0;
                packet_active = 1;
            } else if (command == '\r' || command == '\n') {
                uint32_t values[4];
                packet[packet_pos] = 0;
                if (packet_pos > 2 && packet[0] == 'T' && packet[1] == ',') {
                    uint8_t i, title_len = (uint8_t)(packet_pos - 2);
                    for (i = 0; i < title_len && i < sizeof(s_session_title)-1; i++)
                        s_session_title[i] = packet[i+2];
                    s_session_title[i] = 0;
                    s_dashboard_dirty = 1;
                    s_state_changed = 1;
                    printf("TITLE_OK %u\r\n", title_len);
                } else if (ParseDashboardPacket(packet, values)) {
                    if (values[0] <= PET_LOOK_180_337)
                        PetPlayer_SetState((PetState)values[0]);
                    s_total_tokens = values[1];
                    s_remaining_percent = values[2] > 100 ? 100 : (uint8_t)values[2];
                    s_reset_minutes = values[3];
                    s_usage_valid = 1;
                    s_dashboard_mode = DASHBOARD_MODE_AI;
                    s_dashboard_dirty = 1;
                    s_state_changed = 1;
                    printf("DASHBOARD_OK %lu %lu %lu %lu\r\n",
                           values[0], values[1], values[2], values[3]);
                } else {
                    printf("DASHBOARD_BAD\r\n");
                }
                packet_pos = 0;
                packet_active = 0;
            } else if (packet_pos < sizeof(packet) - 1) {
                packet[packet_pos++] = (char)command;
            }
            return;
        }
        if (s_touch_hold_ms)
            return;
        if (command >= '0' && command <= '8')
            PetPlayer_SetState((PetState)(command - '0'));
        else if (command == 'L' || command == 'l')
            PetPlayer_SetState(PET_LOOK_180_337);
        else if (command == 'R' || command == 'r')
            PetPlayer_SetState(PET_LOOK_0_157);
        else if (command == 'U')
            UploadAsset();
        else if (command == 'A' && source == DEBUG_USARTx)
            UploadVoice();
    }
}

void PetPlayer_OnTouch(int16_t x, int16_t y, uint8_t pressed)
{
    int16_t pet_x = (int16_t)((LCD_X_LENGTH - s_width) / 2);
    int16_t pet_y = (int16_t)((LCD_Y_LENGTH - s_height) / 2);
    if (!pressed) {
        s_touch_active = 0;
        return;
    }
    if (s_touch_active) return;
    s_touch_active = 1;
    if (x >= pet_x && x < pet_x + (int16_t)s_width &&
        y >= pet_y && y < pet_y + (int16_t)s_height) {
        s_touch_hold_ms = 2000;
        s_touch_one_shot = 1;
        PetPlayer_SetState(PET_WAVE);
    } else {
        s_facing_left = x < (int16_t)(LCD_X_LENGTH / 2) ? 1 : 0;
        s_frame = 0;
        if (s_state != PET_WORKING) {
            s_touch_hold_ms = 2000;
            s_touch_one_shot = 1;
            PetPlayer_SetState(s_facing_left ? PET_LOOK_180_337 : PET_LOOK_0_157);
        }
    }
}

void PetPlayer_Update(void)
{
    uint16_t duration = 90;
    uint8_t touch_divider = 0;
    uint8_t absolute_frame;
    if (!s_ready) return;

    s_state_changed = 0;

    if (s_state == PET_WORKING)
        absolute_frame = (s_facing_left ? 15U : 7U) + s_frame;
    else
        absolute_frame = s_first_frames[s_state] + s_frame;

    if (!RenderFrame(absolute_frame, &duration)) {
        printf("Frame decode error: %u\r\n", absolute_frame);
        s_ready = 0;
        return;
    }

    if (s_dashboard_dirty)
        DrawDashboard();

    if (s_state == PET_IDLE) duration = 180;
    else if (s_state == PET_WAVE) duration = 160;
    else if (s_state == PET_JUMP) duration = 140;
    else if (s_state == PET_RUN_RIGHT || s_state == PET_RUN_LEFT) duration = 90;
    else if (s_state == PET_WORKING) duration = 100;
    else if (s_state == PET_WAITING) duration = 140;
    else if (s_state == PET_FAILED) duration = 140;
    else if (s_state == PET_LOOK_0_157 || s_state == PET_LOOK_180_337) duration = 160;
    else duration = 150;

    if (++s_frame >= s_frame_counts[s_state]) {
        s_frame = 0;
        if (s_touch_one_shot) {
            s_touch_one_shot = 0;
            s_touch_hold_ms = 0;
            s_state = PET_IDLE;
            s_dashboard_dirty = 1;
            s_state_changed = 1;
        }
    }

    while (duration--) {
        ESP8266_DashboardPoll();
        PetPlayer_PollSerial();
        if (s_state_changed) {
            break;
        }
        if (s_touch_hold_ms)
            s_touch_hold_ms--;
        if (++touch_divider >= 8) {
            touch_divider = 0;
            XPT2046_TouchEvenHandler();
            Radar_Poll();
            LanguageKey_Poll();
        }
        Delay_us(1);
    }
}
