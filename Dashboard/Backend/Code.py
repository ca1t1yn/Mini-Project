import threading
import time
import serial
import json
import requests
import sqlite3
from collections import deque
from serial.tools import list_ports
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

START_TIME = time.time()

db_lock = threading.RLock()
db_connection = sqlite3.connect("sensor_data.db", check_same_thread=False)

db_connection.execute("""CREATE TABLE IF NOT EXISTS sensor_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    tds REAL,
    turbidity REAL,
    ph REAL,
    temperature REAL,
    predicted_nh3 REAL,
    predicted_do REAL
)""")

db_connection.execute("""CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    parameter TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    value REAL,
    opened_at REAL NOT NULL,
    resolved_at REAL
)""")

db_connection.commit()

latest_data = {
    "tds": None,
    "turbidity": None,
    "ph": None,
    "temperature": None,
    "predicted_nh3": None,
    "predicted_do": None,
    "nh3": None,
    "do": None,
    "potability": None,
    "last_updated": None,
}

THRESHOLDS = {
    "ph": {"label": "pH", "unit": "", "low": (6.5, 6.0), "high": (8.5, 9.0)},
    "tds": {"label": "TDS", "unit": "ppm", "high": (500, 1500)},
    "turbidity": {"label": "Turbidity", "unit": "NTU", "high": (50, 100)},
    "temperature": {"label": "Temperature", "unit": "°C", "high": (32, 35)},
    "nh3": {"label": "Predicted NH3-N", "unit": "mg/L", "high": (0.5, 1.2)},
    "do": {"label": "Predicted DO", "unit": "mg/L", "low": (5, 4)},
}

PLAUSIBLE = {
    "ph": (0, 14),
    "tds": (0, 5000),
    "turbidity": (0, 4000),
    "temperature": (-5, 60),
}

FLATLINE_PARAMS = ("tds", "turbidity", "ph", "temperature")
FLATLINE_N = 60
TRIGGER_COUNT = 3
CLEAR_COUNT = 3
OFFLINE_AFTER_S = 15

TURBIDITY_WINDOW = 5
turbidity_voltage_history = deque(maxlen=TURBIDITY_WINDOW)

# Preliminary 3-point turbidity calibration (distilled water, 250 NTU, ~333 NTU),
# taken in the same container at the same sensor depth.
# Voltages ascending, NTU descending: voltage falls as turbidity rises.
CAL_VOLTS = [1.55, 1.75, 1.96]
CAL_NTU = [333.0, 250.0, 0.0]

SEVERITY_ORDER = {"critical": 0, "fault": 1, "warning": 2}

alert_lock = threading.RLock()
active_alerts = {}
streaks = {}
recent_values = {}


def notify(alert, kind):
    pass


def classify(param, value):
    cfg = THRESHOLDS[param]

    if "high" in cfg:
        warn, crit = cfg["high"]

        if value > crit:
            return "critical", crit, "above"

        if value > warn:
            return "warning", warn, "above"

    if "low" in cfg:
        warn, crit = cfg["low"]

        if value < crit:
            return "critical", crit, "below"

        if value < warn:
            return "warning", warn, "below"

    return None


def _open_or_update(key, parameter, level, message, value):
    event = None
    kind = None

    with alert_lock:
        current = active_alerts.get(key)
        now = time.time()

        if current is None:
            with db_lock:
                cursor = db_connection.execute(
                    "INSERT INTO alerts(key, parameter, level, message, value, opened_at) VALUES (?,?,?,?,?,?)",
                    (key, parameter, level, message, value, now),
                )
                db_connection.commit()

            current = {
                "id": cursor.lastrowid,
                "key": key,
                "parameter": parameter,
                "level": level,
                "message": message,
                "value": value,
                "opened_at": now,
            }

            active_alerts[key] = current
            event = dict(current)
            kind = "opened"

        else:
            level_changed = current["level"] != level

            current["level"] = level
            current["message"] = message
            current["value"] = value

            if level_changed:
                with db_lock:
                    db_connection.execute(
                        "UPDATE alerts SET level=?, message=?, value=? WHERE id=?",
                        (level, message, value, current["id"]),
                    )
                    db_connection.commit()

                event = dict(current)
                kind = "changed"

    if event:
        print(f"ALERT {kind}: [{event['level']}] {event['message']}")
        notify(event, kind)


