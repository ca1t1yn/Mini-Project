#include <esp_now.h>
#include <WiFi.h>

typedef struct SensorData {
  float tds;          
  float turbidity;    
  float temperature;  
  float ph;
} SensorData;

SensorData receivedData;

void onDataRecv(const esp_now_recv_info_t *recv_info, const uint8_t *incomingData, int len) {
  if (len == sizeof(receivedData)) {
    memcpy(&receivedData, incomingData, sizeof(receivedData));

    Serial.printf("Received -> Temp: %.2f °C | TDS: %.2f PPM | Turbidity: %.2f NTU | pH: %.2f \n",
                  receivedData.temperature, receivedData.tds, receivedData.turbidity, receivedData.ph);
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  WiFi.mode(WIFI_STA);

  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW failed to initialize");
    return;
  }

  esp_now_register_recv_cb(onDataRecv);
  Serial.println("ESP-NOW Receiver Ready");
}

void loop() {
}