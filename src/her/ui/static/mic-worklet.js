// Captures mic audio, downsamples from the AudioContext rate (usually 48 kHz)
// to 24 kHz, converts Float32 -> Int16 PCM, and ships ~50 ms chunks to the
// main thread via port.postMessage.

class MicProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.targetRate = (options && options.processorOptions && options.processorOptions.targetRate) || 24000;
    this.inputRate = sampleRate;       // provided by AudioWorkletGlobalScope
    this.ratio = this.inputRate / this.targetRate;
    this.buffer = [];                  // queued float samples after resampling
    this.frameSize = Math.round(this.targetRate * 0.05); // ~50 ms @ 24 kHz = 1200 samples
    this._readIdx = 0;                 // fractional read index into the *input* stream
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const ch = input[0];               // mono
    if (!ch) return true;

    // Simple linear-interp resampling. Not pretty but fine for 48k->24k.
    let i = this._readIdx;
    while (i < ch.length - 1) {
      const i0 = Math.floor(i);
      const frac = i - i0;
      const sample = ch[i0] * (1 - frac) + ch[i0 + 1] * frac;
      this.buffer.push(sample);
      i += this.ratio;
    }
    // Keep the fractional offset for the next block.
    this._readIdx = i - ch.length;
    if (this._readIdx < 0) this._readIdx = 0;

    while (this.buffer.length >= this.frameSize) {
      const slice = this.buffer.splice(0, this.frameSize);
      const pcm = new Int16Array(slice.length);
      for (let k = 0; k < slice.length; k++) {
        let s = Math.max(-1, Math.min(1, slice[k]));
        pcm[k] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
    return true;
  }
}

registerProcessor("mic-processor", MicProcessor);