def _resolve(key):
    with alert_lock:
        current = active_alerts.pop(key, None)

        if current is None:
            return

        with db_lock:
            db_connection.execute(
                "UPDATE alerts SET resolved_at=? WHERE id=?",
                (time.time(), current["id"]),
            )
            db_connection.commit()

    print(f"ALERT resolved: {current['message']}")
    notify(current, "resolved")


def _debounce(key, is_bad):
    s = streaks.setdefault(key, {"bad": 0, "good": 0})

    if is_bad:
        s["bad"] += 1
        s["good"] = 0

        if s["bad"] >= TRIGGER_COUNT:
            return "open"

        return None

    s["good"] += 1
    s["bad"] = 0

    if s["good"] >= CLEAR_COUNT and key in active_alerts:
        return "close"

    return None


def evaluate_reading(readings):
    for param, value in readings.items():
        if value is None:
            continue

        cfg = THRESHOLDS[param]
        label = cfg["label"]
        unit = cfg["unit"]

        if unit:
            unit_text = f" {unit}"
        else:
            unit_text = ""

        out_of_range = False

        if param in PLAUSIBLE:
            low, high = PLAUSIBLE[param]
            out_of_range = not (low <= value <= high)

            key = f"{param}_range"
            action = _debounce(key, out_of_range)

            if action == "open":
                _open_or_update(
                    key,
                    param,
                    "fault",
                    f"{label} reads {value:.2f}{unit_text}, which is outside the possible range. Check the sensor and wiring.",
                    value,
                )

            elif action == "close":
                _resolve(key)

        if param in FLATLINE_PARAMS:
            history = recent_values.setdefault(param, deque(maxlen=FLATLINE_N))

            history.append(value)

            # Calibrated turbidity is clamped at the ends of the calibrated range,
            # so a constant 0 NTU (clear) or max NTU (above range) is not a fault.
            at_clamp = param == "turbidity" and value in (0.0, CAL_NTU[0])

            is_flat = (
                len(history) == FLATLINE_N
                and len(set(history)) == 1
                and not at_clamp
            )

            key = f"{param}_flatline"
            action = _debounce(key, is_flat)

            if action == "open":
                _open_or_update(
                    key,
                    param,
                    "fault",
                    f"{label} has reported exactly {value:.2f}{unit_text} for {FLATLINE_N} readings in a row. The sensor may be stuck or disconnected.",
                    value,
                )

            elif action == "close":
                _resolve(key)

        if out_of_range:
            continue

        result = classify(param, value)

        key = f"{param}_threshold"
        action = _debounce(key, result is not None)

        if action == "open":
            level, limit, direction = result

            _open_or_update(
                key,
                param,
                level,
                f"{label} is {value:.2f}{unit_text}, {direction} the {level} limit of {limit:g}{unit_text}.",
                value,
            )

        elif action == "close":
            _resolve(key)


def process_alerts(tds, turbidity, ph, temperature, nh3, do):
    try:
        evaluate_reading(
            {
                "tds": tds,
                "turbidity": turbidity,
                "ph": ph,
                "temperature": temperature,
                "nh3": nh3,
                "do": do,
            }
        )

        prediction_missing = nh3 is None or do is None

        action = _debounce("prediction_unavailable", prediction_missing)

        if action == "open":
            _open_or_update(
                "prediction_unavailable",
                "system",
                "warning",
                "The ML prediction service is not responding. NH3-N and DO forecasts are unavailable.",
                None,
            )

        elif action == "close":
            _resolve("prediction_unavailable")

    except Exception as error:
        print(f"Alert evaluation failed: {error}")


def watchdog_loop():
    while True:
        try:
            reference = latest_data["last_updated"] or START_TIME
            silent_for = time.time() - reference

            if silent_for > OFFLINE_AFTER_S:
                _open_or_update(
                    "system_offline",
                    "system",
                    "critical",
                    f"No data from the sensor node for {int(silent_for)} seconds. Check power, the ESP-NOW link and the USB connection.",
                    None,
                )
            else:
                _resolve("system_offline")

        except Exception as error:
            print(f"Watchdog error: {error}")

        time.sleep(5)


