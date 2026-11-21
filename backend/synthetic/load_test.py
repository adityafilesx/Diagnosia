"""A load test for SQLite under a clinic's working pattern, with no keys and no network.

    python -m backend.synthetic.load_test                      # 20 staff, 5 slow AI calls at a time, 30 seconds
    python -m backend.synthetic.load_test --staff 40 --seconds 60
    python -m backend.synthetic.load_test --pause 0            # every writer saves non-stop: a stress test

It runs against a throwaway database in a temporary folder, never the real one. Staff threads keep
writing (new patients, transcript lines, tasks) while other threads draft ClinScribe notes through a
fake AI that takes a few seconds, as the real one does. Each person pauses between saves (one second by
default, far busier than real clinic work). It reports how long writes took and how many were refused
as busy or failed.

The threshold for moving to PostgreSQL (audit plan WI-261): at the expected pilot load, 20 staff with
5 AI calls in flight, move when the 95th percentile write takes longer than 250 ms or any write is
refused as busy. Numbers are recorded in docs/BASELINES.md.
"""
import argparse
import os
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, List

P95_LIMIT_MS = 250
BUSY_LIMIT = 0


def run(staff: int, drafters: int, seconds: float, ai_seconds: float, pause: float = 1.0) -> Dict:
    from fastapi.testclient import TestClient

    from backend import llm, ratelimit
    from backend.app import app
    from backend.clinscribe.drafting import NoteDraft
    from backend.config import settings
    from backend.tests.conftest import Person, grant

    folder = Path(tempfile.mkdtemp(prefix="curai-load-"))
    settings.db_path = folder / "load.db"
    settings.documents_dir = folder / "documents"
    settings.document_key_file = ""

    def slow_ai(*args, **options):
        time.sleep(ai_seconds)
        return NoteDraft.model_validate({
            "sections": [{"heading": "Subjective", "statements": [{
                "text": "Cough for three days", "origin": "clinician_statement", "evidence_segments": [1],
                "uncertain": False, "uncertainty_reason": "",
            }]}],
            "missing_information": [],
        })

    llm.ask = slow_ai
    latencies: List[float] = []
    outcomes: Dict[str, int] = {"ok": 0, "busy": 0, "error": 0, "drafts": 0, "draft_errors": 0}
    lock = threading.Lock()
    stop = 0.0  # set once setup is done, so a slow start-up can't eat the measured window

    with ratelimit.suspended(), TestClient(app):
        doctors = [Person("doctor", "Load", f"Doctor{n}", f"load{n}@example.com") for n in range(staff + drafters)]
        charts = []
        for doctor in doctors:
            chart = doctor.post("/api/patients", json={"first_name": "Synthetic", "last_name": "Load"}).json()
            grant(doctor, chart["id"], "ai_scribe")
            encounter = doctor.post(f"/api/patients/{chart['id']}/encounters", json={"reason": "Load"}).json()
            charts.append((chart, encounter))

        def writer(index: int) -> None:
            doctor, (chart, _) = doctors[index], charts[index]
            count = 0
            while time.monotonic() < stop:
                count += 1
                started = time.perf_counter()
                try:
                    if count % 2:
                        response = doctor.post("/api/patients", json={"first_name": "Synthetic", "last_name": f"W{count}"})
                    else:
                        response = doctor.post(f"/api/patients/{chart['id']}/tasks", json={"title": f"Load task {count}"})
                    status_code = response.status_code
                except Exception as error:  # the test client re-raises server errors, such as "database is locked"
                    status_code = 503 if "locked" in str(error) or "busy" in str(error) else 500
                took = (time.perf_counter() - started) * 1000
                with lock:
                    latencies.append(took)
                    kind = "ok" if status_code < 400 else "busy" if status_code == 503 else "error"
                    outcomes[kind] += 1
                time.sleep(pause)

        def drafter(index: int) -> None:
            doctor, (chart, encounter) = doctors[index], charts[index]
            while time.monotonic() < stop:
                session = doctor.post(f"/api/addons/clinscribe/encounters/{encounter['id']}/sessions", json={}).json()
                base = f"/api/addons/clinscribe/sessions/{session['id']}"
                doctor.post(f"{base}/segments", json={"text": "I have had a cough for three days", "speaker": "patient"})
                doctor.post(f"{base}/state", json={"state": "stopped"})
                try:
                    drafted = doctor.post(f"{base}/draft-note", json={"template": "soap"}).status_code == 201
                except Exception:
                    drafted = False
                with lock:
                    outcomes["drafts" if drafted else "draft_errors"] += 1

        stop = time.monotonic() + seconds
        threads = [threading.Thread(target=writer, args=(n,)) for n in range(staff)]
        threads += [threading.Thread(target=drafter, args=(staff + n,)) for n in range(drafters)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    ordered = sorted(latencies) or [0.0]
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    return {
        "staff": staff, "drafters": drafters, "seconds": seconds, "ai_seconds": ai_seconds, "pause": pause,
        "writes": len(latencies), "p50_ms": statistics.median(ordered), "p95_ms": p95, "max_ms": ordered[-1],
        **outcomes,
        "move_to_postgresql": p95 > P95_LIMIT_MS or outcomes["busy"] > BUSY_LIMIT,
    }


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--staff", type=int, default=20)
    parser.add_argument("--drafters", type=int, default=5)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--ai-seconds", type=float, default=3)
    parser.add_argument("--pause", type=float, default=1.0, help="seconds each person waits between saves")
    args = parser.parse_args(arguments)
    os.environ.setdefault("CURAI_NEURAL_TTS", "0")
    result = run(args.staff, args.drafters, args.seconds, args.ai_seconds, args.pause)
    print(f"{result['staff']} staff writing (a save every {result['pause']} s each), {result['drafters']} notes drafting "
          f"at a time ({result['ai_seconds']} s AI), {result['seconds']} s")
    print(f"writes {result['writes']}: ok {result['ok']}, busy (503) {result['busy']}, other errors {result['error']}")
    print(f"write latency: p50 {result['p50_ms']:.0f} ms, p95 {result['p95_ms']:.0f} ms, max {result['max_ms']:.0f} ms")
    print(f"notes drafted {result['drafts']}, failed {result['draft_errors']}")
    print(f"threshold: p95 above {P95_LIMIT_MS} ms or any busy write means move to PostgreSQL -> "
          f"{'MOVE' if result['move_to_postgresql'] else 'stay on SQLite'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
