import threading
import time
import serial
import json
import requests
import sqlite3

from serial.tools import list_ports
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

db_connection = sqlite3.connect('sensor_data.db', check_same_thread=False)
db_connection.execute('''CREATE TABLE IF NOT EXISTS sensor_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    timestamp REAL NOT NULL, 
    tds REAL, 
    turbidity REAL, 
    ph REAL, 
    temperature REAL, 
    predicted_nh3 REAL, 
    predicted_do REAL
)''')

latest_data = {
    "tds": None,
    "turbidity": None,
    "ph": None,
    "temperature": None,
    "predicted_nh3": None,
    "predicted_do": None,
    "nh3": None,
    "do": None,
    "last_updated": None
}



def read_values(line):
    try:
        parts = line.strip().split('|')

        temperatureText = parts[0].split(':')[1].replace('°C', '').strip()
        tdsText = parts[1].split(':')[1].replace('PPM', '').strip()
        turbidityText = parts[2].split(':')[1].replace('NTU', '').strip()
        phText = parts[3].split(':')[1].strip()

        temperatureValue = float(temperatureText)
        tdsValue = float(tdsText)
        turbidityValue = float(turbidityText)
        phValue = float(phText)

        return tdsValue, turbidityValue, temperatureValue, phValue

    except Exception as error:
        print(f"Parse Error: {error}")
        print(f"Received: {repr(line)}")
        return None, None, None, None




def get_prediction(tds, turbidity, ph, temperature):
    try:
        url = "https://mini-project-buj5.onrender.com/predict"
        predictions = {
            "tds": tds,
            "turbidity": turbidity,
            "ph": ph,
            "temperature": temperature
        }

        response = requests.post(url, json=predictions, timeout=10)
        response.raise_for_status()

        data = response.json()

        nh3 = data.get("predicted_nh3")
        do = data.get("predicted_do")

        return nh3, do
    except Exception as error:
        print(f"Prediction API Error: {error}")
        return None, None


def updated_latest_data(tds, turbidity, ph, temperature, nh3, do):
    latest_data["tds"] = tds
    latest_data["turbidity"] = turbidity
    latest_data["ph"] = ph
    latest_data["temperature"] = temperature
    latest_data["predicted_nh3"] = nh3
    latest_data["predicted_do"] = do
    latest_data["nh3"] = nh3
    latest_data["do"] = do
    latest_data["last_updated"] = time.time()

    try:
        db_connection.execute(
            "INSERT INTO sensor_data(timestamp, tds, turbidity, ph, temperature, predicted_nh3, predicted_do) VALUES (?,?,?,?,?,?,?)",
            (time.time(), tds, turbidity, ph, temperature, nh3, do)
        )
        db_connection.commit()
    except Exception as error:
        print(f"Database Entry Failed: {error}")


app = FastAPI(
    title="Intelligent Sensor-Driven Modelling of Climate-Induced River Water Quality Impacts at RSET Campus",
    description="Mini Project.",
    version="1.0"
)


@app.get("/api/latest")
def get_latest():
    if latest_data["last_updated"] is not None:
        if time.time() - latest_data["last_updated"] > 15:
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
                "last_updated": latest_data["last_updated"]
            }

    return {
        "status": "online",
        **latest_data
    }


@app.get("/api/history")
def get_history(hours: int = 24):
    cutoff = time.time() - (hours * 3600)

    cursor = db_connection.execute(
        "SELECT timestamp, tds, turbidity, ph, temperature, predicted_nh3, predicted_do FROM sensor_data WHERE timestamp >= ? ORDER BY timestamp ASC",
        (cutoff,)
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
            "predicted_do": r[6]
        }
        for r in rows
    ]


app.mount("/", StaticFiles(directory="../Frontend", html=True), name="static")


def serial_reader_loop():
    while True:
        try:
            ser = serial.Serial('COM3', 115200, timeout=2)
            print("Connected to COM3 successfully.")

            while True:
                line = ser.readline().decode('utf-8', errors="ignore")

                if not line.strip():
                    continue

                print(f"Raw Serial: {repr(line)}")

                tds, turbidity, temperature, ph = read_values(line)

                if tds is None:
                    continue

                print(
                    f"Sensor Data: TDS={tds}, "
                    f"Turbidity={turbidity}, "
                    f"Temp={temperature}, "
                    f"pH={ph}"
                )

                nh3, do = get_prediction(tds, turbidity, ph, temperature)

                updated_latest_data(
                    tds,
                    turbidity,
                    ph,
                    temperature,
                    nh3,
                    do
                )

                print(
                    f"Recorded: TDS={tds}, "
                    f"Turbidity={turbidity}, "
                    f"Temp={temperature}, "
                    f"pH={ph}, "
                    f"NH3={nh3}, "
                    f"DO={do}"
                )

        except serial.SerialException as e:
            print(f"Serial port COM3 error: {e}. Retrying in 5 seconds...")
            time.sleep(5)

        except Exception as e:
            print(f"Unexpected reader error: {e}. Retrying in 5 seconds...")
            time.sleep(5)


render_thread = threading.Thread(target=serial_reader_loop, daemon=True)
render_thread.start()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)