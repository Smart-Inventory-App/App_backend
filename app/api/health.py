from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "message": "Backend is running"}


@router.get("/version")
async def get_version():
    """Get API version"""
    return {"version": "1.0.0"}


@router.get("/test")
async def test_endpoint():
    """Test endpoint for frontend connection"""
    print("✅ Frontend connected to backend!")
    return {"status": "success", "message": "Connection working!"}
