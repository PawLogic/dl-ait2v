"""
ComfyUI-ServerlessHandler

Starts RunPod Serverless handler alongside ComfyUI.
Runs in a daemon thread since ComfyUI occupies the main thread.
"""
import os
import sys
import signal
import threading

if os.environ.get("RUNPOD_POD_ID"):
    def _start_handler():
        handler_dir = "/workspace/handler"
        if handler_dir not in sys.path:
            sys.path.insert(0, handler_dir)

        import runpod
        from rp_handler import handler

        # Patch: disable signal registration since we're in a thread
        _original_signal = signal.signal
        signal.signal = lambda *args, **kwargs: None

        print("[ServerlessHandler] Starting RunPod handler...")
        try:
            runpod.serverless.start({"handler": handler})
        finally:
            signal.signal = _original_signal

    t = threading.Thread(target=_start_handler, daemon=True)
    t.start()
    print("[ServerlessHandler] Handler thread launched.")
else:
    print("[ServerlessHandler] Not in serverless mode, skipping.")

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
