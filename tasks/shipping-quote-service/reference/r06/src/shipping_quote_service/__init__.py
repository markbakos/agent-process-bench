import math
from decimal import Decimal, ROUND_HALF_UP

from .policy import ROUND


STANDARD={1:(500,800,1200),2:(700,1100,1600),3:(900,1400,2100)}
EXPRESS={1:(900,1400,2100),2:(1200,1800,2700),3:(1500,2300,3400)}


class ShippingQuotes:
    def __init__(self, valid_waiver_codes=()):
        self.valid_waiver_codes=set(valid_waiver_codes)

    def quote(self, weight_grams, destination_zone, *, service="standard", po_box=False, dimensions_cm=None, waiver_code=None):
        if isinstance(weight_grams,bool) or not isinstance(weight_grams,int) or weight_grams<=0 or destination_zone not in STANDARD:
            raise ValueError("invalid parcel")
        if service not in ({"standard"} if ROUND<1 else {"standard","express"}): raise ValueError("unsupported service")
        if ROUND>=2 and po_box: raise ValueError("PO boxes unsupported")
        billable=weight_grams
        if ROUND>=3 and dimensions_cm is not None:
            if not isinstance(dimensions_cm,(tuple,list)) or len(dimensions_cm)!=3 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or x<=0 for x in dimensions_cm):
                raise ValueError("invalid dimensions")
            billable=max(billable,math.ceil(math.prod(dimensions_cm)/5))
        band=0 if billable<=1000 else 1 if billable<=5000 else 2
        standard=STANDARD[destination_zone][band]
        if service=="express":
            charge=EXPRESS[destination_zone][band] if ROUND<5 else int((Decimal(standard)*Decimal("1.75")).quantize(Decimal("1"),rounding=ROUND_HALF_UP))
        else:
            waived=ROUND>=4 and ROUND<6 and waiver_code in self.valid_waiver_codes
            charge=0 if waived else standard
        return {"service":service,"charge":charge,"billable_weight_grams":billable}
