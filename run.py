"""
ReupMaster Pro - Entry Point
Run with: python run.py
"""
import sys
import os
import asyncio
import logging

# Fix Windows console encoding
if sys.platform == 'win32':
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

    # ── Fix Windows asyncio: use ProactorEventLoop ──
    # SelectorEventLoop on Windows produces harmless but extremely noisy
    # "_SelectorSocketTransport._write_send()" errors during large socket
    # writes (e.g. uploading videos via httpx to Facebook).
    # ProactorEventLoop uses IOCP and handles this correctly.
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    # Also suppress any residual asyncio transport warnings
    logging.getLogger('asyncio').setLevel(logging.CRITICAL)

import uvicorn
from app.config import settings

if __name__ == "__main__":
    print()
    print("  =============================================")
    print("    ReupMaster Pro v2.0.0")
    print("    Social Media Reup & Scheduling Tool")
    print("  =============================================")
    print()
    print(f"  Starting server at http://localhost:{settings.PORT}")
    print(f"  Downloads: {settings.DOWNLOAD_DIR}")
    print(f"  Processed: {settings.PROCESSED_DIR}")
    print(f"  AI Provider: {settings.AI_PROVIDER}")
    print()

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
