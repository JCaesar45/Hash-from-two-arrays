interface Particle {
    x: number;
    y: number;
    vx: number;
    vy: number;
    radius: number;
    hue: number;
    saturation: number;
    lightness: number;
    alpha: number;
    life: number;
    maxLife: number;
    frequencyBin: number;
}

interface FrequencyBand {
    low: number;
    high: number;
    amplitude: number;
}

class HashTable<K extends string | number | symbol, V> {
    private table: Map<K, V>;
    private collisionCount: number;
    
    constructor() {
        this.table = new Map<K, V>();
        this.collisionCount = 0;
    }
    
    public arrToObj(keys: K[], values: V[]): Record<K, V | undefined> {
        const result = {} as Record<K, V | undefined>;
        const startTime = performance.now();
        
        for (let i = 0; i < keys.length; i++) {
            const key = keys[i];
            const value = i < values.length ? values[i] : undefined;
            
            result[key] = value;
            
            if (this.table.has(key)) {
                this.collisionCount++;
            }
            this.table.set(key, value as V);
        }
        
        const endTime = performance.now();
        console.debug(`Hash generation took ${(endTime - startTime).toFixed(3)}ms`);
        console.debug(`Collisions: ${this.collisionCount}`);
        
        return result;
    }
    
    public getCollisionStats(): { collisions: number; loadFactor: number } {
        return {
            collisions: this.collisionCount,
            loadFactor: this.table.size / (this.table.size * 1.5)
        };
    }
    
    public clear(): void {
        this.table.clear();
        this.collisionCount = 0;
    }
}

class ParticleSystem {
    private canvas: HTMLCanvasElement;
    private ctx: CanvasRenderingContext2D;
    private particles: Particle[];
    private targetCount: number;
    private audioAnalyser: AnalyserNode | null;
    private frequencyData: Uint8Array | null;
    private lastFrameTime: number;
    private frameCount: number;
    private fps: number;
    private colorSchemes: Map<string, (hue: number) => [number, number, number]>;
    private activeColorScheme: string;
    
    constructor(canvas: HTMLCanvasElement) {
        this.canvas = canvas;
        const context = canvas.getContext('2d', {
            alpha: true,
            desynchronized: true,
            willReadFrequently: false
        });
        
        if (!context) {
            throw new Error('Failed to get 2D context');
        }
        
        this.ctx = context;
        this.particles = [];
        this.targetCount = 1000;
        this.audioAnalyser = null;
        this.frequencyData = null;
        this.lastFrameTime = performance.now();
        this.frameCount = 0;
        this.fps = 60;
        this.activeColorScheme = 'aurora';
        
        this.colorSchemes = new Map([
            ['aurora', (h: number): [number, number, number] => [
                (Math.sin(h * 0.02) * 30 + 180) % 360,
                80,
                60
            ]],
            ['ocean', (h: number): [number, number, number] => [
                200 + Math.sin(h * 0.01) * 20,
                70,
                50 + Math.cos(h * 0.015) * 20
            ]],
            ['fire', (h: number): [number, number, number] => [
                20 + Math.sin(h * 0.03) * 15,
                90,
                55
            ]],
            ['cosmic', (h: number): [number, number, number] => [
                (h * 1.5) % 360,
                50,
                60 + Math.sin(h * 0.01) * 30
            ]]
        ]);
        
        this.resizeCanvas();
        this.initParticles(this.targetCount);
        
        window.addEventListener('resize', this.resizeCanvas.bind(this));
    }
    
    private resizeCanvas(): void {
        const dpr = window.devicePixelRatio || 1;
        const rect = this.canvas.getBoundingClientRect();
        
        this.canvas.width = rect.width * dpr;
        this.canvas.height = rect.height * dpr;
        this.ctx.scale(dpr, dpr);
        
        this.canvas.style.width = `${rect.width}px`;
        this.canvas.style.height = `${rect.height}px`;
    }
    
