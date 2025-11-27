import asyncio
import logging
from fastapi import FastAPI
from Routes.routes import router  
from service.IPMI import main

app = FastAPI()
app.include_router(router)

logging.basicConfig(level=logging.INFO)

async def periodic_collector():
    logging.info("Started periodic_collector task")
    try:
        while True:
            try:
                main()
                logging.info("Collector ran successfully")
            except Exception as e:
                logging.error(f"Collector error: {e}")
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        logging.info("Periodic collector cancelled due to shutdown.")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(periodic_collector())