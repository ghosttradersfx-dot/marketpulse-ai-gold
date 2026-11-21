"""Gold-only market research API. No orders or brokerage connections."""
import os, json, time, math, urllib.parse, urllib.request
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title='MarketPulse AI — Gold Research')
app.mount('/static', StaticFiles(directory=os.path.join(os.path.dirname(__file__), 'static')), name='static')
CACHE = {}
INTERVALS = {'5min','15min','1h','1day'}

def fetch_xaus(interval):
    # XAUS publishes reference prices, not broker-executable quotes.
    mapping = {'5min': ('5m','5d'), '15min': ('15m','5d'), '1h': ('1h','1mo'), '1day': ('1d','6mo')}
    candle_interval, candle_range = mapping[interval]
    url = 'https://xaus.com/api/v1/chart?' + urllib.parse.urlencode({'symbol':'xau','interval':candle_interval,'range':candle_range})
    try:
        req=urllib.request.Request(url, headers={'User-Agent':'MarketPulseGoldResearch/2.0','Accept':'application/json'})
        with urllib.request.urlopen(req, timeout=18) as response: result=json.load(response)
    except Exception as exc:
        raise HTTPException(502, 'XAUS chart feed could not be reached.') from exc
    if not isinstance(result,dict) or not isinstance(result.get('points'),list):
        raise HTTPException(502,'XAUS did not return usable chart points.')
    if result.get('data_state',{}).get('status')=='unavailable':
        raise HTTPException(503,'XAUS reports market data unavailable.')
    return result

def parse_timestamp(t):
    if isinstance(t,(int,float)):
        return datetime.fromtimestamp(t/1000 if t>1e11 else t,timezone.utc).isoformat()
    if isinstance(t,str):
        try:
            return datetime.fromtimestamp(float(t)/1000 if float(t)>1e11 else float(t),timezone.utc).isoformat()
        except ValueError:
            return t
    return None

def is_stale(raw, interval, candle_time):
    if raw.get('data_state',{}).get('status')=='stale':return True
    # Provider metadata can be cached: independently validate update timestamp.
    updated=raw.get('updated_at')
    if updated:
        try:
            dt=datetime.fromisoformat(updated.replace('Z','+00:00'))
            if (datetime.now(timezone.utc)-dt).total_seconds()>900:return True
        except (ValueError,TypeError):return True
    if candle_time:
        try:
            dt=datetime.fromisoformat(candle_time.replace('Z','+00:00'))
            age=(datetime.now(timezone.utc)-dt).total_seconds()
            # Weekend closures and holidays are possible; flag rather than pretending live.
            if age > {'5min':1800,'15min':3600,'1h':10800,'1day':259200}[interval]:return True
        except (ValueError,TypeError):return True
    return False

def ema(values, period):
    if len(values)<period: return None
    v=sum(values[:period])/period
    for x in values[period:]: v=x*(2/(period+1))+v*(1-2/(period+1))
    return v

def rsi(values, period=14):
    if len(values)<period+1:return None
    changes=[values[i]-values[i-1] for i in range(1,len(values))]
    gain=sum(max(x,0) for x in changes[:period])/period
    loss=sum(max(-x,0) for x in changes[:period])/period
    for x in changes[period:]:
        gain=(gain*(period-1)+max(x,0))/period
        loss=(loss*(period-1)+max(-x,0))/period
    if loss==0:return 100.0 if gain>0 else 50.0
    return 100-100/(1+gain/loss)

def atr(candles, period=14):
    if len(candles)<period+1:return None
    tr=[]
    for i in range(1,len(candles)):
        c,p=candles[i],candles[i-1]
        tr.append(max(c['high']-c['low'],abs(c['high']-p['close']),abs(c['low']-p['close'])))
    a=sum(tr[:period])/period
    for x in tr[period:]:a=(a*(period-1)+x)/period
    return a

