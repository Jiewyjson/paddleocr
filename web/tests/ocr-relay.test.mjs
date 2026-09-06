import assert from 'node:assert/strict';
import { test } from 'node:test';
import { onRequestPost } from '../functions/api/ocr.ts';

const env = { OCR_API_ORIGIN: 'https://ocr.example', CF_ACCESS_CLIENT_ID: 'test-id', CF_ACCESS_CLIENT_SECRET: 'test-secret' };
test('relay forwards only a validated strategy, preserving image body', async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async (target, options) => {
    calls++;
    assert.equal(target.origin, env.OCR_API_ORIGIN);
    assert.equal(target.pathname, '/v1/ocr');
    assert.equal(target.searchParams.has('unrelated'), false);
    assert.equal(await new Response(options.body).text(), 'image-bytes');
    return new Response(JSON.stringify({strategy: target.searchParams.get('strategy')}));
  };
  try {
    for (const name of ['fast', 'balanced', 'accurate', 'document', null]) {
      const request = new Request('https://site.example/api/ocr?unrelated=x' + (name ? '&strategy=' + name : ''),
        {method: 'POST', headers: {'Content-Type': 'image/png'}, body: 'image-bytes'});
      const response = await onRequestPost({request, env});
      assert.equal(response.status, 200);
      assert.equal((await response.json()).strategy, name);
    }
    for (const name of ['invalid', '']) {
      const request = new Request('https://site.example/api/ocr?strategy=' + name,
        {method: 'POST', headers: {'Content-Type': 'image/png'}, body: 'image-bytes'});
      assert.equal((await onRequestPost({request, env})).status, 422);
    }
    assert.equal(calls, 5);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
