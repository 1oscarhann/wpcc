import { useEffect, useRef, useState } from "react";
import { manifest } from "../../assets/manifest";

interface Frame {
  frame: { x: number; y: number; w: number; h: number };
}

let atlasPromise: Promise<{ img: HTMLImageElement; frames: Record<string, Frame> }> | null = null;

export function loadAtlasForDom() {
  if (!atlasPromise) {
    atlasPromise = (async () => {
      const json = await (await fetch(manifest.atlases.world)).json();
      const img = new Image();
      img.src = manifest.atlases.world.replace(/[^/]+$/, json.meta.image);
      await img.decode();
      return { img, frames: json.frames as Record<string, Frame> };
    })();
  }
  return atlasPromise;
}

/** A world sprite drawn into a DOM canvas at an integer scale, fitted into a box. */
export function SpriteThumb({ name, box = 64, maxScale = 2, dim = false }: {
  name: string;
  box?: number;
  maxScale?: number;
  dim?: boolean;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let alive = true;
    loadAtlasForDom().then(({ img, frames }) => {
      const f = frames[name]?.frame;
      const c = ref.current;
      if (!alive || !f || !c) return;
      const scale = Math.max(1, Math.min(maxScale, Math.floor(box / Math.max(f.w, f.h))));
      c.width = box;
      c.height = box;
      const ctx = c.getContext("2d")!;
      ctx.imageSmoothingEnabled = false;
      ctx.clearRect(0, 0, box, box);
      ctx.globalAlpha = dim ? 0.45 : 1;
      ctx.drawImage(img, f.x, f.y, f.w, f.h, Math.floor((box - f.w * scale) / 2), box - f.h * scale, f.w * scale, f.h * scale);
      setReady(true);
    });
    return () => {
      alive = false;
    };
  }, [name, box, maxScale, dim]);
  return <canvas ref={ref} width={box} height={box} className="pixel" style={{ opacity: ready ? 1 : 0 }} aria-hidden />;
}
