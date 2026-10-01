#include <esp_now.h>
#include <WiFi.h>
#include <Wire.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Adafruit_ADS1X15.h>

#define ONE_WIRE_BUS 4

OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature tempSensor(&oneWire);
Adafruit_ADS1115 ads;

uint8_t receiverMac[] = {0x8C, 0x94, 0xDF, 0x6B, 0xD2, 0x94};

typedef struct SensorData {
  float tds;
  float turbidity;
  float temperature;
  float ph;
} SensorData;

SensorData readings;
esp_now_peer_info_t peerInfo;

const float VOLTAGE_AT_PH7 = 1.953;
const float VOLTAGE_AT_PH4 = 1.627;

float phSlope;
float phIntercept;

void onDataSent(const wifi_tx_info_t *tx_info, esp_now_send_status_t status) {
  Serial.print("Send status: ");
  Serial.println(status == ESP_NOW_SEND_SUCCESS ? "Success" : "Fail");
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  tempSensor.begin();

  int count = tempSensor.getDeviceCount();
  Serial.print("DS18B20 Sensors found: ");
  Serial.println(count);

  if (count == 0) {
    Serial.println("Error: DS18B20 probe not detected! Check 4.7k pull-up resistor on GPIO 14.");
  }

  Wire.begin(21, 22);
  ads.setGain(GAIN_TWOTHIRDS);

  phSlope = (7.00 - 4.01) / (VOLTAGE_AT_PH7 - VOLTAGE_AT_PH4);
  phIntercept = 7.00 - (phSlope * VOLTAGE_AT_PH7);

  if (!ads.begin(0x48)) {
    Serial.println("ADS1115 not found!");
  }

  WiFi.mode(WIFI_STA);

  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW failed");
    return;
  }

  esp_now_register_send_cb(onDataSent);

  memcpy(peerInfo.peer_addr, receiverMac, 6);
  peerInfo.channel = 0;
  peerInfo.encrypt = false;

  if (esp_now_add_peer(&peerInfo) != ESP_OK) {
    Serial.println("Failed to add peer");
    return;
  }

  Serial.println("ESP-NOW sender ready");
}

void loop() {
  const int NUM_SAMPLES = 10;
  float voltageSum = 0.0;

  for (int i = 0; i < NUM_SAMPLES; i++) {
    int16_t phRaw = ads.readADC_SingleEnded(2);
    voltageSum += phRaw * (6.144 / 32768.0);
    delay(10);
  }

  float phVoltage = voltageSum / NUM_SAMPLES;
  float phValue = (phSlope * phVoltage) + phIntercept;

  if (phValue < 0.0) phValue = 0.0;
  if (phValue > 14.0) phValue = 14.0;

  int16_t tdsRaw = ads.readADC_SingleEnded(0);
  float tdsvoltage = tdsRaw * (6.144 / 32768.0);

  int16_t turbidityRaw = ads.readADC_SingleEnded(1);
  float turbidityVoltage = turbidityRaw * (6.144 / 32768.0);
  float turbidityValue = turbidityVoltage;

  tempSensor.requestTemperatures();
  delay(750);

  float currentTemp = tempSensor.getTempCByIndex(0);

  if (currentTemp == DEVICE_DISCONNECTED_C || currentTemp < -50) {
    currentTemp = 25.0;
  }

  float compensationCoefficient = 1.0 + 0.02 * (currentTemp - 25.0);
  float compensationVoltage = tdsvoltage / compensationCoefficient;

  float tdsPPM =
    (133.42 * pow(compensationVoltage, 3)
    - 255.86 * pow(compensationVoltage, 2)
    + 857.39 * compensationVoltage) * 0.5;

  readings.tds = tdsPPM;
  readings.turbidity = turbidityValue;
  readings.temperature = currentTemp;
  readings.ph = phValue;

  esp_err_t result = esp_now_send(receiverMac, (uint8_t *)&readings, sizeof(readings));

  if (result == ESP_OK) {
    Serial.printf("Sent -> Temp: %.2f C | TDS: %.2f PPM | Turbidity: %.4f V | pH: %.2f\n",
      readings.temperature,
      readings.tds,
      readings.turbidity,
      readings.ph);
  } else {
    Serial.println("Error sending data");
  }

  delay(1000);
}
