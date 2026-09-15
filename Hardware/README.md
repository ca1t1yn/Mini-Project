# Hardware

This folder contains the Arduino sketches and wiring documentation for the two ESP32 boards used in this project.

## System overview

```
[Sensors: TDS, Turbidity] -> ADS1115 -> ESP32 #1 (sender)
                                              |
                                         ESP-NOW (wireless)
                                              |
                                        ESP32 #2 (receiver)
                                              |
                                        USB (Serial) -> Raspberry Pi 4
```

## Sketches

| Sketch | Board | Purpose                                                                                                  |
|---|---|----------------------------------------------------------------------------------------------------------|
| `espsender/espsender.ino` | ESP32 #1 | Reads TDS and Turbidity from the ADS1115, sends readings wirelessly via ESP-NOW                          |
| `espreceiver/espreceiver.ino` | ESP32 #2 | Receives readings via ESP-NOW, prints them over Serial (USB) for the Raspberry Pi to read                |
| `get_mac_address/get_mac_address.ino` | Either board | Utility sketch — prints a board's MAC address, required for pairing the sender with the correct receiver |

## Required libraries (Arduino IDE)

Install via **Sketch → Include Library → Manage Libraries**:

- `Adafruit ADS1X15` (and its dependency, `Adafruit BusIO`)
The `esp_now.h` and `WiFi.h` libraries are included with the ESP32 board package (Espressif's `esp32` core)
- `OneWire`
Gives access to 1-wire devices made by Maxim/Dallas such as temperature sensors
- `DallasTemperature`
Translates binary data into real temperature values
## Wiring: ESP32 #1 (sensor board)

**ADS1115 to ESP32 #1:**

| ADS1115 pin | ESP32 pin |
|---|---|
| VDD | 3.3V |
| GND | GND |
| SDA | GPIO21 |
| SCL | GPIO22 |
| ADDR | GND (sets I2C address to 0x48) |

**TDS sensor:**

| TDS pin | Connects to |
|---|---|
| Signal/Output | ADS1115 A0 |
| VCC | ESP32 5V (VIN) |
| GND | Common ground |

**Turbidity sensor:**

The turbidity sensor can output close to 5V, which exceeds the ADS1115's 3.3V limit at 3.3V VDD.Therefore we use a voltage divider:

Sensor output --[220 ohm]-- (tap to ADS1115 A1) --[330 ohm]-- GND
```

| Turbidity pin | Connects to |
|---|---|
| Signal/Output | 220 ohm resistor -> tap point -> ADS1115 A1 |
| (tap point) | 330 ohm resistor -> GND |
| VCC | ESP32 5V (VIN) |
| GND | Common ground |

## Wiring: ESP32 #2 (receiver board)

No sensors attached. This board only needs:
- USB connection to the Raspberry Pi 4 (provides both power and the Serial data link)
- Flashed with `espreceiver.ino`

## Pairing the two boards (ESP-NOW)

1. Write the `get_mac_address.ino` into ESP32 #2 and note the printed MAC address.
2. In `espsender.ino`, update the `receiverMac[]` array with that MAC address.
3. Write `espsender.ino` to ESP32 #1.
4. Write `espreceiver.ino` to ESP32 #2.
5. Once both boards are powered, ESP32 #2's Serial Monitor (115200 baud) should show incoming readings, e.g.:
 

## Notes
- Temperature and pH sensors are not currently wired in. The dashboard backend can be updated to use placeholder values.
