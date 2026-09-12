"""
Water Quality Prediction API
-----------------------------
Wraps two already-trained RandomForestRegressor models
(NH3-N and Dissolved Oxygen) behind a simple REST API.

Endpoints:
    GET  /         -> health check
    POST /predict  -> run prediction on sensor input
"""

import os
import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 1. Load the trained models ONCE at startup (not per-request)
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "model")

NH3_MODEL_PATH = os.path.join(MODEL_DIR, "nh3_random_forest_50trees.pkl")
DO_MODEL_PATH = os.path.join(MODEL_DIR, "do_random_forest_75trees.pkl")

try:
    nh3_model = joblib.load(NH3_MODEL_PATH)
    do_model = joblib.load(DO_MODEL_PATH)
except FileNotFoundError as e:
    raise RuntimeError(
        f"Could not find model file: {e}. "
        f"Make sure nh3_random_forest_50trees.pkl and do_random_forest_75trees.pkl "
        f"are inside the 'model/' folder."
    ) from e

# The exact column names/order the models were trained on.
# (Taken directly from model.feature_names_in_ - do not change.)
FEATURE_ORDER = ["Temperature", "TDS", "Turbidity", "pH"]

# ---------------------------------------------------------------------------
# 2. Define the request/response schema
# ---------------------------------------------------------------------------
class SensorInput(BaseModel):
    temperature: float = Field(..., description="Water temperature in °C")
    tds: float = Field(..., description="Total Dissolved Solids (ppm)")
    turbidity: float = Field(..., description="Turbidity (NTU)")
    ph: float = Field(..., description="pH value")

    class Config:
        json_schema_extra = {
            "example": {
                "temperature": 20.0,
                "tds": 230.0,
                "turbidity": 15.0,
                "ph": 7.8,
            }
        }


class PredictionOutput(BaseModel):
    predicted_nh3: float
    predicted_do: float


# ---------------------------------------------------------------------------
# 3. Create the app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Water Quality Prediction API",
    description="Predicts NH3-N and Dissolved Oxygen from sensor readings.",
    version="1.0.0",
)


@app.get("/")
def health_check():
    """Simple endpoint to confirm the service is deployed and running."""
    return {"status": "Cloud deployment is working"}


@app.post("/predict", response_model=PredictionOutput)
def predict(payload: SensorInput):
    """
    Accepts sensor readings and returns predicted NH3-N and DO values.
    Applies the exact same input format the models were trained on
    (a DataFrame with columns: Temperature, TDS, Turbidity, pH).
    """
    try:
        sensor_data = pd.DataFrame(
            [[payload.temperature, payload.tds, payload.turbidity, payload.ph]],
            columns=FEATURE_ORDER,
        )

        predicted_nh3 = float(nh3_model.predict(sensor_data)[0])
        predicted_do = float(do_model.predict(sensor_data)[0])

        return PredictionOutput(predicted_nh3=predicted_nh3, predicted_do=predicted_do)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction failed: {e}")


# ---------------------------------------------------------------------------
# 4. Local dev entrypoint (cloud platforms will use the start command instead)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
