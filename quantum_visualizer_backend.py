# quantum_visualizer_backend.py
# Production-grade FastAPI backend with WebSocket support, async database operations,
# and real-time audio processing capabilities.

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Union, Any
from dataclasses import dataclass, field, asdict

import asyncpg
import numpy as np
import uvloop
from fastapi import (
    FastAPI, 
    WebSocket, 
    WebSocketDisconnect, 
    HTTPException, 
    UploadFile, 
    File, 
    BackgroundTasks,
    Depends,
    status
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, validator
from redis import asyncio as aioredis
import aiofiles
import librosa
import soundfile as sf
from scipy import signal
from scipy.fft import rfft, rfftfreq

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

app = FastAPI(
    title="Quantum Harmonic Visualizer API",
    version="2.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://quantum-harmonic.vercel.app"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Processing-Time", "X-Request-ID"]
)

redis_pool: Optional[aioredis.Redis] = None
db_pool: Optional[asyncpg.Pool] = None


class HashTableService:
    """
    High-performance hash table implementation with open addressing 
    and Robin Hood hashing for optimal cache locality.
    """
    
    __slots__ = ('_table', '_size', '_capacity', '_load_factor_threshold', '_tombstone')
    
    def __init__(self, initial_capacity: int = 16, load_factor: float = 0.75):
        self._table: List[Optional[tuple]] = [None] * initial_capacity
        self._size: int = 0
        self._capacity: int = initial_capacity
        self._load_factor_threshold: float = load_factor
        self._tombstone = object()
    
    def _hash_key(self, key: Any) -> int:
        if isinstance(key, str):
            hash_val = hashlib.siphash24(key.encode('utf-8')).digest()
            return int.from_bytes(hash_val[:8], 'little')
        elif isinstance(key, (int, float)):
            hash_bytes = hashlib.siphash24(str(key).encode('utf-8')).digest()
            return int.from_bytes(hash_bytes[:8], 'little')
        else:
            return hash(key)
    
    def _find_slot(self, key: Any, for_insert: bool = False) -> int:
        idx = self._hash_key(key) % self._capacity
        first_tombstone = -1
        distance = 0
        
        while distance < self._capacity:
            slot = self._table[idx]
            
            if slot is None:
                return first_tombstone if first_tombstone != -1 and for_insert else idx
            
            if slot is self._tombstone:
                if first_tombstone == -1:
                    first_tombstone = idx
                idx = (idx + 1) % self._capacity
                distance += 1
                continue
            
            existing_key, _ = slot
            if existing_key == key:
                return idx
            
            existing_distance = (idx - self._hash_key(existing_key) % self._capacity) % self._capacity
            if existing_distance < distance and for_insert:
                return idx
            
            idx = (idx + 1) % self._capacity
            distance += 1
        
        raise RuntimeError("Hash table full")
    
    def _resize(self) -> None:
        old_table = self._table
        self._capacity *= 2
        self._table = [None] * self._capacity
        self._size = 0
        
        for slot in old_table:
            if slot is not None and slot is not self._tombstone:
                key, value = slot
                self.insert(key, value)
    
    def insert(self, key: Any, value: Any) -> None:
        if self._size / self._capacity > self._load_factor_threshold:
            self._resize()
        
        idx = self._find_slot(key, for_insert=True)
        
        if self._table[idx] is None or self._table[idx] is self._tombstone:
            self._size += 1
        
        self._table[idx] = (key, value)
    
    def get(self, key: Any, default: Any = None) -> Any:
        idx = self._find_slot(key)
        slot = self._table[idx]
        
        if slot is not None and slot is not self._tombstone:
            _, value = slot
            return value
        
        return default
    
    def arr_to_obj(self, keys: List[Any], values: List[Any]) -> Dict[str, Any]:
        """Convert two arrays into a hash object, linking keys to values."""
        self._table = [None] * self._capacity
        self._size = 0
        
        result = {}
        
        for i, key in enumerate(keys):
            str_key = str(key)
            
            if i < len(values):
                value = values[i]
                self.insert(str_key, value)
                result[str_key] = value
            else:
                self.insert(str_key, None)
                result[str_key] = None
        
        return result
    
    def __len__(self) -> int:
        return self._size


@dataclass
class AudioPreset:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    particle_count: int = 1000
    color_scheme: str = "aurora"
    frequency_bands: Dict[str, List[int]] = field(default_factory=lambda: {
        "sub_bass": [20, 60],
        "bass": [60, 250],
        "low_mid": [250, 500],
        "mid": [500, 2000],
        "high_mid": [2000, 4000],
        "presence": [4000, 6000],
        "brilliance": [6000, 20000]
    })
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class FrequencySnapshot:
    timestamp: float
    frequencies: List[float]
    peak_frequency: float
    rms_energy: float
    spectral_centroid: float
    zero_crossing_rate: float


class AudioAnalyzer:
    """Real-time audio analysis using spectral processing techniques."""
    
    def __init__(self, sample_rate: int = 44100, fft_size: int = 2048):
        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.hop_length = fft_size // 4
    
    def analyze_file(self, file_path: str) -> Dict[str, Any]:
        y, sr = librosa.load(file_path, sr=self.sample_rate, mono=True)
        
        duration = len(y) / sr
        
        spectral_centroids = librosa.feature.spectral_centroid(
            y=y, sr=sr, n_fft=self.fft_size, hop_length=self.hop_length
        )[0]
        
        rms = librosa.feature.rms(y=y, hop_length=self.hop_length)[0]
        
        zcr = librosa.feature.zero_crossing_rate(y, hop_length=self.hop_length)[0]
        
        mel_spec = librosa.feature.melspectrogram(
            y=y, sr=sr, n_fft=self.fft_size, hop_length=self.hop_length
        )
        
        chroma = librosa.feature.chroma_stft(
            y=y, sr=sr, hop_length=self.hop_length
        )
        
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        times = librosa.times_like(onset_env, sr=sr, hop_length=512)
        
        snapshots = []
        for i in range(0, len(y), self.hop_length):
            chunk = y[i:i + self.fft_size]
            if len(chunk) < self.fft_size:
                break
            
            fft_result = np.abs(rfft(chunk))
            freqs = rfftfreq(self.fft_size, 1 / sr)
            
            peak_idx = np.argmax(fft_result)
            peak_freq = freqs[peak_idx] if peak_idx < len(freqs) else 0
            
            chunk_rms = np.sqrt(np.mean(chunk ** 2))
            
            spectral_centroid = np.sum(freqs * fft_result) / np.sum(fft_result) if np.sum(fft_result) > 0 else 0
            
            zero_crossings = np.sum(np.abs(np.diff(np.sign(chunk)))) / (2 * len(chunk))
            
            snapshots.append(FrequencySnapshot(
                timestamp=i / sr,
                frequencies=fft_result[:32].tolist(),
                peak_frequency=float(peak_freq),
                rms_energy=float(chunk_rms),
                spectral_centroid=float(spectral_centroid),
                zero_crossing_rate=float(zero_crossings)
            ))
        
        return {
            "duration": duration,
            "sample_rate": sr,
            "tempo": float(tempo),
            "beat_times": librosa.frames_to_time(beat_frames, sr=sr).tolist(),
            "snapshots": [asdict(s) for s in snapshots[::10]],
            "spectral_centroids": spectral_centroids.tolist(),
            "rms_energy": rms.tolist(),
            "zero_crossing_rate": zcr.tolist()
        }


@app.on_event("startup")
async def startup_event():
    global redis_pool, db_pool
    
    redis_pool = aioredis.from_url(
        "redis://localhost:6379",
        encoding="utf-8",
        decode_responses=True,
        max_connections=20
    )
    
    db_pool = await asyncpg.create_pool(
        user="quantum_user",
        password="secure_password_here",
        database="quantum_harmonic",
        host="localhost",
        port=5432,
        min_size=5,
        max_size=20
    )
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS presets (
                id UUID PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                particle_count INTEGER DEFAULT 1000,
                color_scheme VARCHAR(50) DEFAULT 'aurora',
                frequency_bands JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            
            CREATE TABLE IF NOT EXISTS audio_analyses (
                id UUID PRIMARY KEY,
                preset_id UUID REFERENCES presets(id),
                file_name VARCHAR(500),
                duration FLOAT,
                tempo FLOAT,
                analysis_data JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            
            CREATE INDEX IF NOT EXISTS idx_presets_name ON presets(name);
            CREATE INDEX IF NOT EXISTS idx_audio_analyses_preset ON audio_analyses(preset_id);
        """)


@app.on_event("shutdown")
async def shutdown_event():
    if redis_pool:
        await redis_pool.close()
    if db_pool:
        await db_pool.close()


class HashRequest(BaseModel):
    keys: List[Any]
    values: List[Any]
    
    @validator('keys')
    def validate_keys(cls, v):
        if not v:
            raise ValueError('Keys array cannot be empty')
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "keys": [1, 2, 3, 4, 5],
                "values": ["a", "b", "c"]
            }
        }


class PresetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    particle_count: int = Field(default=1000, ge=100, le=50000)
    color_scheme: str = Field(default="aurora")
    frequency_bands: Dict[str, List[int]] = Field(default_factory=dict)
    
    @validator('color_scheme')
    def validate_color_scheme(cls, v):
        allowed = {"aurora", "ocean", "fire", "cosmic"}
        if v not in allowed:
            raise ValueError(f'Color scheme must be one of: {allowed}')
        return v


class ConnectionManager:
    """Manages WebSocket connections for real-time visualization updates."""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.connection_metadata: Dict[str, Dict] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.connection_metadata[client_id] = {
            "connected_at": datetime.now(timezone.utc).isoformat(),
            "message_count": 0
        }
        
        await redis_pool.sadd("active_connections", client_id)
        await redis_pool.hset(
            f"connection:{client_id}",
            mapping=self.connection_metadata[client_id]
        )
    
    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        if client_id in self.connection_metadata:
            del self.connection_metadata[client_id]
        
        asyncio.create_task(self._cleanup_redis(client_id))
    
    async def _cleanup_redis(self, client_id: str):
        await redis_pool.srem("active_connections", client_id)
        await redis_pool.delete(f"connection:{client_id}")
    
    async def broadcast_frequency_data(self, data: Dict[str, Any]):
        disconnected = []
        
        for client_id, connection in self.active_connections.items():
            try:
                await connection.send_json(data)
                self.connection_metadata[client_id]["message_count"] += 1
            except WebSocketDisconnect:
                disconnected.append(client_id)
            except Exception as e:
                print(f"Error sending to client {client_id}: {e}")
                disconnected.append(client_id)
        
        for client_id in disconnected:
            self.disconnect(client_id)
    
    async def send_to_client(self, client_id: str, data: Dict[str, Any]):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_json(data)
    
    @property
    def connection_count(self) -> int:
        return len(self.active_connections)


manager = ConnectionManager()


@app.middleware("http")
async def add_request_metadata(request, call_next):
    request_id = str(uuid.uuid4())
    start_time = datetime.now(timezone.utc)
    
    response = await call_next(request)
    
    process_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
    
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Processing-Time"] = f"{process_time:.2f}ms"
    
    return response


@app.get("/api/health")
async def health_check():
    return {
        "status": "operational",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "2.1.0",
        "connections": manager.connection_count,
        "redis_connected": redis_pool is not None,
        "db_connected": db_pool is not None
    }


@app.post("/api/hash/generate")
async def generate_hash(request: HashRequest):
    cache_key = f"hash:{hashlib.md5(json.dumps(request.dict(), sort_keys=True).encode()).hexdigest()}"
    
    cached_result = await redis_pool.get(cache_key)
    if cached_result:
        return JSONResponse(
            content={"result": json.loads(cached_result), "cached": True}
        )
    
    hash_table = HashTableService()
    result = hash_table.arr_to_obj(request.keys, request.values)
    
    await redis_pool.setex(
        cache_key,
        300,
        json.dumps(result)
    )
    
    return JSONResponse(
        content={
            "result": result,
            "cached": False,
            "keys_count": len(request.keys),
            "values_count": len(request.values),
            "hash_size": len(hash_table)
        }
    )


@app.post("/api/presets")
async def create_preset(preset: PresetCreate):
    async with db_pool.acquire() as conn:
        preset_id = str(uuid.uuid4())
        
        await conn.execute(
            """
            INSERT INTO presets (id, name, particle_count, color_scheme, frequency_bands)
            VALUES ($1, $2, $3, $4, $5)
            """,
            preset_id,
            preset.name,
            preset.particle_count,
            preset.color_scheme,
            json.dumps(preset.frequency_bands)
        )
    
    await redis_pool.delete("presets:all")
    
    return {"id": preset_id, "message": "Preset created successfully"}


@app.get("/api/presets")
async def list_presets():
    cached = await redis_pool.get("presets:all")
    if cached:
        return json.loads(cached)
    
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM presets ORDER BY created_at DESC LIMIT 50")
    
    presets = [dict(row) for row in rows]
    
    for preset in presets:
        for date_field in ['created_at', 'updated_at']:
            if date_field in preset and preset[date_field]:
                preset[date_field] = preset[date_field].isoformat()
    
    await redis_pool.setex("presets:all", 60, json.dumps(presets))
    
    return presets


@app.post("/api/audio/analyze")
async def analyze_audio(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    temp_file_path = f"/tmp/{uuid.uuid4()}_{file.filename}"
    
    try:
        async with aiofiles.open(temp_file_path, 'wb') as f:
            while chunk := await file.read(1024 * 1024):
                await f.write(chunk)
        
        analyzer = AudioAnalyzer()
        
        loop = asyncio.get_event_loop()
        analysis_result = await loop.run_in_executor(
            None, analyzer.analyze_file, temp_file_path
        )
        
        analysis_id = str(uuid.uuid4())
        
        if background_tasks:
            background_tasks.add_task(
                store_analysis, analysis_id, file.filename, analysis_result
            )
        
        return {
            "analysis_id": analysis_id,
            "file_name": file.filename,
            **analysis_result
        }
    
    finally:
        try:
            import os
            os.remove(temp_file_path)
        except FileNotFoundError:
            pass


async def store_analysis(analysis_id: str, file_name: str, analysis_data: Dict):
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO audio_analyses (id, file_name, duration, tempo, analysis_data)
            VALUES ($1, $2, $3, $4, $5)
            """,
            analysis_id,
            file_name,
            analysis_data.get("duration"),
            analysis_data.get("tempo"),
            json.dumps(analysis_data)
        )


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    
    try:
        await websocket.send_json({
            "type": "connection_established",
            "client_id": client_id,
            "message": "Connected to Quantum Harmonic Stream",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        while True:
            data = await websocket.receive_json()
            
            if data.get("type") == "frequency_update":
                await manager.broadcast_frequency_data({
                    "type": "frequency_broadcast",
                    "source": client_id,
                    "data": data.get("frequencies", [])
                })
            
            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()})
    
    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        print(f"WebSocket error for client {client_id}: {e}")
        manager.disconnect(client_id)


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "quantum_visualizer_backend:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        workers=4,
        log_level="info"
    )
