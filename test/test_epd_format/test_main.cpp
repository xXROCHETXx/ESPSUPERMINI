#include <unity.h>

#include <array>
#include <cstring>
#include <vector>

#include "epd_format.h"

namespace {

void writeLe16(uint8_t* target, uint16_t value) {
    target[0] = static_cast<uint8_t>(value);
    target[1] = static_cast<uint8_t>(value >> 8);
}

void writeLe32(uint8_t* target, uint32_t value) {
    target[0] = static_cast<uint8_t>(value);
    target[1] = static_cast<uint8_t>(value >> 8);
    target[2] = static_cast<uint8_t>(value >> 16);
    target[3] = static_cast<uint8_t>(value >> 24);
}

std::vector<uint8_t> makeFile(epd::Mode mode) {
    const uint16_t payloadLength =
        mode == epd::Mode::bw ? epd::planeSize : epd::planeSize * 2;
    std::vector<uint8_t> file(epd::headerSize + payloadLength, 0xff);
    memcpy(file.data(), "EPD1", 4);
    file[4] = 1;
    file[5] = static_cast<uint8_t>(mode);
    file[6] = epd::headerSize;
    file[7] = 0;
    writeLe16(file.data() + 8, epd::width);
    writeLe16(file.data() + 10, epd::height);
    writeLe16(file.data() + 12, epd::bytesPerRow);
    writeLe16(file.data() + 14, payloadLength);
    writeLe32(file.data() + 16, 1234567890U);
    writeLe32(
        file.data() + 20,
        epd::crc32(file.data() + epd::headerSize, payloadLength));
    return file;
}

void testParsesBw() {
    const auto file = makeFile(epd::Mode::bw);
    epd::ImageView image;
    epd::ParseError error;
    TEST_ASSERT_TRUE(epd::parse(file.data(), file.size(), image, error));
    TEST_ASSERT_EQUAL_UINT8(static_cast<uint8_t>(epd::Mode::bw),
                            static_cast<uint8_t>(image.mode));
    TEST_ASSERT_NULL(image.redPlane);
}

void testParsesBwr() {
    auto file = makeFile(epd::Mode::bwr);
    file[epd::headerSize] &= 0x7f;
    writeLe32(file.data() + 20,
              epd::crc32(file.data() + epd::headerSize,
                         epd::planeSize * 2));
    epd::ImageView image;
    epd::ParseError error;
    TEST_ASSERT_TRUE(epd::parse(file.data(), file.size(), image, error));
    TEST_ASSERT_NOT_NULL(image.redPlane);
}

void testRejectsCorruption() {
    auto file = makeFile(epd::Mode::bw);
    file.back() ^= 0x01;
    epd::ImageView image;
    epd::ParseError error;
    TEST_ASSERT_FALSE(epd::parse(file.data(), file.size(), image, error));
    TEST_ASSERT_EQUAL_UINT8(static_cast<uint8_t>(epd::ParseError::badCrc),
                            static_cast<uint8_t>(error));
}

void testRejectsOverlap() {
    auto file = makeFile(epd::Mode::bwr);
    file[epd::headerSize] &= 0x7f;
    file[epd::headerSize + epd::planeSize] &= 0x7f;
    writeLe32(file.data() + 20,
              epd::crc32(file.data() + epd::headerSize,
                         epd::planeSize * 2));
    epd::ImageView image;
    epd::ParseError error;
    TEST_ASSERT_FALSE(epd::parse(file.data(), file.size(), image, error));
    TEST_ASSERT_EQUAL_UINT8(
        static_cast<uint8_t>(epd::ParseError::overlappingColours),
        static_cast<uint8_t>(error));
}

}  // namespace

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(testParsesBw);
    RUN_TEST(testParsesBwr);
    RUN_TEST(testRejectsCorruption);
    RUN_TEST(testRejectsOverlap);
    return UNITY_END();
}
