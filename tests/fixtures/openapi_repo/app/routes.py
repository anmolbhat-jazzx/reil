from fastapi import APIRouter

router = APIRouter()


@router.get("/documents/{id}")
def get_document(id: str):
    """Fetch one document."""
    return {}


@router.post("/documents")
def create_document(body: dict):
    """Create a document."""
    return {}
