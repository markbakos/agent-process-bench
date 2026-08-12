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
        sys.path.insert(0,str(a.workspace/"src")); from subscription_billing import BillingEngine; i=int(a.round[1:])
        def plans(): return {"basic":1000,"pro":2000}
        def base():
            e=BillingEngine(plans()); s=e.subscribe("c","basic",date(2026,1,15)); assert e.next_boundary(s,date(2026,1,15))==date(2026,2,15)
            x=e.generate_invoice(s,date(2026,1,15)); y=e.generate_invoice(s,date(2026,1,15)); assert x["id"]==y["id"] and x["amount_due"]==1000
            if i<3: assert e.upgrade(s,"pro",date(2026,1,31))["amount_due"]==484
            else: assert e.upgrade(s,"pro",date(2026,1,31)) is None
        check("billing and upgrade policy",base)
        def anchor():
            e=BillingEngine(plans()); s=e.subscribe("c","basic",date(2024,1,31)); feb=e.next_boundary(s,date(2024,1,31)); mar=e.next_boundary(s,feb)
            assert feb==date(2024,2,29)
            assert mar==(date(2024,3,31) if i>=1 else date(2024,3,29))
        check("monthly anchor",anchor)
        if i>=2:
            def annual():
                e=BillingEngine({"annual":{"price_cents":12000,"interval":"annual"}}); s=e.subscribe("c","annual",date(2024,2,29)); assert e.next_boundary(s,date(2024,2,29))==date(2025,2,28)
            check("annual anchor",annual)
        if i>=3:
            def scheduled():
                e=BillingEngine(plans()); s=e.subscribe("c","basic",date(2026,1,1)); e.upgrade(s,"pro",date(2026,1,10)); inv=e.generate_invoice(s,date(2026,2,1)); assert inv["subtotal"]==2000
            check("scheduled upgrade",scheduled)
        if i>=4:
            def credits():
                e=BillingEngine(plans()); s=e.subscribe("c","basic",date(2026,1,1)); e.credit_customer("c",1500); inv=e.generate_invoice(s,date(2026,1,1)); assert inv["credits"]==1000 and inv["amount_due"]==0 and e.customer_credit("c")==500
            check("credit balance",credits)
        if i>=5:
            def fixed_term():
                e=BillingEngine({"annual":{"price_cents":12000,"interval":"annual"}}); s=e.subscribe("c","annual",date(2026,1,1)); e.generate_invoice(s,date(2026,1,1))
                try: e.generate_invoice(s,date(2027,1,1))
                except ValueError: pass
                else: raise AssertionError("annual auto-renewed")
                assert e.renew(s)["period_start"]==date(2027,1,1)
            check("fixed annual term",fixed_term)
        if i>=6:
            def tax():
                e=BillingEngine(plans()); s=e.subscribe("c","basic",date(2026,1,1),tax_rate="7.5"); e.credit_customer("c",100); inv=e.generate_invoice(s,date(2026,1,1)); assert (inv["subtotal"],inv["credits"],inv["tax"],inv["amount_due"])==(1000,100,68,968)
            check("tax",tax)
        status,build="ok","passed"
    except Exception as exc: tests.append(False); errors.append(f"import/build: {type(exc).__name__}: {exc}"); status,build="error","failed"
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps({"status":status,"tests_passed":sum(tests),"tests_total":len(tests),"build_status":build,"errors":errors},default=str)+"\n")
if __name__=="__main__": main()
