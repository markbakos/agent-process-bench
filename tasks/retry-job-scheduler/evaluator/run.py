import argparse
import json
import sys
sys.dont_write_bytecode = True
from datetime import datetime, timedelta
from pathlib import Path


def main():
    p=argparse.ArgumentParser(); p.add_argument("--workspace",type=Path,required=True); p.add_argument("--round",required=True); p.add_argument("--output",type=Path,required=True); a=p.parse_args(); tests=[]; errors=[]
    def check(name,fn):
        try: fn(); tests.append(True)
        except Exception as exc: tests.append(False); errors.append(f"{name}: {type(exc).__name__}: {exc}")
    try:
        sys.path.insert(0,str(a.workspace/"src")); from retry_job_scheduler import JobScheduler; i=int(a.round[1:]); now=datetime(2026,1,1)
        def scheduler(**kw):
            if i>=1: kw.setdefault("max_backoff_seconds",90)
            kw.setdefault("max_attempts",3)
            return JobScheduler(base_delay_seconds=60,**kw)
        def base():
            s=scheduler(); s.schedule("a",now); s.schedule("b",now); assert s.pop_due(now)["id"]=="a"; s.record_result("a",False,now); assert s.get("a")["due_at"]==now+timedelta(seconds=60); assert s.pop_due(now)["id"]=="b"; s.record_result("b",True,now); assert s.get("b")["status"]=="succeeded"
        check("FIFO and retry",base)
        if i>=1:
            def cap():
                s=scheduler(); s.schedule("a",now); s.pop_due(now); s.record_result("a",False,now); s.pop_due(now+timedelta(seconds=60)); s.record_result("a",False,now+timedelta(seconds=60)); assert s.get("a")["due_at"]==now+timedelta(seconds=150)
            check("backoff cap",cap)
        if i>=2:
            def recurring():
                s=scheduler(max_attempts=1); s.schedule("daily",now,recurrence_seconds=60); assert s.pop_due(now)["id"]=="daily#1"; s.record_result("daily#1",False,now)
                if i<6: assert s.get("daily#2")["due_at"]==now+timedelta(seconds=60)
                else:
                    try: s.get("daily#2")
                    except KeyError: pass
                    else: raise AssertionError("continued after failure")
                    s.resume("daily",now+timedelta(seconds=120)); assert s.get("daily#2")["due_at"]==now+timedelta(seconds=120)
            check("recurrence failure policy",recurring)
        if i>=3:
            def permanent():
                s=scheduler(); s.schedule("a",now); s.pop_due(now); s.record_result("a",False,now,failure_kind="permanent"); assert s.get("a")["status"]=="failed" and s.pop_due(now+timedelta(days=1)) is None
            check("permanent failure",permanent)
        if i>=4:
            def dependency():
                s=scheduler(); s.schedule("a",now); s.schedule("b",now,dependencies=["a"]); assert s.pop_due(now)["id"]=="a"; assert s.pop_due(now) is None; s.record_result("a",True,now); assert s.pop_due(now)["id"]=="b"
            check("dependencies",dependency)
        if i>=5:
            def skipped():
                s=scheduler(max_attempts=1); s.schedule("a",now); s.schedule("b",now,dependencies=["a"]); s.schedule("c",now,dependencies=["b"]); s.pop_due(now); s.record_result("a",False,now); assert s.get("b")["status"]=="skipped" and s.get("c")["status"]=="skipped"
            check("failed dependency",skipped)
        status,build="ok","passed"
    except Exception as exc: tests.append(False); errors.append(f"import/build: {type(exc).__name__}: {exc}"); status,build="error","failed"
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps({"status":status,"tests_passed":sum(tests),"tests_total":len(tests),"build_status":build,"errors":errors},default=str)+"\n")
if __name__=="__main__": main()
