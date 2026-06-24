import sys
sys.path.insert(0, r"C:\Users\Santoyle\Projects\MoneyPrinterTurbo")
import uvicorn
from app.config import config
uvicorn.run(
    app="app.asgi:app",
    host=config.listen_host,
    port=config.listen_port,
    reload=False,
    log_level="info",
)
