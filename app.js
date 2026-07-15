import { ParticleSystem } from "./particles.js";
import { HashTable } from "./hashTable.js";
import { AudioProcessor } from "./audioProcessor.js";

const CONFIG = {
  particleCount: 1000,
  fftSize: 2048,
  smoothingTimeConstant: 0.8,
  minDecibels: -90,
  maxDecibels: -10
};

class QuantumHarmonicApp {
  #particleSystem;
  #audioProcessor;
  #hashTable;
  #animationFrameId;
  #panels;
  #toastContainer;

  constructor() {
    this.#particleSystem = new ParticleSystem(
      document.getElementById("particleCanvas")
    );
    this.#audioProcessor = new AudioProcessor(CONFIG);
    this.#hashTable = new HashTable();
    this.#panels = document.querySelectorAll(".panel");
    this.#toastContainer = document.getElementById("toast-container");

    this.#initEventListeners();
    this.#startRenderLoop();
    this.#showPanel("visualizer");
  }

  #initEventListeners() {
    document.querySelectorAll(".nav-link").forEach((link) => {
      link.addEventListener("click", (e) => {
        const panelName = e.target.dataset.panel;
        this.#showPanel(panelName);

        document
          .querySelectorAll(".nav-link")
          .forEach((l) => l.removeAttribute("aria-current"));
        e.target.setAttribute("aria-current", "page");
      });
    });

    document.getElementById("particleSlider").addEventListener("input", (e) => {
      const count = parseInt(e.target.value);
      this.#particleSystem.resize(count);
      this.#showToast(`Particles: ${count.toLocaleString()}`, "info");
    });

    document.getElementById("audioUploadBtn").addEventListener("click", () => {
      document.getElementById("audioFileInput").click();
    });

    document
      .getElementById("audioFileInput")
      .addEventListener("change", (e) => {
        const file = e.target.files[0];
        if (file) {
          this.#handleAudioUpload(file);
        }
      });

    document.getElementById("generateHashBtn").addEventListener("click", () => {
      this.#generateHashFromInputs();
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === " " && e.target === document.body) {
        e.preventDefault();
        this.#particleSystem.explode();
      }
    });
  }

  #showPanel(panelName) {
    this.#panels.forEach((panel) => {
      panel.classList.remove("active");
      panel.classList.add("hidden");
    });

    const targetPanel = document.getElementById(`${panelName}-panel`);
    if (targetPanel) {
      targetPanel.classList.remove("hidden");
      requestAnimationFrame(() => {
        targetPanel.classList.add("active");
      });
    }
  }

  async #handleAudioUpload(file) {
    try {
      this.#showToast("Processing audio...", "loading");

      const arrayBuffer = await file.arrayBuffer();
      const audioContext = this.#audioProcessor.getContext();
      const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);

      this.#audioProcessor.connectSource(audioBuffer);
      this.#particleSystem.setAudioAnalyzer(
        this.#audioProcessor.getAnalyserNode()
      );

      this.#showToast("Audio loaded successfully! 🎵", "success");
    } catch (error) {
      console.error("Audio processing error:", error);
      this.#showToast("Failed to load audio file", "error");
    }
  }

  #generateHashFromInputs() {
    try {
      const keysInput = document.getElementById("keysInput").value;
      const valuesInput = document.getElementById("valuesInput").value;

      const keys = JSON.parse(keysInput);
      const values = JSON.parse(valuesInput);

      if (!Array.isArray(keys) || !Array.isArray(values)) {
        throw new Error("Both inputs must be valid arrays");
      }

      const result = this.#hashTable.arrToObj(keys, values);

      document.getElementById("hashResult").textContent = JSON.stringify(
        result,
        null,
        2
      );

      this.#particleSystem.celebrateHashCreation(keys.length);

      this.#showToast("Hash generated! ✨", "success");
    } catch (error) {
      this.#showToast(`Error: ${error.message}`, "error");
      document.getElementById("hashResult").textContent = "Invalid input";
    }
  }

  #showToast(message, type = "info") {
    const toast = document.createElement("div");
    const colors = {
      info: "border-cyan-400/30 bg-cyan-500/10",
      success: "border-emerald-400/30 bg-emerald-500/10",
      error: "border-red-400/30 bg-red-500/10",
      loading: "border-purple-400/30 bg-purple-500/10"
    };

    toast.className = `toast-enter glass-panel px-6 py-3 rounded-xl border ${colors[type]} text-sm font-medium`;
    toast.textContent = message;

    this.#toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateX(120%)";
      toast.style.transition = "all 0.4s cubic-bezier(0.16, 1, 0.3, 1)";

      setTimeout(() => toast.remove(), 400);
    }, 3000);
  }

  #startRenderLoop() {
    const render = (timestamp) => {
      this.#particleSystem.update(timestamp);

      if (this.#audioProcessor.isActive()) {
        const frequencyData = this.#audioProcessor.getFrequencyData();
        this.#updateFrequencyBars(frequencyData);
      }

      this.#animationFrameId = requestAnimationFrame(render);
    };

    this.#animationFrameId = requestAnimationFrame(render);
  }

  #updateFrequencyBars(frequencyData) {
    const container = document.getElementById("frequency-bars");
    const barsToShow = 16;

    while (container.children.length < barsToShow) {
      const bar = document.createElement("div");
      bar.className = "frequency-bar";
      container.appendChild(bar);
    }

    const step = Math.floor(frequencyData.length / barsToShow);

    Array.from(container.children).forEach((bar, i) => {
      const value = frequencyData[i * step] / 255;
      const scaledValue = Math.pow(value, 0.8);
      bar.style.transform = `scaleX(${Math.max(0.02, scaledValue)})`;
      bar.style.opacity = 0.3 + scaledValue * 0.7;
    });
  }

  destroy() {
    if (this.#animationFrameId) {
      cancelAnimationFrame(this.#animationFrameId);
    }
    this.#audioProcessor.dispose();
    this.#particleSystem.destroy();
  }
}

const app = new QuantumHarmonicApp();

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    app.destroy();
  });
}
