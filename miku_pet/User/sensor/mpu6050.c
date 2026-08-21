#include "./sensor/mpu6050.h"
#include "./SysTick/bsp_SysTick.h"
#include "./pet/pet_player.h"
#include <stdio.h>

#define MPU_GPIO       GPIOB
#define MPU_SCL        GPIO_Pin_6
#define MPU_SDA        GPIO_Pin_7
#define MPU_ADDR       0x68U
#define MPU_PERIOD_MS  100UL
#define DWT_CTRL_REG   (*((volatile uint32_t *)0xE0001000UL))
#define DWT_COUNT_REG  (*((volatile uint32_t *)0xE0001004UL))

static uint8_t s_valid;
static uint32_t s_last_update;
static uint32_t s_last_gesture;
static int16_t s_ax, s_ay, s_az, s_gx, s_gy, s_gz, s_pitch, s_roll;
static const char *s_gesture = "STABLE";

static int32_t Abs32(int32_t value) { return value < 0 ? -value : value; }
static void DelayUs(uint32_t us)
{
    uint32_t start = DWT_COUNT_REG;
    uint32_t ticks = (SystemCoreClock / 1000000UL) * us;
    while ((uint32_t)(DWT_COUNT_REG - start) < ticks) {}
}
static void SCL(uint8_t high) { high ? GPIO_SetBits(MPU_GPIO, MPU_SCL) : GPIO_ResetBits(MPU_GPIO, MPU_SCL); }
static void SDA(uint8_t high) { high ? GPIO_SetBits(MPU_GPIO, MPU_SDA) : GPIO_ResetBits(MPU_GPIO, MPU_SDA); }
static uint8_t SDA_Read(void) { return GPIO_ReadInputDataBit(MPU_GPIO, MPU_SDA) ? 1U : 0U; }

static void I2C_Start(void) { SDA(1); SCL(1); DelayUs(4); SDA(0); DelayUs(4); SCL(0); }
static void I2C_Stop(void) { SDA(0); SCL(1); DelayUs(4); SDA(1); DelayUs(4); }
static uint8_t I2C_Write(uint8_t value)
{
    uint8_t i, ack;
    for (i = 0; i < 8U; i++) { SDA(value & 0x80U); DelayUs(2); SCL(1); DelayUs(4); SCL(0); value <<= 1; }
    SDA(1); DelayUs(2); SCL(1); DelayUs(3); ack = SDA_Read() ? 0U : 1U; SCL(0); return ack;
}
static uint8_t I2C_Read(uint8_t ack)
{
    uint8_t i, value = 0U;
    SDA(1);
    for (i = 0; i < 8U; i++) { value <<= 1; SCL(1); DelayUs(3); if (SDA_Read()) value |= 1U; SCL(0); DelayUs(2); }
    SDA(ack ? 0U : 1U); SCL(1); DelayUs(4); SCL(0); SDA(1); return value;
}
static uint8_t WriteReg(uint8_t reg, uint8_t value)
{
    uint8_t ok;
    I2C_Start(); ok = I2C_Write((uint8_t)(MPU_ADDR << 1)); ok &= I2C_Write(reg); ok &= I2C_Write(value); I2C_Stop(); return ok;
}
static uint8_t ReadRegs(uint8_t reg, uint8_t *data, uint8_t count)
{
    uint8_t i, ok;
    I2C_Start(); ok = I2C_Write((uint8_t)(MPU_ADDR << 1)); ok &= I2C_Write(reg);
    I2C_Start(); ok &= I2C_Write((uint8_t)((MPU_ADDR << 1) | 1U));
    if (!ok) { I2C_Stop(); return 0U; }
    for (i = 0; i < count; i++) data[i] = I2C_Read(i + 1U < count);
    I2C_Stop(); return 1U;
}
static int16_t Atan2Deg10(int32_t y, int32_t x)
{
    int32_t abs_y = Abs32(y) + 1, r, angle;
    if (x >= 0) { r = ((x - abs_y) * 1000) / (x + abs_y); angle = 450 - (450 * r) / 1000; }
    else { r = ((x + abs_y) * 1000) / (abs_y - x); angle = 1350 - (450 * r) / 1000; }
    return (int16_t)(y < 0 ? -angle : angle);
}

