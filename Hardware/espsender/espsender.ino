#include <esp_now.h>
#include <WiFi.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include <OneWire.h>
#include <DallasTemperature.h>

#define TEMP_PIN 14

OneWire oneWire(TEMP_PIN);
DallasTemperature tempSensor(&oneWire);

Adafruit_ADS1115 ads;
uint8_t receiverMac[] = {0x8C, 0x94, 0xDF, 0x6B, 0xD2, 0x94};

typedef struct SensorData {
  float tds;
  float turbidity;
  float temperature;
} SensorData;

SensorData readings;

esp_now_peer_info_t peerInfo;

void onDataSent(const wifi_tx_info_t *tx_info, esp_now_send_status_t status) {
  Serial.print("Send status: ");
  Serial.println(status == ESP_NOW_SEND_SUCCESS ? "Success" : "Fail");
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  tempSensor.begin();
  Wire.begin(21, 22);
  ads.setGain(GAIN_ONE);
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
  int16_t tdsRaw = ads.readADC_SingleEnded(0);
  int16_t turbidityRaw = ads.readADC_SingleEnded(1);

  float tdsVoltage = ads.computeVolts(tdsRaw);
  float turbidityVoltage = ads.computeVolts(turbidityRaw);

  tempSensor.requestTemperatures();
  float temp=tempSensor.getTempCByIndex(0);

  readings.tds = tdsVoltage;
  readings.turbidity = turbidityVoltage;
  readings.temperature=temp;

  esp_err_t result = esp_now_send(receiverMac, (uint8_t *) &readings, sizeof(readings));

  if (result == ESP_OK) {
    Serial.println("Sent successfully");
  } else {
    Serial.println("Error sending data");
  }

  delay(1000);
}
