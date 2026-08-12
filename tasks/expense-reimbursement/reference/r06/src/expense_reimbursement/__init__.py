from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .policy import ROUND


def _round(value): return int(value.quantize(Decimal("1"),rounding=ROUND_HALF_UP))


class ExpenseEngine:
    def __init__(self,receipt_thresholds=None,small_claim_threshold_cents=0,base_currency="USD"):
        self.thresholds=receipt_thresholds or {}; self.small=small_claim_threshold_cents; self.base=base_currency
        self.claims={}; self._next=1

    def _converted(self,items,rates):
        converted=[None]*len(items); groups={}
        for index,item in enumerate(items):
            currency=item.get("currency",self.base)
            if currency==self.base: converted[index]=item["amount_cents"]
            else:
                if currency not in rates: raise ValueError("missing exchange rate")
                try: rate=Decimal(str(rates[currency]))
                except InvalidOperation as exc: raise ValueError("invalid rate") from exc
                if rate<=0: raise ValueError("invalid rate")
                groups.setdefault((currency,rate),[]).append(index)
        for (_,rate),indexes in groups.items():
            if ROUND<6:
                for index in indexes: converted[index]=_round(Decimal(items[index]["amount_cents"])*rate)
            else:
                exact=[Decimal(items[index]["amount_cents"])*rate for index in indexes]
                target=_round(sum(exact)); floors=[int(value) for value in exact]; remaining=target-sum(floors)
                for offset,index in enumerate(indexes): converted[index]=floors[offset]+(1 if offset<remaining else 0)
        return converted

    def submit(self,employee,items,*,exchange_rates=None):
        if not items: raise ValueError("items required")
        normalized=[]
        for item in items:
            amount=item.get("amount_cents")
            if isinstance(amount,bool) or not isinstance(amount,int) or amount<=0: raise ValueError("invalid amount")
            threshold=2500 if ROUND==0 else self.thresholds.get(item.get("category"))
            if threshold is None: raise ValueError("unknown category")
            if amount>threshold and not item.get("receipt",False): raise ValueError("receipt required")
            normalized.append(dict(item))
        amounts=self._converted(normalized,exchange_rates or {}) if ROUND>=3 else [x["amount_cents"] for x in normalized]
        for item,amount in zip(normalized,amounts): item["base_amount_cents"]=amount
        total=sum(amounts); months={(x["date"].year,x["date"].month) for x in normalized}
        projected=max((self._approved_month(employee,m)+sum(v for x,v in zip(normalized,amounts) if (x["date"].year,x["date"].month)==m) for m in months),default=total)
        if ROUND<4 and projected>100000: raise ValueError("monthly cap")
        needs_finance=ROUND>=4 and projected>100000
        status="approved" if ROUND>=2 and total<=self.small and not needs_finance else "pending_finance" if ROUND>=4 and total<=self.small and needs_finance else "pending_manager"
        cid=f"claim-{self._next}"; self._next+=1
        duplicates=[]
        if ROUND>=5:
            for index,item in enumerate(normalized):
                for old in self.claims.values():
                    if old["employee"]==employee and any(x["merchant"]==item["merchant"] and x["date"]==item["date"] and x["base_amount_cents"]==item["base_amount_cents"] for x in old["items"]):
                        duplicates.append({"item_index":index,"claim_id":old["id"]}); break
        claim={"id":cid,"employee":employee,"items":normalized,"total_cents":total,"status":status,"needs_finance":needs_finance,"duplicates":duplicates}
        self.claims[cid]=claim; return self._public(claim)

    def _approved_month(self,employee,month):
        return sum(item["base_amount_cents"] for claim in self.claims.values() if claim["employee"]==employee and claim["status"]=="approved" for item in claim["items"] if (item["date"].year,item["date"].month)==month)

    def _public(self,claim): return {k:v for k,v in claim.items() if k!="needs_finance"}
    def get(self,claim_id):
        if claim_id not in self.claims: raise KeyError(claim_id)
        return self._public(self.claims[claim_id])
    def approve_manager(self,claim_id):
        claim=self.claims[claim_id]
        if claim["status"]!="pending_manager": raise ValueError("invalid transition")
        claim["status"]="pending_finance" if ROUND>=4 and claim["needs_finance"] else "approved"; return self._public(claim)
    def approve_finance(self,claim_id):
        if ROUND<4: raise ValueError("finance unavailable")
        claim=self.claims[claim_id]
        if claim["status"]!="pending_finance": raise ValueError("invalid transition")
        claim["status"]="approved"; return self._public(claim)