def read_values(line):
    try:
        parts = line.strip().split("|")

        temperatureText = parts[0].split(":")[1].replace("°C", "").strip()
        tdsText = parts[1].split(":")[1].replace("PPM", "").strip()
        # The receiver labels this field "NTU" but it is the raw sensor voltage in volts.
        turbidityText = parts[2].split(":")[1].replace("NTU", "").replace("V", "").strip()
        phText = parts[3].split(":")[1].strip()

        temperatureValue = float(temperatureText)
        tdsValue = float(tdsText)
        turbidityVoltage = float(turbidityText)
        phValue = float(phText)

        return tdsValue, turbidityVoltage, temperatureValue, phValue

    except Exception as error:
        print(f"Parse Error: {error}")
        print(f"Received: {repr(line)}")
        return None, None, None, None


def smooth_turbidity_voltage(voltage):
    turbidity_voltage_history.append(voltage)
    return sum(turbidity_voltage_history) / len(turbidity_voltage_history)


def voltage_to_ntu(voltage):
    # At or above the clear-water voltage -> 0 NTU
    if voltage >= CAL_VOLTS[-1]:
        return 0.0

    # At or below the lowest calibrated voltage -> clamp to top of calibrated range
    if voltage <= CAL_VOLTS[0]:
        return CAL_NTU[0]

    # Piecewise-linear interpolation between calibration points
    for i in range(len(CAL_VOLTS) - 1):
        v0, v1 = CAL_VOLTS[i], CAL_VOLTS[i + 1]

        if v0 <= voltage <= v1:
            n0, n1 = CAL_NTU[i], CAL_NTU[i + 1]
            return n0 + (voltage - v0) * (n1 - n0) / (v1 - v0)

    return 0.0


def get_prediction(tds, turbidity, ph, temperature):
    try:
        url = "https://mini-project-buj5.onrender.com/predict"

        predictions = {
            "tds": tds,
            "turbidity": turbidity,
            "ph": ph,
            "temperature": temperature,
        }

        response = requests.post(url, json=predictions, timeout=90)

        response.raise_for_status()

        data = response.json()

        nh3 = data.get("predicted_nh3")
        do = data.get("predicted_do")

        return nh3, do

    except Exception as error:
        print(f"Prediction API Error: {error}")
        return None, None


def calculate_potability(tds, turbidity, ph, nh3, do):
    values = [tds, turbidity, ph, nh3, do]

    if any(value is None for value in values):
        return {
            "status": "Insufficient Data",
            "checks": {
                "ph": None,
                "tds": None,
                "turbidity": None,
                "nh3": None,
                "do": None,
            },
            "failed_parameters": [],
        }

    checks = {
        "ph": 6.5 <= ph <= 8.5,
        "tds": tds <= 500,
        "turbidity": turbidity <= 5,
        "nh3": nh3 <= 0.5,
        "do": do >= 5,
    }

    failed_parameters = [
        parameter for parameter, passed in checks.items() if not passed
    ]

    if len(failed_parameters) == 0:
        status = "Suitable"
    else:
        status = "Not Suitable"

    return {"status": status, "checks": checks, "failed_parameters": failed_parameters}


def updated_latest_data(tds, turbidity, ph, temperature, nh3, do):
    latest_data["tds"] = tds
    latest_data["turbidity"] = turbidity
    latest_data["ph"] = ph
    latest_data["temperature"] = temperature
    latest_data["predicted_nh3"] = nh3
    latest_data["predicted_do"] = do
    latest_data["nh3"] = nh3
    latest_data["do"] = do

    latest_data["potability"] = calculate_potability(tds, turbidity, ph, nh3, do)

    latest_data["last_updated"] = time.time()

    try:
        with db_lock:
            db_connection.execute(
                "INSERT INTO sensor_data(timestamp, tds, turbidity, ph, temperature, predicted_nh3, predicted_do) VALUES (?,?,?,?,?,?,?)",
                (time.time(), tds, turbidity, ph, temperature, nh3, do),
            )

            db_connection.commit()

    except Exception as error:
        print(f"Database Entry Failed: {error}")

    process_alerts(tds, turbidity, ph, temperature, nh3, do)


app = FastAPI(
    title="Intelligent Sensor-Driven Modelling of Climate-Induced River Water Quality Impacts at RSET Campus",
    description="Mini Project.",
    version="1.0",
)