def macd(values):
    if len(values)<35:return None
    line=[]
    for i in range(26,len(values)+1):
        fast=ema(values[:i],12); slow=ema(values[:i],26)
        line.append(fast-slow)
    signal=ema(line,9)
    return {'line':line[-1],'signal':signal,'histogram':line[-1]-signal}

def rnd(v):return round(v,4) if v is not None else None

@app.get('/')
def home():return FileResponse(os.path.join(os.path.dirname(__file__),'static','index.html'))

@app.get('/api/analysis')
def analysis(interval: str='15min'):
    if interval not in INTERVALS:raise HTTPException(400,'Unsupported interval')
    now=time.time()
    if interval in CACHE and now-CACHE[interval][0]<60:return CACHE[interval][1]
    raw=fetch_xaus(interval)
    candles=[]
    for c in raw['points']:
        try:
            row={'time':parse_timestamp(c['t']),'open':float(c['o']),'high':float(c['h']),'low':float(c['l']),'close':float(c['c'])}
            if row['time'] and all(math.isfinite(v) and v>0 for v in list(row.values())[1:]) and row['low']<=min(row['open'],row['close'])<=row['high'] and row['low']<=max(row['open'],row['close'])<=row['high']:
                candles.append(row)
        except (ValueError,KeyError,TypeError,OverflowError):continue
    candles.sort(key=lambda x:x['time'])
    candles=list({c['time']:c for c in candles}.values())
    if len(candles)<60:raise HTTPException(502,'Insufficient valid candles from provider')
    close=[c['close'] for c in candles]
    e20,e50=ema(close,20),ema(close,50)
    r=rsi(close); m=macd(close); a=atr(candles)
    price=close[-1]
    stale=is_stale(raw,interval,candles[-1]['time'])
    bullish=price>e20>e50 and m['histogram']>0 and r>50
    bearish=price<e20<e50 and m['histogram']<0 and r<50
    trend='Bullish' if bullish else 'Bearish' if bearish else 'Mixed / neutral'
    # Deliberately use completed historical candle values, not chart widget values.
    # Candle timestamps may represent the start of a candle and the latest candle may be forming.
    support=min(c['low'] for c in candles[-20:]); resistance=max(c['high'] for c in candles[-20:])
    reasons=[f'Close {"above" if price>e20 else "below"} EMA20 and {"above" if price>e50 else "below"} EMA50',f'RSI(14) {r:.1f}',f'MACD histogram {m["histogram"]:+.4f}']
    scenario=None
    if not stale and a and a>0 and (bullish or bearish):
        direction='Long' if bullish else 'Short'
        stop=price-1.5*a if bullish else price+1.5*a
        target=price+3*a if bullish else price-3*a
        scenario={'direction':direction,'entry':rnd(price),'stop_loss':rnd(stop),'take_profit':rnd(target),'risk_reward':'1:2','basis':'Illustrative 1.5×ATR stop and 3×ATR target; not an execution signal'}
    result={'symbol':'XAU/USD','interval':interval,'source':'XAUS /api/v1/chart (indicative reference data)','provider_symbol':'xau','as_of_candle':candles[-1]['time'],'retrieved_at':datetime.now(timezone.utc).isoformat(),'provider_updated_at':raw.get('updated_at'),'data_state':raw.get('data_state',{}),'stale':stale,'price':rnd(price),'trend':trend,'reasons':reasons,'indicators':{'ema20':rnd(e20),'ema50':rnd(e50),'rsi14':rnd(r),'atr14':rnd(a),'macd':{k:rnd(v) for k,v in m.items()}},'support20':rnd(support),'resistance20':rnd(resistance),'scenario':scenario,'candles_count':len(candles),'notice':'Indicative XAUS chart candles, not executable quotes. The latest candle may be incomplete; chart data may be delayed. Stale data disables hypothetical scenarios. Educational use only.'}
    CACHE[interval]=(now,result)
    return result
