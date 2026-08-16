import {
  ChevronLeft,
  ChevronRight,
  Clipboard,
  ClipboardCheck,
  FileUp,
  LoaderCircle,
  ScanText,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ChangeEvent, DragEvent, PointerEvent as ReactPointerEvent } from "react";
import type { PDFDocumentProxy } from "pdfjs-dist";

import { SelectionOverlay, isSelectionValid, type Selection } from "@/components/SelectionOverlay";
import { Button } from "@/components/ui/button";
import { detectLocale, translations, type Locale, type Translation } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type SourceKind = "pdf" | "image" | null;
type RasterSource = ImageBitmap | HTMLImageElement;

type OcrBlock = {
  label?: string;
  content?: string;
};

type OcrResponse = {
  request_id: string;
  text: string;
  markdown: string;
  blocks?: OcrBlock[];
  elapsed_ms: number;
  image: { width: number; height: number };
};

type ResultItem = OcrResponse & { previewUrl: string };

const MAX_UPLOAD_EDGE = 2_048;
const MAX_RENDER_EDGE = 3_500;
const MIN_SELECTION_EDGE = 12;
const MAX_HISTORY = 8;
const INSPECTOR_WIDTH_KEY = "crop-ocr-inspector-width";
const INSPECTOR_MIN = 260;
const INSPECTOR_MAX = 640;
const INSPECTOR_DEFAULT = 320;
const OCR_ENDPOINT = import.meta.env.PUBLIC_OCR_ENDPOINT || "/api/ocr";

function clampInspectorWidth(width: number, containerWidth = 0) {
  const maxByContainer = containerWidth > 0 ? Math.floor(containerWidth * 0.55) : INSPECTOR_MAX;
  return Math.max(INSPECTOR_MIN, Math.min(INSPECTOR_MAX, maxByContainer, Math.round(width)));
}

function isPdfFile(file: File) {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

function isImageFile(file: File) {
  return file.type.startsWith("image/") || /\.(avif|bmp|gif|jpe?g|png|webp)$/i.test(file.name);
}

async function decodeImage(file: File): Promise<RasterSource> {
  if ("createImageBitmap" in window) return createImageBitmap(file);

  const objectUrl = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = objectUrl;
    await image.decode();
    return image;
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

function dimensionsOf(source: RasterSource) {
  return isImageBitmap(source)
    ? { width: source.width, height: source.height }
    : { width: source.naturalWidth, height: source.naturalHeight };
}

function closeRasterSource(source: RasterSource | null) {
  if (isImageBitmap(source)) source.close();
}

function isImageBitmap(source: RasterSource | null): source is ImageBitmap {
  return typeof ImageBitmap !== "undefined" && source instanceof ImageBitmap;
}

function cropToJpeg(source: HTMLCanvasElement, selection: Selection, messages: Translation): Promise<Blob> {
  const longestEdge = Math.max(selection.width, selection.height);
  const scale = longestEdge > MAX_UPLOAD_EDGE ? MAX_UPLOAD_EDGE / longestEdge : 1;
  const target = document.createElement("canvas");
  target.width = Math.max(1, Math.round(selection.width * scale));
  target.height = Math.max(1, Math.round(selection.height * scale));

  const context = target.getContext("2d");
  if (!context) return Promise.reject(new Error(messages.cropCanvasFailed));
  context.drawImage(
    source,
    selection.x,
    selection.y,
    selection.width,
    selection.height,
    0,
    0,
    target.width,
    target.height,
  );

  return new Promise((resolve, reject) => {
    target.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error(messages.cropEncodeFailed))),
      "image/jpeg",
      0.92,
    );
  });
}

