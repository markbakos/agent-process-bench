import argparse
import json
import sys
sys.dont_write_bytecode = True
from datetime import date
from decimal import Decimal
from pathlib import Path


def main():
    p=argparse.ArgumentParser(); p.add_argument("--workspace",type=Path,required=True); p.add_argument("--round",required=True); p.add_argument("--output",type=Path,required=True); a=p.parse_args(); tests=[]; errors=[]
    def check(name,fn):
        try: fn(); tests.append(True)
        except Exception as exc: tests.append(False); errors.append(f"{name}: {type(exc).__name__}: {exc}")
    try:
        sys.path.insert(0,str(a.workspace/"src")); from expense_reimbursement import ExpenseEngine; i=int(a.round[1:]); d=date(2026,1,10)
        def engine(**kw):
            if i>=1: kw.setdefault("receipt_thresholds",{"meals":2500,"travel":5000})
            if i>=2: kw.setdefault("small_claim_threshold_cents",1000)
            return ExpenseEngine(**kw)
        def item(amount,**kw): return {"category":"meals","date":d,"merchant":"Cafe","amount_cents":amount,**kw}
        def base():
            e=engine(); c=e.submit("alice",[item(2500)]); assert c["total_cents"]==2500 and c["status"]==("pending_manager" if i<2 else "pending_manager")
            try: e.submit("bob",[item(2501)])
            except ValueError: pass
            else: raise AssertionError("receipt not required")
            approved=e.submit("bob",[item(1000)])
            if approved["status"]=="pending_manager": e.approve_manager(approved["id"])
            assert e.get(approved["id"])["status"]=="approved"
        check("claim and receipt",base)
        if i>=1:
            def category_receipt():
                e=engine(); assert e.submit("a",[{"category":"travel","date":d,"merchant":"Rail","amount_cents":4000}])
            check("category thresholds",category_receipt)
        if i>=2:
            check("small auto approval",lambda: (engine().submit("a",[item(1000)])["status"]=="approved") or (_ for _ in ()).throw(AssertionError()))
        if i>=3:
            def currency():
                e=engine(); c=e.submit("a",[item(1000,currency="EUR")],exchange_rates={"EUR":"1.075"}); assert c["total_cents"]==1075
            check("currency conversion",currency)
        def over_cap():
            e=engine(); big=item(100001,receipt=True)
            if i<4:
                try: e.submit("a",[big])
                except ValueError: return
                raise AssertionError("cap exceeded")
            c=e.submit("a",[big]); assert c["status"]=="pending_manager"; e.approve_manager(c["id"]); assert e.get(c["id"])["status"]=="pending_finance"; e.approve_finance(c["id"]); assert e.get(c["id"])["status"]=="approved"
        check("monthly threshold policy",over_cap)
        if i>=5:
            def duplicates():
                e=engine(); first=e.submit("a",[item(1000)]); second=e.submit("a",[item(1000)]); assert second["duplicates"]==[{"item_index":0,"claim_id":first["id"]}]
            check("duplicate flag",duplicates)
        if i>=6:
            def aggregate_round():
                e=engine(); items=[item(1,currency="EUR",merchant="A"),item(1,currency="EUR",merchant="B")]; c=e.submit("a",items,exchange_rates={"EUR":Decimal("0.5")}); assert c["total_cents"]==1 and [x["base_amount_cents"] for x in c["items"]]==[1,0]
            check("aggregate rounding",aggregate_round)
        status,build="ok","passed"
    except Exception as exc: tests.append(False); errors.append(f"import/build: {type(exc).__name__}: {exc}"); status,build="error","failed"
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps({"status":status,"tests_passed":sum(tests),"tests_total":len(tests),"build_status":build,"errors":errors},default=str)+"\n")
if __name__=="__main__": main()
