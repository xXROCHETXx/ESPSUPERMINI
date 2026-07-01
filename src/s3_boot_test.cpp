#ifdef S3_BOOT_TEST

#include <Arduino.h>
#include <esp_system.h>

namespace {

constexpr uint8_t rgbLedPin = 48;

const char* resetReasonText(esp_reset_reason_t reason) {
    switch (reason) {
        case ESP_RST_POWERON:
            return "power-on";
        case ESP_RST_EXT:
            return "external reset";
        case ESP_RST_SW:
            return "software reset";
        case ESP_RST_PANIC:
            return "panic";
        case ESP_RST_INT_WDT:
            return "interrupt watchdog";
        case ESP_RST_TASK_WDT:
            return "task watchdog";
        case ESP_RST_WDT:
            return "other watchdog";
        case ESP_RST_DEEPSLEEP:
            return "deep sleep wake";
        case ESP_RST_BROWNOUT:
            return "brownout";
        case ESP_RST_SDIO:
            return "sdio";
        default:
            return "unknown";
    }
}

}  // namespace

void setup() {
    pinMode(rgbLedPin, OUTPUT);
    digitalWrite(rgbLedPin, LOW);

    Serial.begin(115200);
    delay(2000);

    const esp_reset_reason_t reason = esp_reset_reason();
    Serial.println();
    Serial.println("ESP32-S3 Super Mini boot test");
    Serial.printf("Reset reason: %d (%s)\n", reason, resetReasonText(reason));
    Serial.printf("Chip model: %s rev %u, cores=%u\n",
                  ESP.getChipModel(),
                  ESP.getChipRevision(),
                  ESP.getChipCores());
    Serial.printf("CPU: %lu MHz\n", static_cast<unsigned long>(ESP.getCpuFreqMHz()));
    Serial.printf("Flash: %lu bytes\n",
                  static_cast<unsigned long>(ESP.getFlashChipSize()));
    Serial.printf("PSRAM: %lu bytes\n",
                  static_cast<unsigned long>(ESP.getPsramSize()));
    Serial.printf("Heap: %lu bytes\n",
                  static_cast<unsigned long>(ESP.getFreeHeap()));
}

void loop() {
    static uint32_t counter = 0;
    digitalWrite(rgbLedPin, (counter % 2) == 0 ? HIGH : LOW);
    Serial.printf("Boot test alive: %lu\n",
                  static_cast<unsigned long>(counter++));
    delay(1000);
}

#endif  // S3_BOOT_TEST
