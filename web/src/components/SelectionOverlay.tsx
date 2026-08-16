import { useCallback, useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

export type Selection = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type Point = { x: number; y: number };

type Handle = "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";

type Interaction =
  | { type: "draw"; start: Point }
  | { type: "move"; start: Point; origin: Selection }
  | { type: "resize"; handle: Handle; start: Point; origin: Selection };

const HANDLES: Array<{ id: Handle; cursor: string; x: (s: Selection) => number; y: (s: Selection) => number }> = [
  { id: "nw", cursor: "nwse-resize", x: (s) => s.x, y: (s) => s.y },
  { id: "n", cursor: "ns-resize", x: (s) => s.x + s.width / 2, y: (s) => s.y },
  { id: "ne", cursor: "nesw-resize", x: (s) => s.x + s.width, y: (s) => s.y },
  { id: "e", cursor: "ew-resize", x: (s) => s.x + s.width, y: (s) => s.y + s.height / 2 },
  { id: "se", cursor: "nwse-resize", x: (s) => s.x + s.width, y: (s) => s.y + s.height },
  { id: "s", cursor: "ns-resize", x: (s) => s.x + s.width / 2, y: (s) => s.y + s.height },
  { id: "sw", cursor: "nesw-resize", x: (s) => s.x, y: (s) => s.y + s.height },
  { id: "w", cursor: "ew-resize", x: (s) => s.x, y: (s) => s.y + s.height / 2 },
];

export function normalizeSelection(start: Point, end: Point): Selection {
  return {
    x: Math.round(Math.min(start.x, end.x)),
    y: Math.round(Math.min(start.y, end.y)),
    width: Math.round(Math.abs(end.x - start.x)),
    height: Math.round(Math.abs(end.y - start.y)),
  };
}

export function isSelectionValid(selection: Selection | null, minEdge: number) {
  return Boolean(selection && selection.width >= minEdge && selection.height >= minEdge);
}

function clampPoint(point: Point, canvas: { width: number; height: number }): Point {
  return {
    x: Math.max(0, Math.min(canvas.width, point.x)),
    y: Math.max(0, Math.min(canvas.height, point.y)),
  };
}

function clampSelection(selection: Selection, canvas: { width: number; height: number }): Selection {
  const width = Math.min(selection.width, canvas.width);
  const height = Math.min(selection.height, canvas.height);
  return {
    width,
    height,
    x: Math.max(0, Math.min(Math.round(selection.x), canvas.width - width)),
    y: Math.max(0, Math.min(Math.round(selection.y), canvas.height - height)),
  };
}

function resizeSelection(origin: Selection, handle: Handle, from: Point, to: Point): Selection {
  let left = origin.x;
  let top = origin.y;
  let right = origin.x + origin.width;
  let bottom = origin.y + origin.height;
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  if (handle.includes("w")) left = origin.x + dx;
  if (handle.includes("e")) right = origin.x + origin.width + dx;
  if (handle.includes("n")) top = origin.y + dy;
  if (handle.includes("s")) bottom = origin.y + origin.height + dy;
  return normalizeSelection({ x: left, y: top }, { x: right, y: bottom });
}

function contains(selection: Selection, point: Point) {
  return (
    point.x >= selection.x &&
    point.x <= selection.x + selection.width &&
    point.y >= selection.y &&
    point.y <= selection.y + selection.height
  );
}

function hitTest(point: Point, selection: Selection | null, handleHit: number, minEdge: number): Handle | "move" | "draw" {
  if (selection && isSelectionValid(selection, minEdge)) {
    const slop = handleHit * 0.9;
    for (const handle of HANDLES) {
      if (Math.hypot(point.x - handle.x(selection), point.y - handle.y(selection)) <= slop) {
        return handle.id;
      }
    }
    if (contains(selection, point)) return "move";
  }
  return "draw";
}

type SelectionOverlayProps = {
  canvasSize: { width: number; height: number };
  selection: Selection | null;
  minEdge: number;
  disabled?: boolean;
  onChange: (selection: Selection | null) => void;
  onCommit?: () => void;
};

export function SelectionOverlay({
  canvasSize,
  selection,
  minEdge,
  disabled = false,
  onChange,
  onCommit,
}: SelectionOverlayProps) {
  const overlayRef = useRef<SVGSVGElement>(null);
  const interactionRef = useRef<Interaction | null>(null);
  const [cssScale, setCssScale] = useState(1);
  const [cursor, setCursor] = useState("crosshair");

  useEffect(() => {
    const node = overlayRef.current;
    if (!node || !canvasSize.width) return;
    const sync = () => {
      const width = node.getBoundingClientRect().width;
      if (width > 0) setCssScale(width / canvasSize.width);
    };
    sync();
    const observer = new ResizeObserver(sync);
    observer.observe(node);
    return () => observer.disconnect();
  }, [canvasSize.width]);

  const pointFromEvent = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>) => {
      const bounds = overlayRef.current?.getBoundingClientRect();
      if (!bounds || !canvasSize.width || !canvasSize.height) return null;
      return clampPoint(
        {
          x: ((event.clientX - bounds.left) / bounds.width) * canvasSize.width,
          y: ((event.clientY - bounds.top) / bounds.height) * canvasSize.height,
        },
        canvasSize,
      );
    },
    [canvasSize],
  );

  const updateCursor = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (disabled || interactionRef.current) return;
    const point = pointFromEvent(event);
    if (!point) return;
    const hit = hitTest(point, selection, 14 / cssScale, minEdge);
    if (hit === "draw") setCursor("crosshair");
    else if (hit === "move") setCursor("move");
    else setCursor(HANDLES.find((handle) => handle.id === hit)?.cursor ?? "crosshair");
  };

  const start = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (disabled || event.button !== 0) return;
    const point = pointFromEvent(event);
    if (!point) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const hit = hitTest(point, selection, 14 / cssScale, minEdge);
    if (hit === "draw") {
      interactionRef.current = { type: "draw", start: point };
      onChange({ x: Math.round(point.x), y: Math.round(point.y), width: 0, height: 0 });
      setCursor("crosshair");
      return;
    }
    if (!selection) return;
    if (hit === "move") {
      interactionRef.current = { type: "move", start: point, origin: selection };
      setCursor("move");
      return;
    }
    interactionRef.current = { type: "resize", handle: hit, start: point, origin: selection };
    setCursor(HANDLES.find((handle) => handle.id === hit)?.cursor ?? "crosshair");
  };

  const move = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!interactionRef.current) {
      updateCursor(event);
      return;
    }
    const point = pointFromEvent(event);
    const interaction = interactionRef.current;
    if (!point) return;
    if (interaction.type === "draw") {
      onChange(normalizeSelection(interaction.start, point));
      return;
    }
    if (interaction.type === "move") {
      onChange(
        clampSelection(
          {
            ...interaction.origin,
            x: interaction.origin.x + (point.x - interaction.start.x),
            y: interaction.origin.y + (point.y - interaction.start.y),
          },
          canvasSize,
        ),
      );
      return;
    }
    onChange(clampSelection(resizeSelection(interaction.origin, interaction.handle, interaction.start, point), canvasSize));
  };

  const finish = (event: ReactPointerEvent<SVGSVGElement>) => {
    const point = pointFromEvent(event);
    const interaction = interactionRef.current;
    interactionRef.current = null;
    if (!point || !interaction) return;
    if (interaction.type === "draw") {
      const next = normalizeSelection(interaction.start, point);
      onChange(isSelectionValid(next, minEdge) ? next : null);
    }
  };

  const valid = isSelectionValid(selection, minEdge);
  const handleSize = 8 / cssScale;
  const stroke = 2 / cssScale;

  return (
    <svg
      ref={overlayRef}
      viewBox={`0 0 ${canvasSize.width} ${canvasSize.height}`}
      className="absolute inset-0 h-full w-full touch-none"
      style={{ cursor }}
      onPointerDown={start}
      onPointerMove={move}
      onPointerUp={finish}
      onPointerCancel={finish}
      onDoubleClick={() => {
        if (valid) onCommit?.();
      }}
    >
      {valid && selection && (
        <path
          d={`M0 0H${canvasSize.width}V${canvasSize.height}H0Z M${selection.x} ${selection.y}H${selection.x + selection.width}V${selection.y + selection.height}H${selection.x}Z`}
          fill="rgba(24, 24, 27, 0.42)"
          fillRule="evenodd"
          pointerEvents="none"
        />
      )}
      {selection && selection.width > 0 && selection.height > 0 && (
        <rect
          x={selection.x}
          y={selection.y}
          width={selection.width}
          height={selection.height}
          fill="none"
          stroke="#0284c7"
          strokeWidth={stroke}
          vectorEffect="non-scaling-stroke"
          pointerEvents="none"
        />
      )}
      {valid && selection &&
        HANDLES.map((handle) => (
          <rect
            key={handle.id}
            x={handle.x(selection) - handleSize / 2}
            y={handle.y(selection) - handleSize / 2}
            width={handleSize}
            height={handleSize}
            fill="#fff"
            stroke="#0284c7"
            strokeWidth={stroke}
            vectorEffect="non-scaling-stroke"
            pointerEvents="none"
          />
        ))}
    </svg>
  );
}