@app.get("/api/latest")
def get_latest():
    if latest_data["last_updated"] is not None:
        if time.time() - latest_data["last_updated"] > OFFLINE_AFTER_S:
            return {
                "status": "offline",
                "tds": None,
                "turbidity": None,
                "ph": None,
                "temperature": None,
                "predicted_nh3": None,
                "predicted_do": None,
                "nh3": None,
                "do": None,
                "potability": {
                    "status": "Insufficient Data",
                    "checks": {
                        "ph": None,
                        "tds": None,
                        "turbidity": None,
                        "nh3": None,
                        "do": None,
                    },
                    "failed_parameters": [],
                },
                "last_updated": latest_data["last_updated"],
            }

    return {"status": "online", **latest_data}


@app.get("/api/history")
def get_history(hours: int = 24):
    cutoff = time.time() - (hours * 3600)

    with db_lock:
        cursor = db_connection.execute(
            "SELECT timestamp, tds, turbidity, ph, temperature, predicted_nh3, predicted_do FROM sensor_data WHERE timestamp >= ? ORDER BY timestamp ASC",
            (cutoff,),
        )

        rows = cursor.fetchall()

    return [
        {
            "timestamp": r[0],
            "tds": r[1],
            "turbidity": r[2],
            "ph": r[3],
            "temperature": r[4],
            "predicted_nh3": r[5],
            "predicted_do": r[6],
        }
        for r in rows
    ]


@app.get("/api/alerts")
def get_alerts():
    with alert_lock:
        items = [dict(a) for a in active_alerts.values()]

    items.sort(key=lambda a: (SEVERITY_ORDER.get(a["level"], 9), -a["opened_at"]))

    return items


@app.get("/api/alerts/history")
def get_alert_history(hours: int = 168):
    cutoff = time.time() - (hours * 3600)

    with db_lock:
        cursor = db_connection.execute(
            "SELECT id, parameter, level, message, value, opened_at, resolved_at FROM alerts WHERE opened_at >= ? ORDER BY opened_at DESC LIMIT 100",
            (cutoff,),
        )

        rows = cursor.fetchall()

    return [
        {
            "id": r[0],
            "parameter": r[1],
            "level": r[2],
            "message": r[3],
            "value": r[4],
            "opened_at": r[5],
            "resolved_at": r[6],
        }
        for r in rows
    ]


app.mount("/", StaticFiles(directory="../Frontend", html=True), name="static")


def serial_reader_loop():
    while True:
        try:
            ser = serial.Serial("/dev/ttyUSB0", 115200, timeout=2)

            print("Connected to /dev/ttyUSB0 successfully.")

            while True:
                line = ser.readline().decode("utf-8", errors="ignore")

                if not line.strip():
                    continue

                print(f"Raw Serial: {repr(line)}")

                tds, turbidity_voltage, temperature, ph = read_values(line)

                if tds is None:
                    continue

                turbidity_voltage_smoothed = smooth_turbidity_voltage(turbidity_voltage)

                turbidity_ntu = voltage_to_ntu(turbidity_voltage_smoothed)

                print(
                    f"Sensor Data: TDS={tds}, "
                    f"Turbidity Voltage={turbidity_voltage:.2f} V, "
                    f"Smoothed Voltage={turbidity_voltage_smoothed:.2f} V, "
                    f"Turbidity={turbidity_ntu:.2f} NTU, "
                    f"Temp={temperature}, "
                    f"pH={ph}"
                )

                nh3, do = get_prediction(tds, turbidity_ntu, ph, temperature)

                updated_latest_data(tds, turbidity_ntu, ph, temperature, nh3, do)

                print(
                    f"Recorded: TDS={tds}, "
                    f"Turbidity={turbidity_ntu:.2f} NTU, "
                    f"Temp={temperature}, "
                    f"pH={ph}, "
                    f"NH3={nh3}, "
                    f"DO={do}"
                )

        except serial.SerialException as e:
            print(f"Serial port error: {e}. " f"Retrying in 5 seconds...")
            time.sleep(5)

        except Exception as e:
            print(f"Unexpected reader error: {e}. " f"Retrying in 5 seconds...")
            time.sleep(5)


render_thread = threading.Thread(target=serial_reader_loop, daemon=True)
render_thread.start()

watchdog_thread = threading.Thread(target=watchdog_loop, daemon=True)
watchdog_thread.start()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)