from fastapi import APIRouter

router = APIRouter()


@router.get("/{widget_id}")
def get_widget(widget_id: str):
    ...
