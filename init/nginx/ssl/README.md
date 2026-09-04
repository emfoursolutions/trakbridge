# TrakBridge nginx TLS material

Drop the two files nginx expects into **this directory** on the host:

| File               | Purpose                                    |
|--------------------|--------------------------------------------|
| `trakbridge.crt`   | PEM-encoded server certificate (full chain) |
| `trakbridge.key`   | PEM-encoded private key                     |

They are mounted read-only into the `nginx` container by
`docker-compose.yml` at `/etc/nginx/ssl/`. Both filenames are
referenced from `init/nginx/nginx.conf`; if you rename either,
update the `ssl_certificate` / `ssl_certificate_key` directives
to match.

## Local / self-signed testing

```bash
openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout trakbridge.key -out trakbridge.crt \
  -days 365 -subj "/CN=localhost"
chmod 600 trakbridge.key
```

Browsers will warn on the self-signed cert — that's expected for
local testing.

## Production

Use a real CA. If Let's Encrypt suits, run certbot on the host
and symlink or copy the fullchain/privkey into this directory,
then reload nginx (`docker compose exec nginx nginx -s reload`)
on renewal.
