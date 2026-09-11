import assert from 'node:assert/strict';
import test from 'node:test';
import { exactLoopFrames, prepareLoopBuffers } from '../src/loopBuffers.ts';
class Buffer {
  constructor(channels, length, sampleRate) {
    this.numberOfChannels = channels; this.length = length; this.sampleRate = sampleRate;
    this.data = Array.from({length:channels},()=>new Float32Array(length));
  }
  getChannelData(channel) { return this.data[channel]; }
  copyToChannel(data, channel) { this.data[channel].set(data); }
}
const context = { createBuffer: (...args) => new Buffer(...args) };
test('piano after 48k to 44.1k decoding needs one zero sample, shared by both slots', () => {
  assert.notEqual((220499/44100)*44100,220499);
  assert.equal(exactLoopFrames(220499,44100),220500);
  const a = new Buffer(2,220499,44100), b = new Buffer(2,220499,44100);
  for (let i=0;i<a.length;i++) { a.data[0][i]=Math.sin(i);a.data[1][i]=Math.cos(i);b.data[0][i]=i/1e6;b.data[1][i]=-i/1e6; }
  const result=prepareLoopBuffers(context,a,b);
  for (const key of ['a','b']) { const original=key==='a'?a:b, padded=result[key];
    assert.equal(padded.length,220500);
    for(let ch=0;ch<2;ch++) {assert.deepEqual(padded.data[ch].subarray(0,original.length),original.data[ch]);assert.equal(padded.data[ch][original.length],0);}
  }
});
test('exact endpoints retain the original audio buffers',()=>{
  const a=new Buffer(2,239999,48000),b=new Buffer(2,239999,48000);
  const result=prepareLoopBuffers(context,a,b);assert.equal(result.a,a);assert.equal(result.b,b);
});
test('all common rates produce exact endpoints with bounded added silence',()=>{
  for(const rate of [8000,16000,22050,32000,44100,48000,88200,96000,192000])for(let n=1;n<=500000;n+=13) {
    const frames=exactLoopFrames(n,rate);assert.equal((frames/rate)*rate,frames);assert.ok(frames>=n&&(frames-n)/rate<.001);
  }
});