    private initParticles(count: number): void {
        const width = this.canvas.width / (window.devicePixelRatio || 1);
        const height = this.canvas.height / (window.devicePixelRatio || 1);
        
        this.particles = Array.from({ length: count }, (): Particle => ({
            x: Math.random() * width,
            y: Math.random() * height,
            vx: (Math.random() - 0.5) * 2,
            vy: (Math.random() - 0.5) * 2,
            radius: Math.random() * 4 + 1,
            hue: Math.random() * 360,
            saturation: 80,
            lightness: 60,
            alpha: Math.random() * 0.6 + 0.2,
            life: Math.random(),
            maxLife: Math.random() * 100 + 50,
            frequencyBin: Math.floor(Math.random() * 32)
        }));
    }
    
    public setAudioAnalyzer(analyser: AnalyserNode): void {
        this.audioAnalyser = analyser;
        this.frequencyData = new Uint8Array(analyser.frequencyBinCount);
    }
    
    public resize(newCount: number): void {
        this.targetCount = newCount;
        
        const currentCount = this.particles.length;
        if (newCount > currentCount) {
            const width = this.canvas.width / (window.devicePixelRatio || 1);
            const height = this.canvas.height / (window.devicePixelRatio || 1);
            
            for (let i = 0; i < newCount - currentCount; i++) {
                this.particles.push({
                    x: Math.random() * width,
                    y: Math.random() * height,
                    vx: (Math.random() - 0.5) * 2,
                    vy: (Math.random() - 0.5) * 2,
                    radius: Math.random() * 4 + 1,
                    hue: Math.random() * 360,
                    saturation: 80,
                    lightness: 60,
                    alpha: Math.random() * 0.6 + 0.2,
                    life: Math.random(),
                    maxLife: Math.random() * 100 + 50,
                    frequencyBin: Math.floor(Math.random() * 32)
                });
            }
        } else if (newCount < currentCount) {
            this.particles.length = newCount;
        }
    }
    
    public explode(): void {
        const width = this.canvas.width / (window.devicePixelRatio || 1);
        const height = this.canvas.height / (window.devicePixelRatio || 1);
        const centerX = width / 2;
        const centerY = height / 2;
        
        this.particles.forEach(p => {
            const angle = Math.atan2(p.y - centerY, p.x - centerX);
            const force = Math.random() * 20 + 5;
            p.vx += Math.cos(angle) * force;
            p.vy += Math.sin(angle) * force;
        });
    }
    
    public celebrateHashCreation(keyCount: number): void {
        this.particles.forEach((p, i) => {
            p.hue = (i * 137.508) % 360;
            p.alpha = 0.9;
            p.radius = 3 + Math.sin(i * 0.5) * 2;
        });
    }
    
    public update(timestamp: number): void {
        const width = this.canvas.width / (window.devicePixelRatio || 1);
        const height = this.canvas.height / (window.devicePixelRatio || 1);
        
        const deltaTime = (timestamp - this.lastFrameTime) / 1000;
        this.lastFrameTime = timestamp;
        
        this.frameCount++;
        if (this.frameCount % 60 === 0) {
            this.fps = Math.round(1 / deltaTime);
        }
        
        if (this.audioAnalyser && this.frequencyData) {
            this.audioAnalyser.getByteFrequencyData(this.frequencyData);
        }
        
        this.ctx.clearRect(0, 0, width, height);
        
        const colorFn = this.colorSchemes.get(this.activeColorScheme)!;
        
        for (const p of this.particles) {
            let frequencyInfluence = 1.0;
            
            if (this.frequencyData) {
                const binIndex = p.frequencyBin % this.frequencyData.length;
                frequencyInfluence = this.frequencyData[binIndex] / 255;
            }
            
            const speedMultiplier = 1 + frequencyInfluence * 3;
            
            p.x += p.vx * deltaTime * 60 * speedMultiplier;
            p.y += p.vy * deltaTime * 60 * speedMultiplier;
            
            p.vx *= 0.999;
            p.vy *= 0.999;
            
            p.life += 0.01;
            if (p.life > 1) p.life = 0;
            
            if (p.x < -50) p.x = width + 50;
            if (p.x