function splitLines(value: string): string[] {
  return value
    .split(/\r?\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function resultLines(result: ResultItem): string[] {
  const fromBlocks = result.blocks?.flatMap((block) => splitLines(block.content ?? "")) ?? [];
  if (fromBlocks.length > 0) return fromBlocks;
  return splitLines(result.text || result.markdown);
}

function getRequestId() {
  return typeof crypto.randomUUID === "function"
    ? crypto.randomUUID().replaceAll("-", "")
    : `${Date.now()}${Math.random().toString(16).slice(2)}`;
}

export function OcrWorkspace() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const workspaceRef = useRef<HTMLDivElement>(null);
  const inspectorWidthRef = useRef(INSPECTOR_DEFAULT);
  const inspectorDragRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const dragDepthRef = useRef(0);
  const [locale, setLocale] = useState<Locale>("zh");
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [rasterImage, setRasterImage] = useState<RasterSource | null>(null);
  const [sourceKind, setSourceKind] = useState<SourceKind>(null);
  const [fileName, setFileName] = useState("");
  const [pageNumber, setPageNumber] = useState(1);
  const [pageCount, setPageCount] = useState(0);
  const [canvasSize, setCanvasSize] = useState({ width: 0, height: 0 });
  const [selection, setSelection] = useState<Selection | null>(null);
  const [isRendering, setIsRendering] = useState(false);
  const [isRecognizing, setIsRecognizing] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<ResultItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [inspectorWidth, setInspectorWidth] = useState(INSPECTOR_DEFAULT);
  const [isResizingInspector, setIsResizingInspector] = useState(false);
  inspectorWidthRef.current = inspectorWidth;
  const t = translations[locale];
  const hasSource = Boolean(pdf || rasterImage);
  const activeResult = results.find((item) => item.request_id === activeId) ?? results[0] ?? null;
  const selectionIsValid = isSelectionValid(selection, MIN_SELECTION_EDGE);
  const willDownscale = Boolean(
    selectionIsValid && selection && Math.max(selection.width, selection.height) > MAX_UPLOAD_EDGE,
  );

  useEffect(() => {
    setLocale(detectLocale());
    const saved = Number(window.localStorage.getItem(INSPECTOR_WIDTH_KEY));
    if (Number.isFinite(saved) && saved >= INSPECTOR_MIN && saved <= INSPECTOR_MAX) {
      setInspectorWidth(saved);
    }
  }, []);

  useEffect(() => {
    if (!isResizingInspector) return;
    const previousCursor = document.body.style.cursor;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    return () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = "";
    };
  }, [isResizingInspector]);

  useEffect(() => {
    document.documentElement.lang = t.locale;
    document.title = t.title;
    document.querySelector('meta[name="description"]')?.setAttribute("content", t.metaDescription);
  }, [t]);

  useEffect(() => {
    return () => {
      void pdf?.destroy();
    };
  }, [pdf]);

  useEffect(() => {
    return () => closeRasterSource(rasterImage);
  }, [rasterImage]);

  useEffect(() => {
    return () => {
      for (const item of results) URL.revokeObjectURL(item.previewUrl);
    };
    // Revoke leftovers only when the workspace unmounts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!pdf || !canvasRef.current) return;

    let cancelled = false;
    let renderTask: { cancel: () => void } | undefined;
    const canvas = canvasRef.current;

    const render = async () => {
      setIsRendering(true);
      setError(null);
      setSelection(null);
      try {
        const page = await pdf.getPage(pageNumber);
        const baseViewport = page.getViewport({ scale: 1 });
        const renderScale = Math.min(2, Math.max(1.25, 1_600 / baseViewport.width));
        const viewport = page.getViewport({ scale: renderScale });
        canvas.width = Math.round(viewport.width);
        canvas.height = Math.round(viewport.height);
        if (!canvas.getContext("2d", { alpha: false })) throw new Error(t.couldNotRender);

        const task = page.render({ canvas, viewport });
        renderTask = task;
        await task.promise;
        if (!cancelled) setCanvasSize({ width: canvas.width, height: canvas.height });
      } catch (renderError) {
        if (!cancelled) setError(renderError instanceof Error ? renderError.message : t.couldNotRender);
      } finally {
        if (!cancelled) setIsRendering(false);
      }
    };

    void render();
    return () => {
      cancelled = true;
      renderTask?.cancel();
    };
  }, [pageNumber, pdf, t.couldNotRender]);

  useEffect(() => {
    if (!rasterImage || !canvasRef.current) return;

    let cancelled = false;
    const canvas = canvasRef.current;
    const render = () => {
      setIsRendering(true);
      setError(null);
      setSelection(null);
      try {
        const sourceSize = dimensionsOf(rasterImage);
        if (!sourceSize.width || !sourceSize.height) throw new Error(t.couldNotOpenImage);
        const scale = Math.min(1, MAX_RENDER_EDGE / Math.max(sourceSize.width, sourceSize.height));
        canvas.width = Math.max(1, Math.round(sourceSize.width * scale));
        canvas.height = Math.max(1, Math.round(sourceSize.height * scale));
        const context = canvas.getContext("2d", { alpha: false });
        if (!context) throw new Error(t.couldNotRender);
        context.drawImage(rasterImage, 0, 0, canvas.width, canvas.height);
        if (!cancelled) setCanvasSize({ width: canvas.width, height: canvas.height });
      } catch (renderError) {
        if (!cancelled) setError(renderError instanceof Error ? renderError.message : t.couldNotRender);
      } finally {
        if (!cancelled) setIsRendering(false);
      }
    };

    render();
    return () => {
      cancelled = true;
    };
  }, [rasterImage, t.couldNotOpenImage, t.couldNotRender]);

  const openFile = useCallback(
    async (file: File) => {
      const isPdf = isPdfFile(file);
      const isImage = !isPdf && isImageFile(file);
      if (!isPdf && !isImage) {
        setError(t.invalidFile);
        return;
      }

      setError(null);
      setSelection(null);
      setCanvasSize({ width: 0, height: 0 });
      try {
        if (isPdf) {
          const pdfjs = await import("pdfjs-dist");
          pdfjs.GlobalWorkerOptions.workerSrc = new URL(
            "pdfjs-dist/build/pdf.worker.min.mjs",
            import.meta.url,
          ).toString();
          const bytes = new Uint8Array(await file.arrayBuffer());
          const document = await pdfjs.getDocument({ data: bytes }).promise;
          setRasterImage(null);
          setPdf(document);
          setSourceKind("pdf");
          setFileName(file.name);
          setPageCount(document.numPages);
          setPageNumber(1);
          return;
        }

        const image = await decodeImage(file);
        setPdf(null);
        setRasterImage(image);
        setSourceKind("image");
        setFileName(file.name);
        setPageCount(0);
        setPageNumber(1);
      } catch (loadError) {
        setPdf(null);
        setRasterImage(null);
        setSourceKind(null);
        setFileName("");
        setPageCount(0);
        setError(loadError instanceof Error ? loadError.message : isPdf ? t.couldNotOpenPdf : t.couldNotOpenImage);
      }
    },
    [t.couldNotOpenImage, t.couldNotOpenPdf, t.invalidFile],
  );

  const onFileInput = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) void openFile(file);
  };

  const onDragEnter = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragDepthRef.current += 1;
    if (event.dataTransfer.types.includes("Files")) setDragOver(true);
  };

  const onDragLeave = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) setDragOver(false);
  };

  const onDragOver = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragDepthRef.current = 0;
    setDragOver(false);
    const file = event.dataTransfer.files[0];
    if (file) void openFile(file);
  };

  useEffect(() => {
    const onPaste = (event: ClipboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "TEXTAREA" || target.tagName === "INPUT" || target.isContentEditable)) return;
      const items = event.clipboardData?.items;
      if (!items) return;
      for (const item of items) {
        if (item.kind === "file") {
          const file = item.getAsFile();
          if (file) {
            event.preventDefault();
            void openFile(file);
            return;
          }
        }
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [openFile]);

  const recognizeRegion = useCallback(async (region: Selection) => {
    const source = canvasRef.current;
    if (!source) return;

    setIsRecognizing(true);
    setError(null);
    try {
      const crop = await cropToJpeg(source, region, t);
      const requestId = getRequestId();
      const previewUrl = URL.createObjectURL(crop);
      const response = await fetch(OCR_ENDPOINT, {
        method: "POST",
        headers: {
          "Content-Type": crop.type,
          "X-Request-Id": requestId,
        },
        body: crop,
      });
      const body = (await response.json()) as OcrResponse | { detail?: string };
      if (!response.ok) {
        URL.revokeObjectURL(previewUrl);
        throw new Error("detail" in body ? body.detail || t.requestFailed : t.requestFailed);
      }
      const item: ResultItem = { ...(body as OcrResponse), previewUrl };
      setResults((previous) => {
        const next = [item, ...previous].slice(0, MAX_HISTORY);
        for (const old of previous) {
          if (!next.includes(old)) URL.revokeObjectURL(old.previewUrl);
        }
        return next;
      });
      setActiveId(item.request_id);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t.requestFailed);
    } finally {
      setIsRecognizing(false);
    }
  }, [t]);

  const recognizeSelection = () => {
    if (selectionIsValid && selection) void recognizeRegion(selection);
  };

  const recognizeWholeSource = () => {
    if (!canvasSize.width || !canvasSize.height) return;
    const fullSelection = { x: 0, y: 0, width: canvasSize.width, height: canvasSize.height };
    setSelection(fullSelection);
    void recognizeRegion(fullSelection);
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "TEXTAREA" || target.tagName === "INPUT" || target.isContentEditable)) return;
      if (event.key === "Escape") {
        setSelection(null);
        return;
      }
      if (
        event.key === "Enter" &&
        selection &&
        isSelectionValid(selection, MIN_SELECTION_EDGE) &&
        !isRecognizing &&
        !isRendering
      ) {
        event.preventDefault();
        void recognizeRegion(selection);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isRecognizing, isRendering, recognizeRegion, selection]);

  const copyText = async (value: string, key: string) => {
    if (!value) return;
    await navigator.clipboard.writeText(value);
    setCopiedKey(key);
    window.setTimeout(() => {
      setCopiedKey((current) => (current === key ? null : current));
    }, 1600);
  };

  const persistLocale = (next: Locale) => {
    window.localStorage.setItem("crop-ocr-locale", next);
    setLocale(next);
  };

  const persistInspectorWidth = (width: number) => {
    window.localStorage.setItem(INSPECTOR_WIDTH_KEY, String(width));
  };

  const startInspectorResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    inspectorDragRef.current = { startX: event.clientX, startWidth: inspectorWidthRef.current };
    setIsResizingInspector(true);
  };

  const moveInspectorResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = inspectorDragRef.current;
    if (!drag) return;
    const containerWidth = workspaceRef.current?.getBoundingClientRect().width ?? 0;
    const next = clampInspectorWidth(drag.startWidth + (drag.startX - event.clientX), containerWidth);
    setInspectorWidth(next);
  };

  const stopInspectorResize = () => {
    if (!inspectorDragRef.current) return;
    inspectorDragRef.current = null;
    setIsResizingInspector(false);
    persistInspectorWidth(inspectorWidthRef.current);
  };

  const resetInspectorWidth = () => {
    setInspectorWidth(INSPECTOR_DEFAULT);
    persistInspectorWidth(INSPECTOR_DEFAULT);
  };

  const nudgeInspectorWidth = (delta: number) => {
    const containerWidth = workspaceRef.current?.getBoundingClientRect().width ?? 0;
    const next = clampInspectorWidth(inspectorWidthRef.current + delta, containerWidth);
    setInspectorWidth(next);
    persistInspectorWidth(next);
  };

  const toolbarPos = selectionIsValid && selection && canvasSize.height
    ? selection.y + selection.height > canvasSize.height * 0.82
      ? { left: `${(selection.x / canvasSize.width) * 100}%`, bottom: `${(1 - selection.y / canvasSize.height) * 100}%`, transform: "translateY(-8px)" }
      : { left: `${(selection.x / canvasSize.width) * 100}%`, top: `${((selection.y + selection.height) / canvasSize.height) * 100}%`, transform: "translateY(8px)" }
    : null;

  return (
    <div
      className="relative flex h-dvh flex-col bg-[#e6e8ec] text-zinc-900"
      onDragEnter={onDragEnter}
      onDragLeave={onDragLeave}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      <input
        ref={fileInputRef}
        className="sr-only"
        type="file"
        accept="application/pdf,.pdf,image/*"
        onChange={onFileInput}
      />

      <header className="shrink-0 border-b border-zinc-200 bg-white px-3 py-2 sm:px-4">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-2">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <p className="shrink-0 text-sm font-semibold tracking-tight">{t.heading}</p>
            <div className="flex items-center rounded-md bg-zinc-100 p-0.5 text-[11px] font-medium leading-none text-zinc-500">
              <button
                type="button"
                className={cn(
                  "rounded px-1.5 py-1 transition-colors",
                  locale === "zh" && "bg-white text-zinc-900 shadow-sm",
                )}
                onClick={() => persistLocale("zh")}
                aria-label="中文"
                aria-pressed={locale === "zh"}
              >
                中
              </button>
              <button
                type="button"
                className={cn(
                  "rounded px-1.5 py-1 transition-colors",
                  locale === "en" && "bg-white text-zinc-900 shadow-sm",
                )}
                onClick={() => persistLocale("en")}
                aria-label="English"
                aria-pressed={locale === "en"}
              >
                EN
              </button>
            </div>
            {hasSource && (
              <>
                <p className="hidden min-w-0 truncate text-sm text-zinc-500 md:block" title={fileName}>
                  {fileName}
                </p>
                {pdf && (
                  <div className="flex items-center gap-0.5">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setPageNumber((value) => Math.max(1, value - 1))}
                      disabled={pageNumber <= 1 || isRendering}
                      aria-label={t.previousPage}
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <span className="min-w-10 text-center text-xs tabular-nums text-zinc-600">
                      {pageNumber}/{pageCount}
                    </span>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setPageNumber((value) => Math.min(pageCount, value + 1))}
                      disabled={pageNumber >= pageCount || isRendering}
                      aria-label={t.nextPage}
                    >
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                )}
              </>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            <Button size="sm" variant="outline" onClick={() => fileInputRef.current?.click()}>
              <FileUp className="h-4 w-4" />
              {t.openFile}
            </Button>
            {hasSource && (
              <Button
                size="sm"
                variant="ghost"
                onClick={recognizeWholeSource}
                disabled={isRendering || isRecognizing}
              >
                {sourceKind === "image" ? t.recognizeWholeImage : t.recognizeWholePage}
              </Button>
            )}
            {selectionIsValid && (
              <Button
                size="sm"
                className="hidden md:inline-flex"
                onClick={recognizeSelection}
                disabled={isRecognizing || isRendering}
              >
                {isRecognizing ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <ScanText className="h-4 w-4" />}
                {isRecognizing ? t.recognizing : t.recognizeSelection}
              </Button>
            )}
          </div>
        </div>
      </header>

      {error && (
        <p role="alert" className="shrink-0 border-b border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">
          {error}
        </p>
      )}

      {hasSource ? (
        <div
          ref={workspaceRef}
          className={cn("flex min-h-0 flex-1 flex-col lg:flex-row", isResizingInspector && "select-none")}
        >
          <section className="relative flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="min-h-0 flex-1 overflow-auto">
              <div className="flex min-h-full items-start justify-center p-4 sm:p-6">
                <div className="relative w-fit shadow-[0_18px_50px_-24px_rgba(24,24,27,0.45)]">
                  <canvas ref={canvasRef} className="block max-w-full bg-white" />
                  {canvasSize.width > 0 && (
                    <SelectionOverlay
                      canvasSize={canvasSize}
                      selection={selection}
                      minEdge={MIN_SELECTION_EDGE}
                      disabled={isRendering || isRecognizing}
                      onChange={setSelection}
                      onCommit={recognizeSelection}
                    />
                  )}
                  {toolbarPos && selection && (
                    <div className="absolute z-10 hidden items-center gap-1 lg:flex" style={toolbarPos}>
                      <div className="flex items-center gap-1 rounded-lg border border-zinc-200 bg-white p-1 shadow-lg">
                        <Button size="sm" onClick={recognizeSelection} disabled={isRecognizing}>
                          {isRecognizing ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <ScanText className="h-3.5 w-3.5" />}
                          {isRecognizing ? t.recognizing : t.recognizeSelection}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setSelection(null)}>
                          {t.clearSelection}
                        </Button>
                      </div>
                    </div>
                  )}
                  {(isRendering || isRecognizing) && (
                    <div className="absolute inset-0 grid place-items-center bg-white/50 text-sm text-zinc-700">
                      <span className="flex items-center gap-2 rounded-full bg-white px-3 py-1.5 shadow">
                        <LoaderCircle className="h-4 w-4 animate-spin" />
                        {isRecognizing ? t.recognizing : t.rendering}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            </div>
            {selectionIsValid && (
              <div className="flex shrink-0 items-center justify-center gap-2 border-t border-zinc-200 bg-white px-3 py-2 lg:hidden">
                <Button size="sm" className="flex-1 max-w-40" onClick={recognizeSelection} disabled={isRecognizing}>
                  {isRecognizing ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <ScanText className="h-3.5 w-3.5" />}
                  {isRecognizing ? t.recognizing : t.recognizeSelection}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setSelection(null)}>
                  {t.clearSelection}
                </Button>
              </div>
            )}
          </section>

          <div
            role="separator"
            aria-orientation="vertical"
            aria-label={t.resizeInspector}
            aria-valuenow={inspectorWidth}
            aria-valuemin={INSPECTOR_MIN}
            aria-valuemax={INSPECTOR_MAX}
            tabIndex={0}
            className={cn(
              "relative hidden w-1.5 shrink-0 cursor-col-resize touch-none items-stretch justify-center lg:flex",
              "before:absolute before:inset-y-0 before:-left-1.5 before:-right-1.5 before:content-['']",
              isResizingInspector ? "bg-sky-300" : "bg-transparent hover:bg-sky-200/80",
            )}
            onPointerDown={startInspectorResize}
            onPointerMove={moveInspectorResize}
            onPointerUp={stopInspectorResize}
            onPointerCancel={stopInspectorResize}
            onDoubleClick={resetInspectorWidth}
            onKeyDown={(event) => {
              if (event.key === "ArrowLeft") {
                event.preventDefault();
                nudgeInspectorWidth(16);
              } else if (event.key === "ArrowRight") {
                event.preventDefault();
                nudgeInspectorWidth(-16);
              } else if (event.key === "Home") {
                event.preventDefault();
                resetInspectorWidth();
              }
            }}
          >
            <span className="my-auto h-8 w-0.5 rounded-full bg-zinc-300" />
          </div>
          <aside
            className="flex max-h-[42vh] w-full shrink-0 flex-col overflow-hidden border-t border-zinc-200 bg-white lg:max-h-none lg:w-[var(--inspector-width)] lg:border-t-0"
            style={{ ["--inspector-width" as string]: `${inspectorWidth}px` }}
          >
            <div className="border-b border-zinc-100 px-4 py-3">
              <p className="text-xs font-medium uppercase tracking-wide text-zinc-400">{t.selectionSize}</p>
              {selectionIsValid && selection ? (
                <>
                  <CropPreview canvas={canvasRef.current} selection={selection} />
                  <p className="mt-2 text-sm tabular-nums text-zinc-600">
                    {selection.width} × {selection.height}px
                  </p>
                  <p className="mt-1 text-xs leading-5 text-zinc-400">{t.dragToAdjust}</p>
                  {willDownscale && <p className="mt-2 text-xs leading-5 text-amber-700">{t.uploadLimitHint}</p>}
                </>
              ) : (
                <p className="mt-1 text-sm leading-6 text-zinc-500">{t.noSelectionPreview}</p>
              )}
            </div>

            <div className="flex min-h-0 flex-1 flex-col">
              <div className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wide text-zinc-400">{t.resultTitle}</p>
                  {activeResult && (
                    <p className="mt-0.5 text-xs tabular-nums text-zinc-400">
                      {activeResult.image.width} × {activeResult.image.height}px · {(activeResult.elapsed_ms / 1000).toFixed(1)} {t.seconds}
                    </p>
                  )}
                </div>
                {activeResult && resultLines(activeResult).length > 1 && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void copyText(activeResult.text || activeResult.markdown, `${activeResult.request_id}:all`)}
                  >
                    {copiedKey === `${activeResult.request_id}:all` ? (
                      <ClipboardCheck className="h-4 w-4" />
                    ) : (
                      <Clipboard className="h-4 w-4" />
                    )}
                    {copiedKey === `${activeResult.request_id}:all` ? t.copied : t.copyAll}
                  </Button>
                )}
              </div>
              {activeResult ? (
                <ul className="min-h-40 flex-1 space-y-0.5 overflow-auto px-2 pb-3" aria-label={t.resultLabel}>
                  {resultLines(activeResult).map((line, index) => {
                    const key = `${activeResult.request_id}:${index}`;
                    const isCopied = copiedKey === key;
                    return (
                      <li key={key} className="group flex items-start gap-1 rounded-md px-2 py-1.5 hover:bg-zinc-50">
                        <p className="min-w-0 flex-1 whitespace-pre-wrap text-sm leading-6 text-zinc-800">{line}</p>
                        <button
                          type="button"
                          className="mt-0.5 shrink-0 rounded p-1 text-zinc-300 transition-colors hover:bg-zinc-100 hover:text-zinc-700"
                          onClick={() => void copyText(line, key)}
                          aria-label={t.copyLine}
                          title={isCopied ? t.copied : t.copyLine}
                        >
                          {isCopied ? <ClipboardCheck className="h-3.5 w-3.5 text-zinc-700" /> : <Clipboard className="h-3.5 w-3.5" />}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="px-4 pb-3 text-sm leading-6 text-zinc-400">{t.resultPlaceholder}</p>
              )}

              {results.length > 1 && (
                <div className="border-t border-zinc-100 px-3 py-2">
                  <p className="px-1 pb-2 text-xs font-medium uppercase tracking-wide text-zinc-400">{t.historyTitle}</p>
                  <ul className="space-y-1">
                    {results.map((item) => (
                      <li key={item.request_id}>
                        <button
                          type="button"
                          onClick={() => setActiveId(item.request_id)}
                          className={cn(
                            "flex w-full items-center gap-2 rounded-md px-1 py-1 text-left hover:bg-zinc-50",
                            item.request_id === activeResult?.request_id && "bg-zinc-100",
                          )}
                        >
                          <img src={item.previewUrl} alt="" className="h-8 w-10 shrink-0 rounded object-cover ring-1 ring-zinc-200" />
                          <span className="min-w-0 flex-1 truncate text-xs text-zinc-600">
                            {item.text || item.markdown || "—"}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </aside>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 items-center justify-center p-6">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex w-full max-w-lg flex-col items-center rounded-2xl border border-dashed border-zinc-300 bg-white/80 px-8 py-16 text-center transition-colors hover:border-zinc-400 hover:bg-white"
          >
            <FileUp className="h-8 w-8 text-zinc-400" />
            <p className="mt-4 text-base font-medium text-zinc-900">{t.dropToOpen}</p>
            <p className="mt-2 text-sm text-zinc-500">{t.orClickToBrowse}</p>
            <p className="mt-6 text-xs text-zinc-400">{t.pasteHint}</p>
            <p className="mt-1 text-xs text-zinc-400">{t.privacyTag}</p>
          </button>
        </div>
      )}

      {dragOver && (
        <div className="pointer-events-none absolute inset-0 z-20 grid place-items-center bg-zinc-900/30">
          <p className="rounded-xl bg-white px-5 py-3 text-sm font-medium shadow-xl">{t.dropRelease}</p>
        </div>
      )}
    </div>
  );
}

function CropPreview({ canvas, selection }: { canvas: HTMLCanvasElement | null; selection: Selection }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!canvas || !ref.current || selection.width < 1 || selection.height < 1) return;
    const maxWidth = 288;
    const scale = Math.min(1, maxWidth / selection.width);
    const width = Math.max(1, Math.round(selection.width * scale));
    const height = Math.max(1, Math.round(selection.height * scale));
    ref.current.width = width;
    ref.current.height = height;
    const context = ref.current.getContext("2d");
    if (!context) return;
    context.drawImage(
      canvas,
      selection.x,
      selection.y,
      selection.width,
      selection.height,
      0,
      0,
      width,
      height,
    );
  }, [canvas, selection]);

  return <canvas ref={ref} className="mt-3 max-w-full rounded-md bg-zinc-100 ring-1 ring-zinc-200" />;
}
