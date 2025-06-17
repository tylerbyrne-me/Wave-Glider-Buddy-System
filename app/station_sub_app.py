# app/station_sub_app.py
from fastapi import FastAPI

# Create a new FastAPI instance for the sub-application
station_api = FastAPI()
print(
    f"DEBUG_PRINT: station_sub_app.py - station_api instance created: {type(station_api)}"
)

# --- Minimal Test Route for Sub-App ---
print("DEBUG_PRINT: station_sub_app.py - Defining GET /sub_app_minimal_test")


@station_api.get("/sub_app_minimal_test")
async def sub_app_minimal_test_endpoint():
    print(
        "DEBUG_PRINT: station_sub_app.py - /sub_app_minimal_test endpoint was called!"
    )
    return {"message": "Sub-application minimal test route is working!"}


print(
    "DEBUG_PRINT: station_sub_app.py - /sub_app_minimal_test definition processed by Python interpreter."
)
