"""Thin wrapper: redirects stdout+stderr to verify_out.txt, then runs verify_memory."""
import sys
import traceback

outfile = open("verify_out.txt", "w", encoding="utf-8", buffering=1)
sys.stdout = outfile
sys.stderr = outfile

try:
    import verify_memory
except SystemExit as e:
    print(f"[SystemExit] {e}", flush=True)
except Exception:
    traceback.print_exc()
finally:
    outfile.flush()
    outfile.close()
