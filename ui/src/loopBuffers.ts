// Chromium can get stuck on the last render quantum when a whole-buffer loop's
// duration converts back to a fractional frame (e.g. 220499 / 44100). Keep the
// decoded samples intact and append only the zeros needed for an exact endpoint.
export function exactLoopFrames(frames: number, sampleRate: number): number {
  while ((frames / sampleRate) * sampleRate !== frames) frames += 1;
  return frames;
}

export function prepareLoopBuffers(
  context: Pick<BaseAudioContext, "createBuffer">,
  a: AudioBuffer,
  b: AudioBuffer,
): { a: AudioBuffer; b: AudioBuffer } {
  const frames = exactLoopFrames(Math.max(a.length, b.length), a.sampleRate);
  const pad = (buffer: AudioBuffer) => {
    if (buffer.length === frames) return buffer;
    const padded = context.createBuffer(buffer.numberOfChannels, frames, buffer.sampleRate);
    for (let channel = 0; channel < buffer.numberOfChannels; channel += 1) {
      padded.copyToChannel(buffer.getChannelData(channel), channel);
    }
    return padded;
  };
  return { a: pad(a), b: pad(b) };
}
