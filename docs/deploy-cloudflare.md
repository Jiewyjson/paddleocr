# Cloudflare Pages + Access deployment

This MVP has two independently protected hosts. The original PDF/image stays in
the browser; only the rendered crop crosses the network:

```text
browser
  │  Access browser session
  ▼
app.<your-domain>  (Cloudflare Pages + /api/ocr Function)
  │  Access service token, crop JPEG stream only
  ▼
ocr-api.<your-domain>  (Cloudflare Access + Tunnel)
  ▼
cloudflared on a separate LAN tunnel host
  ▼
http://<ocr-mac-lan-ip>:8788    (FastAPI on this Mac)
  ▼
127.0.0.1:8111    (MLX-VLM on this Mac)
```

The Pages site and the tunnel API must use **different hostnames**. A hostname
can be attached to either Pages or a Tunnel route, not both. For example,
`ocr.wyjsonw.com` can serve the Pages UI while
`ocr-api.wyjsonw.com` reaches the Mac through the Tunnel. FastAPI is reachable
only at this Mac's fixed/reserved LAN address;
the MLX-VLM server remains loopback-only. `cloudflared` may run on any LAN host
that can reach FastAPI at that address.

## 1. Create and deploy the Pages site with Wrangler

This repository uses the same manual, local-Wrangler release style as
`../paste`, but its target is **Cloudflare Pages** rather than an OpenNext
Worker. `web/functions/api/ocr.ts` requires a Pages Function, so do not use
Dashboard drag-and-drop uploads and do not run `wrangler deploy`.

This is a **Direct Upload** Pages project. Cloudflare does not allow a Direct
Upload project to later become a Git-integrated Pages project. Use this path
when releases should be explicitly published from this checkout.

From `web/`, install dependencies once, log in to the same Cloudflare account
used by the tunnel, then create the project and make the first deployment:

```bash
pnpm install
pnpm pages:login
pnpm pages:create -- <pages-project-name> main
pnpm pages:deploy -- <pages-project-name> main
```

The `pages:deploy` helper runs `astro build`, uploads `dist/`, and compiles the
root `functions/` directory into the `/api/ocr` Pages Function. It requires the
project name explicitly, rather than using a cached Wrangler project selection.
For a preview deployment, pass a non-production branch:

```bash
pnpm pages:deploy -- <pages-project-name> preview
```

Attach `app.<your-domain>` as the production custom domain. Do not set
`PUBLIC_OCR_ENDPOINT` in Pages: an unset value makes the browser call the
same-origin Function at `/api/ocr`.

## 2. Protect the Pages host with browser authentication

In Cloudflare Zero Trust, create an **Access > Self-hosted** application for
`app.<your-domain>`. Add an Allow policy for the intended identity provider,
group, or email list. For a Pages custom domain, create a specific Access
application for that hostname; protecting `*.pages.dev` alone does not protect
the custom domain correctly.

The browser must pass this Access application before it can invoke the Pages
Function. No user Access token is exposed to JavaScript or sent to the Mac.

## 3. Publish and protect the API host

Reserve a stable LAN address for the OCR Mac, for example `192.168.1.50`, and
bind FastAPI to that exact address. The tunnel connector is on the other LAN
machine, so it must be able to reach this address and port.

```bash
OCR_BIND_HOST=192.168.1.50 just serve
```

`just serve` defaults FastAPI to loopback. Override `OCR_BIND_HOST` when the
tunnel host needs to reach this Mac over the LAN. MLX-VLM stays on
`127.0.0.1`. You can still start the two scripts directly:

```bash
./scripts/start_mlx_vlm_server.sh
OCR_BIND_HOST=192.168.1.50 bash scripts/start_ocr_api.sh
```

Create a second Self-hosted Access application for `ocr-api.<your-domain>`. Give
it a **Service Auth** policy that accepts the service token created in the next
step.

The public-hostname-to-origin mapping has one source of truth. Choose the mode
used by the existing Tunnel; do not configure competing ingress rules in both
places:

