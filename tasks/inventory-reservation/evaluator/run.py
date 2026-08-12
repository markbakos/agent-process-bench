import argparse
import json
import sys
sys.dont_write_bytecode = True
from pathlib import Path


def main():
    p=argparse.ArgumentParser(); p.add_argument("--workspace",type=Path,required=True); p.add_argument("--round",required=True); p.add_argument("--output",type=Path,required=True); a=p.parse_args()
    tests=[]; errors=[]
    def check(name,fn):
        try: fn(); tests.append(True)
        except Exception as exc: tests.append(False); errors.append(f"{name}: {type(exc).__name__}: {exc}")
    try:
        sys.path.insert(0,str(a.workspace/"src")); import inventory_reservation as m; Inventory=m.Inventory; i=int(a.round[1:])
        def amount(value): return value["available"] if isinstance(value,dict) else value
        def base():
            inv=Inventory({("sku","a"):10}); r=inv.reserve("sku","a",4); assert amount(inv.availability("sku","a"))==6
            inv.release(r["id"]); assert amount(inv.availability("sku","a"))==10
            r=inv.reserve("sku","a",3); inv.commit(r["id"]); assert amount(inv.availability("sku","a"))==7
        check("reservation lifecycle",base)
        def oversell():
            inv=Inventory({("sku","a"):2})
            if i<2:
                try: inv.reserve("sku","a",3)
                except ValueError: return
                raise AssertionError("oversell accepted")
            inv.reserve("sku","a",5); assert amount(inv.availability("sku","a"))==-3
        check("oversell policy",oversell)
        if i>=1:
            def idem():
                inv=Inventory({("sku","a"):10}); x=inv.reserve("sku","a",3,idempotency_key="k"); y=inv.reserve("sku","a",3,idempotency_key="k"); assert x["id"]==y["id"] and amount(inv.availability("sku","a"))==7
            check("idempotency",idem)
        if i>=3:
            def visible():
                inv=Inventory({("sku","a"):2}); r=inv.reserve("sku","a",5); inv.commit(r["id"]); assert inv.get_reservation(r["id"])["status"]=="committed" and amount(inv.availability("sku","a"))==0
            check("lifecycle visibility",visible)
        if i>=4:
            def conflict():
                inv=Inventory({("sku","a"):5,("other","a"):5}); inv.reserve("sku","a",1,idempotency_key="k")
                try: inv.reserve("other","a",1,idempotency_key="k")
                except m.IdempotencyConflict: return
                raise AssertionError("mismatched key replayed")
            check("idempotency conflict",conflict)
        if i>=5:
            def report():
                inv=Inventory({("sku","a"):3}); inv.reserve("sku","a",5); assert inv.availability("sku","a")=={"physical_on_hand":3,"active_reserved":5,"available":-2,"backordered":2}
            check("availability report",report)
        if i>=6:
            def transfer():
                inv=Inventory({("sku","a"):8,("sku","b"):2}); inv.reserve("sku","a",3); inv.transfer("sku","a","b",4)
                assert inv.availability("sku","a")["physical_on_hand"]==4 and inv.availability("sku","b")["physical_on_hand"]==6
            check("transfer",transfer)
        status,build="ok","passed"
    except Exception as exc: tests.append(False); errors.append(f"import/build: {type(exc).__name__}: {exc}"); status,build="error","failed"
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps({"status":status,"tests_passed":sum(tests),"tests_total":len(tests),"build_status":build,"errors":errors})+"\n")
if __name__=="__main__": main()
