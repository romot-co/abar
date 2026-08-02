import { useCallback, useEffect, useRef, useState } from "react";
import type { DeckAudioView } from "./generated";

type Slot = "a" | "b";
type Mode = "auto" | "manual";
export type ComparisonAudio = { delivery_id: string; audio: DeckAudioView[] };
export type PlayerTelemetry = { switches: number; listenMs: { a: number; b: number }; answerMs: number };

export function useComparisonPlayer(comparison: ComparisonAudio | null) {
  const [activeSlot, setActiveSlot] = useState<Slot>("a");
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [loading, setLoading] = useState(comparison !== null);
  const [error, setError] = useState<string | null>(null);
  const [heard, setHeard] = useState<Record<Slot, boolean>>({ a: false, b: false });
  const contextRef = useRef<AudioContext | null>(null);
  const buffersRef = useRef<Record<Slot, AudioBuffer> | null>(null);
  const gainsRef = useRef<Record<Slot, GainNode> | null>(null);
  const sourcesRef = useRef<Record<Slot, AudioBufferSourceNode> | null>(null);
  const offsetRef = useRef(0);
  const startedAtContextRef = useRef<number | null>(null);
  const playingRef = useRef(false);
  const durationRef = useRef(0);
  const animationRef = useRef<number | null>(null);
  const answerStartedRef = useRef<number | null>(null);
  const activeSinceRef = useRef<number | null>(null);
  const listenRef = useRef({ a: 0, b: 0 });
  const switchesRef = useRef(0);
  const activeSlotRef = useRef<Slot>("a");
  const modeRef = useRef<Mode>("auto");
  const previousPositionRef = useRef(0);

  const stopSources = useCallback(() => {
    if (!sourcesRef.current) return;
    for (const source of Object.values(sourcesRef.current)) {
      try { source.stop(); } catch { /* one-shot source may already be stopped */ }
      source.disconnect();
    }
    sourcesRef.current = null;
  }, []);

  const currentPosition = useCallback(() => {
    const context = contextRef.current;
    const started = startedAtContextRef.current;
    if (!context || started === null || !playingRef.current || durationRef.current <= 0) return offsetRef.current;
    return (offsetRef.current + Math.max(0, context.currentTime - started)) % durationRef.current;
  }, []);

  const startSources = useCallback((offset: number) => {
    const context = contextRef.current;
    const buffers = buffersRef.current;
    const gains = gainsRef.current;
    if (!context || !buffers || !gains) return false;
    const when = context.currentTime + 0.02;
    const a = context.createBufferSource();
    const b = context.createBufferSource();
    a.buffer = buffers.a;
    b.buffer = buffers.b;
    a.loop = true;
    b.loop = true;
    a.connect(gains.a);
    b.connect(gains.b);
    a.start(when, offset);
    b.start(when, offset);
    sourcesRef.current = { a, b };
    offsetRef.current = offset;
    startedAtContextRef.current = when;
    return true;
  }, []);

  const account = useCallback((slot: Slot) => {
    if (activeSinceRef.current === null) return;
    const now = performance.now();
    listenRef.current[slot] += now - activeSinceRef.current;
    activeSinceRef.current = now;
  }, []);

  const crossfadeTo = useCallback((next: Slot) => {
    const context = contextRef.current;
    const gains = gainsRef.current;
    if (!context || !gains) return;
    const previous = activeSlotRef.current;
    if (previous === next) return;
    account(previous);
    const now = context.currentTime;
    for (const slot of [previous, next] as Slot[]) {
      gains[slot].gain.cancelScheduledValues(now);
      gains[slot].gain.setValueAtTime(gains[slot].gain.value, now);
    }
    gains[previous].gain.linearRampToValueAtTime(0, now + 0.01);
    gains[next].gain.linearRampToValueAtTime(1, now + 0.01);
    activeSlotRef.current = next;
    setActiveSlot(next);
    setHeard((value) => value[next] ? value : { ...value, [next]: true });
  }, [account]);

  const play = useCallback(async () => {
    const context = contextRef.current;
    if (!context || playingRef.current) return;
    await context.resume();
    if (!startSources(offsetRef.current)) return;
    const now = performance.now();
    answerStartedRef.current ??= now;
    activeSinceRef.current = now;
    playingRef.current = true;
    setPlaying(true);
    setHeard((value) => value[activeSlotRef.current] ? value : { ...value, [activeSlotRef.current]: true });
  }, [startSources]);
  const playRef = useRef(play);
  useEffect(() => {
    playRef.current = play;
  }, [play]);

  const pause = useCallback(() => {
    if (!playingRef.current) return;
    account(activeSlotRef.current);
    activeSinceRef.current = null;
    offsetRef.current = currentPosition();
    startedAtContextRef.current = null;
    playingRef.current = false;
    stopSources();
    setPosition(offsetRef.current);
    setPlaying(false);
  }, [account, currentPosition, stopSources]);

  const switchSlot = useCallback(async () => {
    modeRef.current = "manual";
    if (!playingRef.current) await play();
    switchesRef.current += 1;
    crossfadeTo(activeSlotRef.current === "a" ? "b" : "a");
  }, [crossfadeTo, play]);

  const selectSlot = useCallback(async (slot: Slot) => {
    if (activeSlotRef.current === slot && modeRef.current === "manual") {
      if (playingRef.current) pause();
      else await play();
      return;
    }
    modeRef.current = "manual";
    if (!playingRef.current) await play();
    if (activeSlotRef.current !== slot) {
      switchesRef.current += 1;
      crossfadeTo(slot);
    }
  }, [crossfadeTo, pause, play]);

  const urlA = comparison?.audio.find((item) => item.slot === "A")?.url;
  const urlB = comparison?.audio.find((item) => item.slot === "B")?.url;
  const deliveryId = comparison?.delivery_id ?? null;
  useEffect(() => {
    setActiveSlot("a");
    setPlaying(false);
    setPosition(0);
    setDuration(0);
    setLoading(deliveryId !== null);
    setError(null);
    setHeard({ a: false, b: false });
    offsetRef.current = 0;
    startedAtContextRef.current = null;
    playingRef.current = false;
    durationRef.current = 0;
    answerStartedRef.current = null;
    activeSinceRef.current = null;
    listenRef.current = { a: 0, b: 0 };
    switchesRef.current = 0;
    activeSlotRef.current = "a";
    modeRef.current = "auto";
    previousPositionRef.current = 0;
    if (deliveryId === null || !urlA || !urlB) return;

    let cancelled = false;
    const context = new AudioContext();
    const gainA = context.createGain();
    const gainB = context.createGain();
    gainA.connect(context.destination);
    gainB.connect(context.destination);
    gainA.gain.value = 1;
    gainB.gain.value = 0;
    contextRef.current = context;
    gainsRef.current = { a: gainA, b: gainB };
    void Promise.all([fetch(urlA), fetch(urlB)])
      .then(async ([first, second]) => {
        if (!first.ok || !second.ok) throw new Error("比較音声を読み込めませんでした");
        return Promise.all([
          first.arrayBuffer().then((data) => context.decodeAudioData(data)),
          second.arrayBuffer().then((data) => context.decodeAudioData(data)),
        ]);
      })
      .then(([a, b]) => {
        if (cancelled) return;
        buffersRef.current = { a, b };
        durationRef.current = Math.min(a.duration, b.duration);
        setDuration(durationRef.current);
        setLoading(false);
        // Browsers may reject this before the first user gesture; the Play button remains available.
        void playRef.current().catch(() => undefined);
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "比較音声を読み込めませんでした");
          setLoading(false);
        }
      });
    const update = () => {
      if (playingRef.current) {
        const now = currentPosition();
        if (modeRef.current === "auto" && now + 0.05 < previousPositionRef.current) {
          crossfadeTo(activeSlotRef.current === "a" ? "b" : "a");
        }
        previousPositionRef.current = now;
        setPosition(now);
      }
      animationRef.current = requestAnimationFrame(update);
    };
    animationRef.current = requestAnimationFrame(update);
    return () => {
      cancelled = true;
      if (animationRef.current !== null) cancelAnimationFrame(animationRef.current);
      stopSources();
      gainA.disconnect();
      gainB.disconnect();
      void context.close();
      contextRef.current = null;
      buffersRef.current = null;
      gainsRef.current = null;
    };
  }, [crossfadeTo, currentPosition, deliveryId, stopSources, urlA, urlB]);

  const seek = useCallback((seconds: number) => {
    const target = Math.max(0, Math.min(seconds, durationRef.current));
    const resume = playingRef.current;
    stopSources();
    offsetRef.current = target;
    startedAtContextRef.current = null;
    previousPositionRef.current = target;
    setPosition(target);
    if (resume) startSources(target);
  }, [startSources, stopSources]);

  const snapshotTelemetry = useCallback((): PlayerTelemetry => {
    account(activeSlotRef.current);
    return {
      switches: switchesRef.current,
      listenMs: { a: Math.round(listenRef.current.a), b: Math.round(listenRef.current.b) },
      answerMs: answerStartedRef.current === null ? 0 : Math.round(performance.now() - answerStartedRef.current),
    };
  }, [account]);

  return { activeSlot, playing, position, duration, loading, error, heard, play, pause, switchSlot, selectSlot, seek, snapshotTelemetry };
}

export type ComparisonPlayer = ReturnType<typeof useComparisonPlayer>;
