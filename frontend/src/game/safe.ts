import gsap from "gsap";
import type { Container } from "pixi.js";

/** Kill every tween on a display object (and its children / scale points) before destroying it. */
export function safeDestroy(o: Container | null | undefined): void {
  if (!o || o.destroyed) return;
  const stack: Container[] = [o];
  while (stack.length) {
    const c = stack.pop()!;
    gsap.killTweensOf(c);
    if (c.scale) gsap.killTweensOf(c.scale);
    for (const ch of c.children) stack.push(ch as Container);
  }
  o.destroy({ children: true });
}
