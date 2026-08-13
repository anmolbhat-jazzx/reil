from fastapi import APIRouter

router = APIRouter()


@router.get("", response_model=list)
def list_configs():
    ...


@router.get("/{config_id}")
def get_config(config_id: str):
    ...
