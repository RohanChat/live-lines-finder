from __future__ import annotations
from typing import Optional, List, Dict
from datetime import datetime
from pydantic import Field, field_serializer, model_validator
from .models import SportKey, MarketType, Period, Market, Region, Base, _iso_utc_z


class FeedQuery(Base):
    sports: Optional[List[SportKey]] = None
    event_ids: Optional[List[str]] = None
    start_time_from: Optional[datetime] = None
    start_time_to: Optional[datetime] = None
    markets: Optional[List[MarketType]] = None
    periods: Optional[List[Period]] = None
    bookmakers: Optional[List[str]] = None
    players: Optional[List[str]] = None
    teams: Optional[List[str]] = None
    regions: Optional[List[Region]] = None
    limit: Optional[int] = None
    extra: Dict = Field(default_factory=dict)

    @field_serializer("start_time_from")
    def serialize_start_time_from(self, dt: Optional[datetime], _info):
        return _iso_utc_z(dt)
    
    @field_serializer("start_time_to")
    def serialize_start_time_to(self, dt: Optional[datetime], _info):
        return _iso_utc_z(dt)
    
    @model_validator(mode="before")
    @classmethod
    def _coerce_enums(cls, data):
        if not isinstance(data, dict):
            return data
        def coerce_list(xs, EnumCls):
            if xs is None: return None
            out = []
            for x in xs:
                if isinstance(x, EnumCls):
                    out.append(x)
                else:
                    # allow exact value and name lookups
                    try:
                        out.append(EnumCls(x))
                    except Exception:
                        try:
                            out.append(EnumCls[str(x)])
                        except Exception:
                            raise TypeError(f"Cannot coerce {x!r} to {EnumCls.__name__}")
            return out

        d = dict(data)
        d["sports"]  = coerce_list(d.get("sports"),  SportKey)
        d["markets"] = coerce_list(d.get("markets"), MarketType)
        d["periods"] = coerce_list(d.get("periods"), Period)
        d["regions"] = coerce_list(d.get("regions"), Region)
        return d
