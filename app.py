from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Cloud deployment is working"}