void MPU6050_Init(void)
{
    GPIO_InitTypeDef gpio;
    uint8_t who = 0U;
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOB, ENABLE);
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk; DWT_COUNT_REG = 0U; DWT_CTRL_REG |= 1UL;
    gpio.GPIO_Pin = MPU_SCL | MPU_SDA; gpio.GPIO_Speed = GPIO_Speed_50MHz; gpio.GPIO_Mode = GPIO_Mode_Out_OD; GPIO_Init(MPU_GPIO, &gpio);
    SDA(1); SCL(1); Delay_ms(50);
    if (ReadRegs(0x75U, &who, 1U) && who == 0x68U &&
        WriteReg(0x6BU, 0x01U) && WriteReg(0x19U, 9U) &&
        WriteReg(0x1AU, 3U) && WriteReg(0x1BU, 0U) && WriteReg(0x1CU, 0U)) {
        s_valid = 1U; printf("MPU6050_READY addr=68 PB6_PB7\r\n");
    } else printf("MPU6050_ERROR who=%02X\r\n", who);
    s_last_update = SysTick_GetTick() - MPU_PERIOD_MS;
}

void MPU6050_Update(void)
{
    uint8_t d[14]; int16_t ax, ay, az, gx, gy, gz; int32_t denominator; uint32_t now = SysTick_GetTick();
    if ((now - s_last_update) < MPU_PERIOD_MS) return; s_last_update = now;
    if (!ReadRegs(0x3BU, d, 14U)) { s_valid = 0U; printf("MPU6050 valid=0\r\n"); return; }
    ax = (int16_t)(((uint16_t)d[0] << 8) | d[1]); ay = (int16_t)(((uint16_t)d[2] << 8) | d[3]); az = (int16_t)(((uint16_t)d[4] << 8) | d[5]);
    gx = (int16_t)(((uint16_t)d[8] << 8) | d[9]); gy = (int16_t)(((uint16_t)d[10] << 8) | d[11]); gz = (int16_t)(((uint16_t)d[12] << 8) | d[13]);
    s_ax = (int16_t)((int32_t)ax * 1000 / 16384); s_ay = (int16_t)((int32_t)ay * 1000 / 16384); s_az = (int16_t)((int32_t)az * 1000 / 16384);
    s_gx = (int16_t)((int32_t)gx * 10 / 131); s_gy = (int16_t)((int32_t)gy * 10 / 131); s_gz = (int16_t)((int32_t)gz * 10 / 131);
    denominator = Abs32(ay) > Abs32(az) ? Abs32(ay) + Abs32(az) / 2 : Abs32(az) + Abs32(ay) / 2;
    s_pitch = Atan2Deg10(-ax, denominator); s_roll = Atan2Deg10(ay, az); s_valid = 1U; s_gesture = "STABLE";
    if (Abs32(ax) > 24500 || Abs32(ay) > 24500 || Abs32(az) > 24500) s_gesture = "SHAKE";
    else if (s_roll > 300) s_gesture = "TILT_RIGHT"; else if (s_roll < -300) s_gesture = "TILT_LEFT";
    if ((now - s_last_gesture) > 1200UL) {
        if (s_gesture[0] == 'S' && s_gesture[1] == 'H') { PetPlayer_SetState(PET_JUMP); s_last_gesture = now; }
        else if (s_roll > 450) { PetPlayer_SetState(PET_LOOK_0_157); s_last_gesture = now; }
        else if (s_roll < -450) { PetPlayer_SetState(PET_LOOK_180_337); s_last_gesture = now; }
    }
    printf("MPU6050 valid=1 ax=%d ay=%d az=%d gx10=%d gy10=%d gz10=%d pitch10=%d roll10=%d gesture=%s\r\n", s_ax,s_ay,s_az,s_gx,s_gy,s_gz,s_pitch,s_roll,s_gesture);
    PetPlayer_RefreshMPUPage();
}

uint8_t MPU6050_IsValid(void){return s_valid;} int16_t MPU6050_GetAccelXmg(void){return s_ax;} int16_t MPU6050_GetAccelYmg(void){return s_ay;} int16_t MPU6050_GetAccelZmg(void){return s_az;}
int16_t MPU6050_GetGyroX10(void){return s_gx;} int16_t MPU6050_GetGyroY10(void){return s_gy;} int16_t MPU6050_GetGyroZ10(void){return s_gz;}
int16_t MPU6050_GetPitch10(void){return s_pitch;} int16_t MPU6050_GetRoll10(void){return s_roll;} const char *MPU6050_GetGesture(void){return s_gesture;}
