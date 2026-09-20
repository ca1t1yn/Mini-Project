
#include <esp_now.h>
#include <WiFi.h>

typedef struct SensorData {
  float tds;
  float turbidity;
  float temperature;
} SensorData;

SensorData receivedData;

void onDataRecv(const esp_now_recv_info_t *recv_info, const uint8_t *incomingData, int len) {
  memcpy(&receivedData, incomingData, sizeof(receivedData));

  Serial.print("TDS:");
  Serial.print(receivedData.tds,3);
  Serial.print(",Turbidity:");
  Serial.println(receivedData.turbidity,3);
  Serial.print(",Temperature:");
  Serial.println(receivedData.temperature,2);
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  WiFi.mode(WIFI_STA);

  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW failed");
    return;
  }
  esp_now_register_recv_cb(onDataRecv);
  Serial.println("The ESP-NOW receiver is ready");
}

void loop() {
}
