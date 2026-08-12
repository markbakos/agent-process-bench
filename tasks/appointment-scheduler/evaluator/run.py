import argparse
import json
import sys
sys.dont_write_bytecode = True
from datetime import datetime, time
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", type=Path, required=True); p.add_argument("--round", required=True); p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(); tests = []; errors = []
    def check(name, fn):
        try: fn(); tests.append(True)
        except Exception as exc: tests.append(False); errors.append(f"{name}: {type(exc).__name__}: {exc}")
    try:
        sys.path.insert(0, str(a.workspace / "src")); from appointment_scheduler import Scheduler
        i = int(a.round[1:])
        def base():
            s = Scheduler(); day = datetime(2026, 8, 11, 9)
            first = s.book("p1", day); assert first["duration_minutes"] == 30
            try: s.book("p1", day.replace(minute=15))
            except ValueError: pass
            else: raise AssertionError("overlap accepted")
            assert s.book("p2", day)["id"] != first["id"]
            s.cancel(first["id"]); assert s.book("p1", day)["start"] == day
        check("booking overlap and cancellation", base)
        def days():
            s = Scheduler(); monday = datetime(2026, 8, 10, 9); saturday = datetime(2026, 8, 15, 12, 30)
            if i == 0:
                assert s.book("p", monday); invalid = saturday
            else:
                assert s.book("p", saturday); invalid = monday
            try: s.book("q", invalid)
            except ValueError: return
            raise AssertionError("closed day accepted")
        check("operating days", days)
        if i >= 2:
            def duration():
                s = Scheduler(); start = datetime(2026, 8, 11, 15, 30); appt = s.book("p", start, duration_minutes=90); assert appt["duration_minutes"] == 90
                try: s.book("q", start, duration_minutes=45)
                except ValueError: return
                raise AssertionError("invalid duration")
            check("variable duration", duration)
        if i >= 3:
            def provider_hours():
                hours = {"night": {1: (time(18), time(20))}}; s = Scheduler(provider_hours=hours)
                assert s.book("night", datetime(2026, 8, 11, 18))
                try: s.book("night", datetime(2026, 8, 11, 10))
                except ValueError: return
                raise AssertionError("provider hours ignored")
            check("provider hours", provider_hours)
        if i >= 4:
            def recurring():
                s = Scheduler(); start = datetime(2026, 8, 11, 10); s.book("p", start.replace(day=18))
                before = len(s.list_appointments())
                if i == 4:
                    result = s.book_recurring("p", start, 3); assert len(result["created"]) == 2 and len(result["skipped"]) == 1
                else:
                    try: s.book_recurring("p", start, 3)
                    except ValueError: assert len(s.list_appointments()) == before
                    else: raise AssertionError("non-atomic recurrence")
            check("recurring policy", recurring)
        if i >= 6:
            def history():
                s = Scheduler(); appt = s.book("p", datetime(2026, 8, 11, 10)); s.cancel(appt["id"])
                assert s.list_appointments() == [] and s.history()[0]["status"] == "cancelled"
                assert s.book("p", datetime(2026, 8, 11, 10))
            check("cancellation history", history)
        status, build = "ok", "passed"
    except Exception as exc:
        tests.append(False); errors.append(f"import/build: {type(exc).__name__}: {exc}"); status, build = "error", "failed"
    a.output.parent.mkdir(parents=True, exist_ok=True); a.output.write_text(json.dumps({"status": status, "tests_passed": sum(tests), "tests_total": len(tests), "build_status": build, "errors": errors}) + "\n")
if __name__ == "__main__": main()
