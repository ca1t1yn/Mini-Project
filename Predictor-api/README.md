# Water Quality Prediction API

Wraps two pre-trained `RandomForestRegressor` models (NH3-N and Dissolved
Oxygen) in a FastAPI service with a `/predict` endpoint.

## Project structure

```
project/
├── app.py                 # FastAPI app (health check + /predict)
├── model/
│   ├── nh3_random_forest.pkl
│   └── do_random_forest.pkl
├── requirements.txt
└── README.md
```

## Input format (`POST /predict`)

```json
{
  "temperature": 20.0,
  "tds": 230.0,
  "turbidity": 15.0,
  "ph": 7.8
}
```

## Output format

```json
{
  "predicted_nh3": 0.1446,
  "predicted_do": 7.9007
}
```

## Run locally

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Then visit `http://127.0.0.1:8000/docs` for interactive Swagger docs,
or test with curl:

```bash
curl -X POST http://127.0.0.1:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"temperature":20.0,"tds":230.0,"turbidity":15.0,"ph":7.8}'
```

## Notes

- Models were trained with scikit-learn 1.6.1. `requirements.txt` pins
  this exact version to avoid `InconsistentVersionWarning` and any
  subtle prediction drift.
- No separate scaler/encoder is used — the models take raw
  Temperature/TDS/Turbidity/pH values directly, matching the original
  training script (`predict_water_quality.py`).
- Model files total ~90 MB. This is under GitHub's 100 MB hard file
  limit, but keep it in mind for deploy time and free-tier build
  limits.
