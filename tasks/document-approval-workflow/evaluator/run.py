import argparse
import json
import sys
sys.dont_write_bytecode = True
from datetime import date
from pathlib import Path


def main():
    p=argparse.ArgumentParser(); p.add_argument("--workspace",type=Path,required=True); p.add_argument("--round",required=True); p.add_argument("--output",type=Path,required=True); a=p.parse_args(); tests=[]; errors=[]
    def check(name,fn):
        try: fn(); tests.append(True)
        except Exception as exc: tests.append(False); errors.append(f"{name}: {type(exc).__name__}: {exc}")
    try:
        sys.path.insert(0,str(a.workspace/"src")); from document_approval_workflow import ApprovalWorkflow; i=int(a.round[1:])
        def workflow(**kw):
            if i>=1: kw.setdefault("finance_threshold_cents",1000)
            if i>=2: kw.setdefault("department_managers",{"eng":"mary"})
            if i>=5: kw.setdefault("finance_approver","frank")
            return ApprovalWorkflow(**kw)
        def base():
            w=workflow(); req=w.submit("alice","eng",2000); w.approve(req["id"],"mary","manager"); assert w.get(req["id"])["status"]=="pending_finance"; w.approve(req["id"],"frank","finance"); assert w.get(req["id"])["status"]=="approved"
            own=w.submit("alice","eng",2000)
            try: w.approve(own["id"],"alice","manager")
            except ValueError: return
            raise AssertionError("self approval")
        check("sequential approval",base)
        if i>=1:
            def threshold():
                w=workflow(); req=w.submit("alice","eng",1000); w.approve(req["id"],"mary","manager"); assert w.get(req["id"])["status"]=="approved"
            check("finance threshold",threshold)
        if i>=2:
            def manager():
                w=workflow(); req=w.submit("alice","eng",100)
                try: w.approve(req["id"],"other","manager")
                except ValueError: return
                raise AssertionError("wrong manager")
            check("department manager",manager)
        if i>=3:
            def history():
                w=workflow(); req=w.submit("alice","eng",100,comment="needed"); w.comment(req["id"],"bob","reviewing"); w.approve(req["id"],"mary","manager",comment="ok"); h=w.history(req["id"]); assert [x["action"] for x in h]==["submitted","commented","approved_manager"] and [x["sequence"] for x in h]==[1,2,3]
            check("audit history",history)
        if i>=4:
            def resubmit():
                w=workflow(); req=w.submit("alice","eng",100); w.reject(req["id"],"mary","manager"); w.resubmit(req["id"],"alice",amount_cents=200); assert w.get(req["id"])["status"]=="pending_manager" and len(w.history(req["id"]))==3
            check("resubmission",resubmit)
        if i>=5:
            def delegation():
                w=workflow(); w.delegate("mary","dana",date(2026,1,1),date(2026,1,31)); req=w.submit("alice","eng",100); w.approve(req["id"],"dana","manager",on_date=date(2026,1,15)); assert w.get(req["id"])["status"]=="approved" and w.history(req["id"])[-1]["actor"]=="dana"
            check("delegation",delegation)
        if i>=6:
            def single_hop():
                w=workflow(); w.delegate("mary","dana",date(2026,1,1),date(2026,1,31)); w.delegate("dana","erin",date(2026,1,1),date(2026,1,31)); req=w.submit("alice","eng",100)
                try: w.approve(req["id"],"erin","manager",on_date=date(2026,1,15))
                except ValueError: return
                raise AssertionError("recursive delegation")
            check("single-hop delegation",single_hop)
        status,build="ok","passed"
    except Exception as exc: tests.append(False); errors.append(f"import/build: {type(exc).__name__}: {exc}"); status,build="error","failed"
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps({"status":status,"tests_passed":sum(tests),"tests_total":len(tests),"build_status":build,"errors":errors},default=str)+"\n")
if __name__=="__main__": main()
