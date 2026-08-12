from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from .policy import ROUND


def _add_business(start, minutes):
    current=start
    while current.weekday()>=5 or current.time()<time(9) or current.time()>=time(17):
        if current.weekday()<5 and current.time()<time(9): current=current.replace(hour=9,minute=0,second=0,microsecond=0)
        else:
            current=(current+timedelta(days=1)).replace(hour=9,minute=0,second=0,microsecond=0)
    remaining=minutes
    while remaining:
        available=int((current.replace(hour=17,minute=0,second=0,microsecond=0)-current).total_seconds()//60)
        used=min(available,remaining); current+=timedelta(minutes=used); remaining-=used
        if remaining:
            current=(current+timedelta(days=1)).replace(hour=9,minute=0,second=0,microsecond=0)
            while current.weekday()>=5: current+=timedelta(days=1)
    return current


def _business_elapsed(start,end):
    if end<=start: return 0
    minutes=0; cursor=start
    while cursor<end:
        next_minute=cursor+timedelta(minutes=1)
        if cursor.weekday()<5 and time(9)<=cursor.time()<time(17): minutes+=1
        cursor=next_minute
    return minutes


class SLARouter:
    def __init__(self, category_queues, priority_sla_minutes, vip_sla_minutes=None, priority_queues=None,
                 vip_reduction_percent=0, minimum_sla_minutes=1):
        self.category_queues=category_queues; self.slas=priority_sla_minutes; self.vip_slas=vip_sla_minutes or {}
        self.priority_queues=priority_queues or {}; self.vip_reduction=vip_reduction_percent; self.minimum=minimum_sla_minutes; self._next=1
        if ROUND>=5 and (not 0<=vip_reduction_percent<=100 or minimum_sla_minutes<=0): raise ValueError("invalid VIP policy")

    def create_ticket(self, category, priority, created_at, vip=False):
        if priority not in self.slas or self.slas[priority]<=0: raise ValueError("unknown priority")
        if ROUND>=3:
            if priority not in self.priority_queues: raise ValueError("missing priority queue")
            queue=self.priority_queues[priority]
        else: queue=self.category_queues.get(category,"general")
        minutes=self.slas[priority]
        if vip and ROUND >= 1:
            if ROUND<5: minutes=self.vip_slas.get(priority,minutes)
            else: minutes=max(self.minimum,int((Decimal(minutes)*(100-self.vip_reduction)/100).quantize(Decimal("1"),rounding=ROUND_HALF_UP)))
        deadline=created_at+timedelta(minutes=minutes) if ROUND<2 else _add_business(created_at,minutes)
        item={"id":f"ticket-{self._next}","category":category,"priority":priority,"created_at":created_at,
              "vip":vip,"queue":queue,"sla_minutes":minutes,"deadline":deadline}; self._next+=1; return item

    def is_escalation_eligible(self,ticket,now):
        if ROUND<4: raise AttributeError("escalation unavailable")
        if ROUND>=6: return now>ticket["deadline"]
        return _business_elapsed(ticket["created_at"],now)*100>=ticket["sla_minutes"]*80
