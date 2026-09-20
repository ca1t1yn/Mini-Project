#include <WiFi.h>

void setup() {
  Serial.begin(115200);
  delay(1000);
  WiFi.mode(WIFI_STA);
  Serial.println();
  Serial.print("This board's MAC address:");
  Serial.println(WiFi.macAddress());
}

void loop() {
  // nothing to do here
}
