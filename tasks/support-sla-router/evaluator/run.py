import argparse
import json
import sys
sys.dont_write_bytecode = True
from datetime import datetime
from pathlib import Path


def main():
    p=argparse.ArgumentParser(); p.add_argument("--workspace",type=Path,required=True); p.add_argument("--round",required=True); p.add_argument("--output",type=Path,required=True); a=p.parse_args(); tests=[]; errors=[]
    def check(name,fn):
        try: fn(); tests.append(True)
        except Exception as exc: tests.append(False); errors.append(f"{name}: {type(exc).__name__}: {exc}")
    try:
        sys.path.insert(0,str(a.workspace/"src")); from support_sla_router import SLARouter; i=int(a.round[1:]); created=datetime(2026,8,14,16,30)
        def router(**kw):
            base={"category_queues":{"billing":"money"},"priority_sla_minutes":{"high":120}}
            if i>=3: base["priority_queues"]={"high":"urgent"}
            base.update(kw); return SLARouter(**base)
        def base():
            t=router().create_ticket("billing","high",created); assert t["queue"]==("money" if i<3 else "urgent")
            unknown=router().create_ticket("unknown","high",created); assert unknown["queue"]==("general" if i<3 else "urgent")
            assert t["deadline"]==(datetime(2026,8,14,18,30) if i<2 else datetime(2026,8,17,10,30))
        check("route and deadline",base)
        if i>=1 and i<5:
            def vip_table():
                t=router(vip_sla_minutes={"high":30}).create_ticket("billing","high",created,vip=True); assert t["deadline"]==(datetime(2026,8,14,17) if i<2 else datetime(2026,8,14,17))
            check("VIP table",vip_table)
        if i>=4:
            def escalation():
                kwargs={"vip_reduction_percent":50,"minimum_sla_minutes":45} if i>=5 else {}
                r=router(**kwargs); t=r.create_ticket("billing","high",datetime(2026,8,14,9))
                if i<6:
                    assert not r.is_escalation_eligible(t,datetime(2026,8,14,10,35)); assert r.is_escalation_eligible(t,datetime(2026,8,14,10,36))
                else:
                    assert not r.is_escalation_eligible(t,t["deadline"]); assert r.is_escalation_eligible(t,t["deadline"].replace(minute=t["deadline"].minute+1))
            check("escalation policy",escalation)
        if i>=5:
            def vip_reduction():
                t=router(vip_reduction_percent=75,minimum_sla_minutes=45).create_ticket("billing","high",datetime(2026,8,14,9),vip=True); assert t["sla_minutes"]==45 and t["deadline"]==datetime(2026,8,14,9,45)
            check("VIP reduction",vip_reduction)
        status,build="ok","passed"
    except Exception as exc: tests.append(False); errors.append(f"import/build: {type(exc).__name__}: {exc}"); status,build="error","failed"
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps({"status":status,"tests_passed":sum(tests),"tests_total":len(tests),"build_status":build,"errors":errors},default=str)+"\n")
if __name__=="__main__": main()
