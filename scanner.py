from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Iterable, List, Dict
import math

@dataclass
class StockSnapshot:
    code: str
    name: str
    price: float
    open: float
    high: float
    low: float
    prev_close: float
    volume: float
    avg_volume_20: float
    turnover_krw: float
    market_cap_krw: float
    ma5_5m: float
    ma20_5m: float
    recent_high_5m: float
    recent_high_20m: float
    pullback_low_5m: float
    bid_strength: float = 100.0
    is_management: bool = False
    is_halted: bool = False
    is_preferred: bool = False
    is_spac: bool = False

    @property
    def change_pct(self) -> float:
        if self.prev_close <= 0:
            return 0.0
        return (self.price / self.prev_close - 1.0) * 100.0

    @property
    def volume_ratio(self) -> float:
        if self.avg_volume_20 <= 0:
            return 0.0
        return self.volume / self.avg_volume_20 * 100.0

    @property
    def high_gap_pct(self) -> float:
        if self.high <= 0:
            return -999.0
        return (self.price / self.high - 1.0) * 100.0

    @property
    def body_position(self) -> float:
        span = max(self.high - self.low, 1e-9)
        return (self.price - self.low) / span

def base_filter(s: StockSnapshot) -> bool:
    """공통 필터: 초저가/초소형/관리/정지/우선주/스팩 제외."""
    if s.price < 1500:
        return False
    if s.market_cap_krw < 50_000_000_000:   # 500억원
        return False
    if s.turnover_krw < 5_000_000_000:      # 50억원
        return False
    if s.is_management or s.is_halted or s.is_preferred or s.is_spac:
        return False
    return True

def clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))

def breakout_score(s: StockSnapshot) -> float:
    """돌파형: 거래대금 + 거래량 + 최근고점 접근/돌파 + 단기추세."""
    turnover = clamp(math.log10(max(s.turnover_krw / 1e8, 1)) * 12, 0, 30)
    vol = clamp((s.volume_ratio - 100) / 10, 0, 25)
    near_high = clamp((3.0 + s.high_gap_pct) / 3.0 * 15, 0, 15)
    trend = 15 if s.price > s.ma5_5m > s.ma20_5m else (8 if s.price > s.ma20_5m else 0)
    breakout = 15 if s.price >= s.recent_high_20m else (10 if s.price >= s.recent_high_5m * 0.995 else 0)
    return round(turnover + vol + near_high + trend + breakout, 1)

def pullback_score(s: StockSnapshot) -> float:
    """눌림목형: 상승추세 유지 + 고점 대비 적당한 눌림 + 재반등 위치."""
    turnover = clamp(math.log10(max(s.turnover_krw / 1e8, 1)) * 10, 0, 25)
    vol = clamp((s.volume_ratio - 100) / 12, 0, 20)
    trend = 25 if s.ma5_5m > s.ma20_5m and s.price > s.ma20_5m else 0
    pullback_pct = (s.price / max(s.high, 1e-9) - 1) * 100
    # 고점 대비 -1% ~ -4% 부근을 선호
    if -4.0 <= pullback_pct <= -1.0:
        pullback = 20
    elif -6.0 <= pullback_pct < -4.0 or -1.0 < pullback_pct <= 0:
        pullback = 10
    else:
        pullback = 0
    rebound = 10 if s.price > s.pullback_low_5m * 1.005 else 0
    return round(turnover + vol + trend + pullback + rebound, 1)

def volume_explosion_score(s: StockSnapshot) -> float:
    """거래량폭발형: 거래량 증가율을 가장 크게 반영."""
    vol = clamp((s.volume_ratio - 100) / 8, 0, 40)
    turnover = clamp(math.log10(max(s.turnover_krw / 1e8, 1)) * 10, 0, 25)
    momentum = clamp((s.change_pct - 1.0) * 3, 0, 15)
    strength = clamp((s.bid_strength - 100) / 5, 0, 10)
    candle = clamp(s.body_position * 10, 0, 10)
    return round(vol + turnover + momentum + strength + candle, 1)

def scan_breakout(stocks: Iterable[StockSnapshot]) -> List[Dict]:
    out = []
    for s in stocks:
        if not base_filter(s):
            continue
        if not (2.0 <= s.change_pct <= 15.0):
            continue
        if s.volume_ratio < 180:
            continue
        if s.high_gap_pct < -2.0:
            continue
        if not (s.price > s.ma20_5m):
            continue
        if s.price < s.recent_high_5m * 0.99:
            continue
        out.append(result_row(s, "돌파형", breakout_score(s)))
    return sorted(out, key=lambda x: x["score"], reverse=True)

def scan_pullback(stocks: Iterable[StockSnapshot]) -> List[Dict]:
    out = []
    for s in stocks:
        if not base_filter(s):
            continue
        if not (1.5 <= s.change_pct <= 12.0):
            continue
        if s.volume_ratio < 150:
            continue
        if not (s.ma5_5m > s.ma20_5m and s.price > s.ma20_5m):
            continue
        if not (-6.0 <= s.high_gap_pct <= -0.5):
            continue
        if s.price <= s.pullback_low_5m:
            continue
        out.append(result_row(s, "눌림목형", pullback_score(s)))
    return sorted(out, key=lambda x: x["score"], reverse=True)

def scan_volume_explosion(stocks: Iterable[StockSnapshot]) -> List[Dict]:
    out = []
    for s in stocks:
        if not base_filter(s):
            continue
        if not (1.0 <= s.change_pct <= 18.0):
            continue
        if s.volume_ratio < 250:
            continue
        if s.turnover_krw < 8_000_000_000:  # 이 검색기는 80억 이상
            continue
        if s.body_position < 0.55:
            continue
        out.append(result_row(s, "거래량폭발형", volume_explosion_score(s)))
    return sorted(out, key=lambda x: x["score"], reverse=True)

def result_row(s: StockSnapshot, scanner: str, score: float) -> Dict:
    return {
        "scanner": scanner,
        "code": s.code,
        "name": s.name,
        "price": int(s.price),
        "change_pct": round(s.change_pct, 2),
        "turnover_eok": round(s.turnover_krw / 1e8, 1),
        "volume_ratio": round(s.volume_ratio, 1),
        "high_gap_pct": round(s.high_gap_pct, 2),
        "bid_strength": round(s.bid_strength, 1),
        "score": score,
    }
