interface Env {
  OCR_API_ORIGIN: string;
  CF_ACCESS_CLIENT_ID: string;
  CF_ACCESS_CLIENT_SECRET: string;
  OCR_MAX_IMAGE_BYTES?: string;
}

type FunctionContext = {
  request: Request;
  env: Env;
};

const DEFAULT_MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const ALLOWED_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

function noStoreJson(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

export const onRequestPost = async ({ request, env }: FunctionContext): Promise<Response> => {
  const type = request.headers.get("content-type")?.split(";", 1)[0].toLowerCase();
  if (!type || !ALLOWED_IMAGE_TYPES.has(type)) {
    return noStoreJson({ detail: "Send a JPEG, PNG, or WebP crop as the request body." }, 415);
  }

  const maxBytes = Number(env.OCR_MAX_IMAGE_BYTES || DEFAULT_MAX_IMAGE_BYTES);
  const contentLength = request.headers.get("content-length");
  if (contentLength && Number(contentLength) > maxBytes) {
    return noStoreJson({ detail: "Crop image exceeds the request size limit." }, 413);
  }

  if (!env.OCR_API_ORIGIN || !env.CF_ACCESS_CLIENT_ID || !env.CF_ACCESS_CLIENT_SECRET) {
    return noStoreJson({ detail: "OCR relay is not configured." }, 503);
  }

  const target = new URL("/v1/ocr", env.OCR_API_ORIGIN);
  const headers = new Headers({
    "Content-Type": type,
    "CF-Access-Client-Id": env.CF_ACCESS_CLIENT_ID,
    "CF-Access-Client-Secret": env.CF_ACCESS_CLIENT_SECRET,
  });
  const requestId = request.headers.get("x-request-id");
  if (requestId) headers.set("X-Request-Id", requestId);

  try {
    // Do not read arrayBuffer()/formData() here. Passing the stream preserves the
    // crop-only boundary and avoids writing or buffering a second copy in the Function.
    const upstream = await fetch(target, {
      method: "POST",
      headers,
      body: request.body,
      redirect: "manual",
    });
    const responseHeaders = new Headers(upstream.headers);
    responseHeaders.delete("set-cookie");
    responseHeaders.set("Cache-Control", "no-store");
    responseHeaders.set("X-Content-Type-Options", "nosniff");
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  } catch {
    return noStoreJson({ detail: "Could not reach the local OCR service." }, 502);
  }
};
