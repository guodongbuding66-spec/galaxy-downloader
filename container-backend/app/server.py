from .main import app
from .playback import router as playback_router

# Keep the established parser/download app intact and register playback as a
# separate router so preview streaming can evolve independently from final-file
# download/FFmpeg behavior.
app.include_router(playback_router)
