import argparse
import json
import sys
sys.dont_write_bytecode = True
from pathlib import Path


def main():
    p=argparse.ArgumentParser(); p.add_argument("--workspace",type=Path,required=True); p.add_argument("--round",required=True); p.add_argument("--output",type=Path,required=True); a=p.parse_args(); tests=[]; errors=[]
    def check(name,fn):
        try: fn(); tests.append(True)
        except Exception as exc: tests.append(False); errors.append(f"{name}: {type(exc).__name__}: {exc}")
    try:
        sys.path.insert(0,str(a.workspace/"src")); from shipping_quote_service import ShippingQuotes; i=int(a.round[1:])
        def base():
            q=ShippingQuotes(); assert q.quote(1000,1)["charge"]==500 and q.quote(1001,2)["charge"]==1100
            for args in ((0,1),(1,9)):
                try: q.quote(*args)
                except ValueError: pass
                else: raise AssertionError(args)
            if i<2: assert q.quote(500,1,po_box=True)["charge"]==500
            else:
                try: q.quote(500,1,po_box=True)
                except ValueError: pass
                else: raise AssertionError("PO box accepted")
        check("standard and PO box policy",base)
        if i>=1:
            def express():
                charge=ShippingQuotes().quote(1000,1,service="express")["charge"]; assert charge==(900 if i<5 else 875)
            check("express pricing",express)
        if i>=3:
            def dimensional():
                result=ShippingQuotes().quote(500,1,dimensions_cm=(50,40,30)); assert result["billable_weight_grams"]==12000 and result["charge"]==1200
                assert ShippingQuotes().quote(900,1,dimensions_cm=(10,10,10))["charge"]==500
            check("dimensional weight",dimensional)
        if i>=4:
            def waiver():
                q=ShippingQuotes(valid_waiver_codes={"FREE"}); expected=0 if i<6 else 500
                assert q.quote(500,1,waiver_code="FREE")["charge"]==expected
                assert q.quote(500,1,service="express",waiver_code="FREE")["charge"]==(900 if i<5 else 875)
            check("waiver policy",waiver)
        status,build="ok","passed"
    except Exception as exc: tests.append(False); errors.append(f"import/build: {type(exc).__name__}: {exc}"); status,build="error","failed"
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps({"status":status,"tests_passed":sum(tests),"tests_total":len(tests),"build_status":build,"errors":errors})+"\n")
if __name__=="__main__": main()