1. **Remotely managed Tunnel (Dashboard):** On the machine already running
   `cloudflared`, keep using its existing connector configuration. In the
   Cloudflare Tunnel Dashboard, add `ocr-api.<your-domain>` with service
   `http://192.168.1.50:8788`. The Access application provides the edge
   protection for this hostname. The Dashboard owns this route; no local
   `ingress` YAML is needed for it. If the connector configuration supports
   origin JWT validation, configuring the application's audience is an
   optional defense-in-depth layer.
2. **Locally managed Tunnel (YAML):** Copy
   `infra/cloudflared/config.yml.example` to a private location on the *tunnel
   host*, replace the placeholders (including the OCR Mac LAN IP), and run:

   ```bash
   cloudflared tunnel --config /private/path/to/config.yml run
   ```

   Its `ingress` section owns the route. Set `audTag` to the API Access
   application's audience. `originRequest.access.required` makes cloudflared
   validate the Access JWT before forwarding traffic to FastAPI.

Do not bind either Python service to `0.0.0.0`. MLX-VLM must remain on
`127.0.0.1`; FastAPI is the only service that needs a scoped LAN listener.

## 4. Allow the Pages Function to call the API

Create an Access service token. The repository includes a terminal helper that
prompts for the required values and stores all three as encrypted Pages secrets:

```bash
cd web
pnpm pages:secrets -- <pages-project-name>
```

Enter `OCR_API_ORIGIN` as a complete HTTP(S) URL — for example,
`https://ocr-api.<your-domain>`, **not** `ocr-api.<your-domain>` — followed by the
Access service token Client ID and Client Secret. `OCR_API_ORIGIN` is not
confidential, but storing it as a secret keeps the manual release flow entirely
in Wrangler and works identically at runtime. Alternatively, add it as a normal
Pages variable in the dashboard.
The bindings are:

| Pages variable | Value |
| --- | --- |
| `OCR_API_ORIGIN` | `https://ocr-api.<your-domain>` |
| `CF_ACCESS_CLIENT_ID` | service token client ID (encrypted) |
| `CF_ACCESS_CLIENT_SECRET` | service token client secret (encrypted) |
| `OCR_MAX_IMAGE_BYTES` | optional, defaults to `10485760` |

`web/functions/api/ocr.ts` injects the service-token headers server-side and
streams the request body. Never set either Access credential with a `PUBLIC_`
prefix and never place them in `.env` committed to Git. For local Pages
Function testing, copy `web/.dev.vars.example` to `web/.dev.vars`, add test
values, then run `pnpm pages:dev`.

## 5. Restrict LAN access to FastAPI

Binding FastAPI to a LAN address makes `http://192.168.1.50:8788` reachable
inside the LAN. Cloudflare Access is enforced at Cloudflare's edge, so a
client that calls FastAPI directly would not pass through that check. Add a
Mac firewall or router ACL that permits TCP/8788 only from the tunnel host's
LAN IP. Do not create a router port-forward for 8788 or 8111.

## Why there are two Access applications

Browser Access answers “may this person use the tool?” The API Access
application answers “may this Pages Function reach the Mac?” This avoids CORS
and cross-subdomain Access-cookie problems while keeping the API unreachable
from arbitrary Internet clients. The LAN firewall rule above is what prevents
other LAN clients from bypassing the tunnel and calling FastAPI directly.

## Official references

- [Protect a Pages custom domain with Access](https://developers.cloudflare.com/pages/platform/known-issues/)
- [Pages Function variables and encrypted secrets](https://developers.cloudflare.com/pages/functions/bindings/)
- [Access CORS proxy pattern with a service token](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/cors/)
- [Tunnel `Protect with Access` / origin JWT validation](https://developers.cloudflare.com/tunnel/advanced/origin-parameters/)
- [Locally managed versus remotely managed Tunnels](https://developers.cloudflare.com/tunnel/advanced/local-management/)
