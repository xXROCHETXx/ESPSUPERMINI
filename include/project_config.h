#pragma once

#include <stdint.h>

#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.example.h"
#endif

namespace config {

constexpr uint16_t displayWidth = 296;
constexpr uint16_t displayHeight = 152;
constexpr uint16_t bytesPerRow = 37;

constexpr uint32_t wifiTimeoutMs = 10000;
constexpr uint32_t downloadTimeoutMs = 15000;
constexpr uint32_t displayWatchdogSeconds = 120;
constexpr uint64_t fallbackSleepSeconds = 24ULL * 60ULL * 60ULL;
constexpr uint64_t minimumSleepSeconds = 15ULL * 60ULL;

// Chile continental. POSIX TZ strings reverse the UTC sign.
constexpr char chileTimezone[] = "CLT4CLST,M9.1.6/24,M4.1.6/24";

// ESP32-S3 Arduino defaults: MOSI=11, SCK=12, MISO=13.
// Control pins are provisional until the real wiring is tested.
constexpr uint8_t pinBusy = 4;
constexpr uint8_t pinDc = 5;
constexpr uint8_t pinReset = 6;
constexpr uint8_t pinFlashCs = 7;
constexpr uint8_t pinPanelCs = 8;

constexpr float batteryCapacityMah = 400.0f;
constexpr float estimatedDeepSleepMa = 0.020f;
constexpr float estimatedAwakeMa = 100.0f;
constexpr float estimatedDisplayMa = 50.0f;

}  // namespace config

