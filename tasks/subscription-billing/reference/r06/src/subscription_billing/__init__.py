import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .policy import ROUND


def _money(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _clamped(year, month, day):
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _add_month(value, anchor):
    year = value.year + (value.month == 12); month = value.month % 12 + 1
    return _clamped(year, month, anchor)


class BillingEngine:
    def __init__(self, plans):
        self.plans = {}
        for key, value in plans.items():
            spec = {"price_cents": value, "interval": "monthly"} if isinstance(value, int) else dict(value)
            if isinstance(spec.get("price_cents"), bool) or not isinstance(spec.get("price_cents"), int) or spec["price_cents"] <= 0 or spec.get("interval") not in {"monthly", "annual"}:
                raise ValueError("invalid plan")
            if ROUND < 2 and spec["interval"] != "monthly":
                raise ValueError("annual plans unavailable")
            self.plans[key] = spec
        self.subscriptions = {}; self.invoices = {}; self.credits = {}; self._next_sub = 1; self._next_invoice = 1

    def subscribe(self, customer_id, plan_id, signup_date, *, tax_rate=0):
        if plan_id not in self.plans or not isinstance(signup_date, date):
            raise ValueError("invalid subscription")
        try: rate = Decimal(str(tax_rate))
        except InvalidOperation as exc: raise ValueError("invalid tax rate") from exc
        if rate < 0 or not rate.is_finite(): raise ValueError("invalid tax rate")
        sid=f"sub-{self._next_sub}"; self._next_sub+=1
        self.subscriptions[sid]={"id":sid,"customer_id":customer_id,"plan_id":plan_id,"signup":signup_date,
                                 "anchor":signup_date.day,"tax_rate":rate,"scheduled_plan":None,"expired":False,
                                 "term_start":signup_date}
        return sid

    def _next(self, sub, after):
        plan=self.plans[sub["plan_id"]]
        if plan["interval"] == "annual":
            year=after.year+1 if (after.month,after.day)>=(sub["signup"].month,sub["signup"].day) else after.year
            candidate=_clamped(year,sub["signup"].month,sub["signup"].day)
            if candidate<=after: candidate=_clamped(year+1,sub["signup"].month,sub["signup"].day)
            return candidate
        anchor=sub["anchor"] if ROUND>=1 else after.day
        candidate=_clamped(after.year,after.month,anchor)
        if candidate<=after: candidate=_add_month(candidate,anchor)
        return candidate

    def next_boundary(self, subscription_id, after):
        return self._next(self.subscriptions[subscription_id],after)

    def _is_boundary(self, sub, value):
        if value==sub["signup"]: return True
        probe=sub["signup"]
        while probe<value:
            probe=self._next(sub,probe)
        return probe==value

    def generate_invoice(self, subscription_id, period_start):
        sub=self.subscriptions[subscription_id]; key=(subscription_id,period_start)
        if key in self.invoices: return dict(self.invoices[key])
        if not self._is_boundary(sub,period_start): raise ValueError("not a boundary")
        plan=self.plans[sub["plan_id"]]
        if ROUND>=5 and plan["interval"]=="annual" and period_start>sub["term_start"]:
            sub["expired"]=True; raise ValueError("annual subscription expired")
        if ROUND>=3 and sub["scheduled_plan"] and period_start>sub["signup"]:
            sub["plan_id"]=sub["scheduled_plan"]; sub["scheduled_plan"]=None; plan=self.plans[sub["plan_id"]]
        subtotal=plan["price_cents"]; customer=sub["customer_id"]
        available=self.credits.get(customer,0) if ROUND>=4 else 0; credits=min(subtotal,available)
        if ROUND>=4: self.credits[customer]=available-credits
        taxable=subtotal-credits; tax=_money(Decimal(taxable)*sub["tax_rate"]/100) if ROUND>=6 else 0
        invoice={"id":f"inv-{self._next_invoice}","subscription_id":subscription_id,"period_start":period_start,
                 "subtotal":subtotal,"credits":credits,"tax":tax,"amount_due":taxable+tax}
        self._next_invoice+=1; self.invoices[key]=invoice
        return dict(invoice)

    def upgrade(self, subscription_id, new_plan_id, effective_date):
        if new_plan_id not in self.plans: raise ValueError("unknown plan")
        sub=self.subscriptions[subscription_id]
        if ROUND>=3:
            sub["scheduled_plan"]=new_plan_id; return None
        old=self.plans[sub["plan_id"]]["price_cents"]; new=self.plans[new_plan_id]["price_cents"]
        start=sub["signup"]
        while self._next(sub,start)<=effective_date: start=self._next(sub,start)
        end=self._next(sub,start); days=(end-start).days; remaining=(end-effective_date).days
        difference=_money(Decimal(new-old)*remaining/days); sub["plan_id"]=new_plan_id
        invoice={"id":f"inv-{self._next_invoice}","subscription_id":subscription_id,"period_start":effective_date,
                 "subtotal":max(0,difference),"credits":max(0,-difference),"tax":0,"amount_due":max(0,difference)}
        self._next_invoice+=1; return invoice

    def credit_customer(self, customer_id, cents):
        if ROUND<4 or isinstance(cents,bool) or not isinstance(cents,int) or cents<=0: raise ValueError("invalid credit")
        self.credits[customer_id]=self.credits.get(customer_id,0)+cents

    def customer_credit(self, customer_id):
        return self.credits.get(customer_id,0)

    def renew(self, subscription_id):
        sub=self.subscriptions[subscription_id]; plan=self.plans[sub["plan_id"]]
        if ROUND<5 or plan["interval"]!="annual": raise ValueError("cannot renew")
        boundary=self._next(sub,sub["term_start"])
        if not sub["expired"]:
            sub["expired"]=True
        sub["expired"]=False; sub["term_start"]=boundary
        return self.generate_invoice(subscription_id,boundary)
