import { useCallback, useEffect, useRef, useState } from "react";
import type { DeckAudioView } from "./generated";
import { prepareLoopBuffers } from "./loopBuffers";

type Slot = "a" | "b";
type Mode = "auto" | "manual";
export type ComparisonAudio = { delivery_id: string; audio: DeckAudioView[] };
export type PlayerTelemetry = { switches: number; listenMs: { a: number; b: number }; answerMs: number };
type DeliveryStatus = { id: string | null; loading: boolean; error: string | null; heard: Record<Slot, boolean> };

function initialStatus(id: string | null): DeliveryStatus {
  return { id, loading: id !== null, error: null, heard: { a: false, b: false } };
}

export function useComparisonPlayer(comparison: ComparisonAudio | null) {
  const [activeSlot, setActiveSlot] = useState<Slot>("a");
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  // loading/error/heard are keyed by delivery so the first render of a new comparison
  // never inherits the previous comparison's "both heard" state before the reset effect runs.
  const deliveryId = comparison?.delivery_id ?? null;
  const [status, setStatus] = useState<DeliveryStatus>(() => initialStatus(deliveryId));
  const current = status.id === deliveryId ? status : initialStatus(deliveryId);
  const { loading, error, heard } = current;
  const deliveryRef = useRef(deliveryId);
  const contextRef = useRef<AudioContext | null>(null);
  const buffersRef = useRef<Record<Slot, AudioBuffer> | null>(null);
  const gainsRef = useRef<Record<Slot, GainNode> | null>(null);
  const sourcesRef = useRef<Record<Slot, AudioBufferSourceNode> | null>(null);
  const offsetRef = useRef(0);
  const startedAtContextRef = useRef<number | null>(null);
  const playingRef = useRef(false);
  const playGenerationRef = useRef(0);
  const durationRef = useRef(0);
  const animationRef = useRef<number | null>(null);
  const answerStartedRef = useRef<number | null>(null);
  const activeSinceRef = useRef<number | null>(null);
  const listenRef = useRef({ a: 0, b: 0 });
  const switchesRef = useRef(0);
  const activeSlotRef = useRef<Slot>("a");
  const modeRef = useRef<Mode>("auto");
  const previousPositionRef = useRef(0);

  const update = useCallback((id: string | null, change: (value: DeliveryStatus) => DeliveryStatus) => {
    setStatus((value) => {
      const base = value.id === id ? value : initialStatus(id);
      return change(base);
    });
  }, []);
  const markHeard = useCallback((slot: Slot) => {
    update(deliveryRef.current, (value) => value.heard[slot] ? value : { ...value, heard: { ...value.heard, [slot]: true } });
  }, [update]);

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
    markHeard(next);
  }, [account, markHeard]);

  const play = useCallback(async () => {
    const context = contextRef.current;
    if (!context) return false;
    if (playingRef.current) return true;
    const generation = playGenerationRef.current;
    try {
      await context.resume();
    } catch {
      if (context === contextRef.current && generation === playGenerationRef.current) {
        update(deliveryRef.current, (value) => ({ ...value, error: "音声の再生を開始できませんでした。比較を開き直してください" }));
      }
      return false;
    }
    // Autoplay and a user click may await the same permission. Only one may start,
    // and a request from a paused or replaced deck must never start its successor.
    if (context !== contextRef.current || generation !== playGenerationRef.current) return false;
    if (playingRef.current) return true;
    if (!startSources(offsetRef.current)) return false;
    const now = performance.now();
    answerStartedRef.current ??= now;
    activeSinceRef.current = now;
    playingRef.current = true;
    setPlaying(true);
    markHeard(activeSlotRef.current);
    return true;
  }, [markHeard, startSources]);
  const playRef = useRef(play);
  useEffect(() => {
    playRef.current = play;
  }, [play]);

  const pause = useCallback(() => {
    playGenerationRef.current += 1;
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
    if (!playingRef.current && !(await play())) return;
    if (!playingRef.current) return;
    switchesRef.current += 1;
    crossfadeTo(activeSlotRef.current === "a" ? "b" : "a");
  }, [crossfadeTo, play]);

  // Pressing the card that is playing pauses it (also during the automatic alternation);
  // pressing the active card while paused resumes it; pressing the other card switches to it.
  const selectSlot = useCallback(async (slot: Slot) => {
    if (activeSlotRef.current === slot && (playingRef.current || modeRef.current === "manual")) {
      modeRef.current = "manual";
      if (playingRef.current) pause();
      else await play();
      return;
    }
    modeRef.current = "manual";
    if (!playingRef.current && !(await play())) return;
    if (!playingRef.current) return;
    if (activeSlotRef.current !== slot) {
      switchesRef.current += 1;
      crossfadeTo(slot);
    }
  }, [crossfadeTo, pause, play]);

  const urlA = comparison?.audio.find((item) => item.slot === "A")?.url;
  const urlB = comparison?.audio.find((item) => item.slot === "B")?.url;
  useEffect(() => {
    deliveryRef.current = deliveryId;
    setActiveSlot("a");
    setPlaying(false);
    setPosition(0);
    setDuration(0);
    setStatus(initialStatus(deliveryId));
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
        buffersRef.current = prepareLoopBuffers(context, a, b);
        durationRef.current = buffersRef.current.a.duration;
        setDuration(durationRef.current);
        update(deliveryId, (value) => ({ ...value, loading: false }));
        // Browsers may reject this before the first user gesture; the Play button remains available.
        void playRef.current().catch(() => undefined);
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          const message = caught instanceof Error && caught.message === "比較音声を読み込めませんでした"
            ? caught.message
            : "比較音声を読み込めませんでした。画面を更新してください";
          update(deliveryId, (value) => ({ ...value, loading: false, error: message }));
        }
      });
    const tick = () => {
      if (playingRef.current) {
        const now = currentPosition();
        if (modeRef.current === "auto" && now + 0.05 < previousPositionRef.current) {
          crossfadeTo(activeSlotRef.current === "a" ? "b" : "a");
        }
        previousPositionRef.current = now;
        setPosition(now);
      }
      animationRef.current = requestAnimationFrame(tick);
    };
    animationRef.current = requestAnimationFrame(tick);
    return () => {
      cancelled = true;
      playGenerationRef.current += 1;
      if (animationRef.current !== null) cancelAnimationFrame(animationRef.current);
      stopSources();
      gainA.disconnect();
      gainB.disconnect();
      void context.close();
      contextRef.current = null;
      buffersRef.current = null;
      gainsRef.current = null;
    };
  }, [crossfadeTo, currentPosition, deliveryId, stopSources, update, urlA, urlB]);

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
