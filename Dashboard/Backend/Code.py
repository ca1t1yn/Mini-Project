import threading
import time
import serial
import json
import requests

from serial.tools import list_ports
from fastapi import FastAPI

latest_data={"tds":None,"turbidity":None,"ph":None,"temperature":None,"predicted_NH3":None,"predicted_DO":None,"last_updated":None}

def read_values(line):
    try:
        parts=line.split(',')
        tdsText=parts[0].split(':')
        turbidityText=parts[1].split(':')
        tdsValue=float(tdsText[1])
        turbidityValue=float(turbidityText[1])
        return tdsValue, turbidityValue

    except Exception as error:
        return None, None

def get_prediction(tds, turbidity, ph, temperature):
    try:
        url="https://mini-project-buj5.onrender.com/predict"
        predictions={"tds":tds,"turbidity":turbidity,"ph":ph, "temperature":temperature}

        response=requests.post(url,json=predictions,timeout=90)
        data=response.json()

        nh3=data["predicted_nh3"]
        do=data["predicted_do"]

        return nh3,do

    except Exception as error:
        return None,None

def updated_latest_data(tds,turbidity,ph,temperature,nh3,do):
    latest_data["tds"]=tds
    latest_data["turbidity"]=turbidity
    latest_data["ph"]=ph
    latest_data["temperature"]=temperature
    latest_data["nh3"]=nh3
    latest_data["do"]=do
    latest_data["last_updated"]=time.time()

app=FastAPI(title="Intelligent Sensor-Driven Modelling of Climate-Induced River Water Quality Impacts at RSET Campus",
                description="Mini Project.",version="1.0")
@app.get("/api/latest")
def get_latest():
    return latest_data

def serial_reader_loop():
    ser=serial.Serial('/dev/ttyUSB0',115200,timeout=2)

    while True:
        line=ser.readline().decode('utf-8',errors="ignore")
        if not line.strip():
            continue

        tds,turbidity=read_values(line)
        if tds is None:
            continue
        nh3,do=get_prediction(tds,turbidity,latest_data["ph"],latest_data["temperature"])
        updated_latest_data(tds,turbidity,latest_data["ph"],latest_data["temperature"],nh3,do)
        print(f"TDS={tds}, Turbidity={turbidity},NH3={nh3},DO={do}")

render_thread=threading.Thread(target=serial_reader_loop, daemon=True)
render_thread.start()
