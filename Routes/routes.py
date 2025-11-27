from fastapi import APIRouter
from service.PowerControl import router as powercontrol_router

router = APIRouter()
router.include_router(powercontrol_router)