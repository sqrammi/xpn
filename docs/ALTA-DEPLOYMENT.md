# First deployment on alta.jeffhansen.com

For changes already made on the host, see the [Alta host change record](ALTA-HOST-CHANGES.md). This page is the deployment procedure.

Use the existing nginx HTTPS virtual host and Let's Encrypt certificate. The console will be `https://alta.jeffhansen.com/xpn/`, enrollment under `/xpn/join`, and the native tunnel `wss://alta.jeffhansen.com/xpn/vpn`. Both upstream services listen only on loopback. No additional public port or certificate is required.

These are future deployment instructions. Builds/tests now run in the existing `~/repo/xpn` checkout (`/root/repo/xpn` on Alta), using one service account, `xpn`. The former `/opt/xpn-test` workspace and `xpn-packet` account were removed after successful migration. No persistent XPN services or live nginx changes have been installed.

Observed host details: Ubuntu 26.04.1 Resolute, x86-64, system Node 22.22.1, existing HTTPS certificate `/etc/ssl/cert.pem`. The private Node 24.22.1 runtime is now `~/repo/xpn/build/tools/node-v24.22.1-linux-x64/`. **Port 3001 is already an upstream for `/ips/`**. This guide uses 3301 for XPN's native service instead; recheck that 3000 and 3301 are available before deploying.

## 1. Inspect prerequisites on alta

Run after logging into alta:

```sh
cd ~/repo/xpn
cat /etc/os-release
uname -m
node --version
/usr/bin/node --version
sudo ss -ltnp '( sport = :3000 or sport = :3301 )'
sudo nginx -t
```

This recipe uses Node **24.13.1+**, OpenSSL **3.0+**, libwebsockets **4.3+** and ports 3000/3301. Use the private Node runtime under the checkout instead of replacing system Node. The service overrides below expose the same source/build tree through a private read-only mount; no runtime copy under `/opt` or changes to `/root` permissions are needed.

If either port is occupied, choose two unused loopback ports. Change `PORT` in `/etc/xpn.env` for Node, the numeric port in the native unit's `ExecStart` for C, and the corresponding `proxy_pass` lines in the locations snippet. Do not stop another service to free a port.

Inspect your existing HTTPS `server {}` for `alta.jeffhansen.com` and record its actual file path. `sudo nginx -T` can locate it, but do not post the complete output publicly because other services' config may contain secrets. Retain its certificate paths and TLS configuration.

## 2. Build in the checkout

On Noble/Resolute with the required Ubuntu components enabled:

```sh
sudo apt-get update
sudo apt-get install -y build-essential cmake ninja-build pkg-config \
  libssl-dev libwebsockets-dev libjansson-dev libcurl4-openssl-dev \
  iproute2 nftables openssl curl
cd ~/repo/xpn
export PATH="$PWD/build/tools/node-v24.22.1-linux-x64/bin:$PATH"
npm ci --ignore-scripts
npm test
npm run check
cmake -S native -B build/native -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build/native
ctest --test-dir build/native --output-on-failure
sudo sh deploy/create-users.sh
# Alta SSH logs in as root; the wrapper starts ordinary tests as xpn.
sh native/tools/test-as-xpn.sh node server/native-integration.mjs build/native/test_transport
XPN_TEST_PINNING=sni sh native/tools/test-as-xpn.sh node server/native-integration.mjs build/native/test_transport
XPN_TEST_PINNING=trusted-wrong-pin sh native/tools/test-as-xpn.sh node server/native-integration.mjs build/native/test_transport
```

The integration tests run their own temporary nginx configuration on ephemeral loopback ports, without reloading the live nginx service or configuring TUN. Keep the initial VPN profiles in **Fast PSK** mode; hybrid requires OpenSSL 3.5+ on both server and client.

## 3. Configure services to use this checkout (not yet performed)

The standard service templates also support packaged installations. For this in-place source deployment, install their definitions and add the following overrides. No source, Node runtime or executable is copied out of the checkout.

```sh
sudo install -m 644 deploy/xpn-control.service deploy/xpn-native.service \
  deploy/xpn-network.service /etc/systemd/system/
sudo install -d /etc/systemd/system/xpn-control.service.d \
  /etc/systemd/system/xpn-native.service.d /etc/systemd/system/xpn-network.service.d
```

Create `/etc/systemd/system/xpn-control.service.d/checkout.conf`:

```ini
[Service]
BindReadOnlyPaths=/root/repo/xpn:/run/xpn-source
WorkingDirectory=/run/xpn-source
ExecStart=
ExecStart=/usr/bin/env /run/xpn-source/build/tools/node-v24.22.1-linux-x64/bin/node /run/xpn-source/server/main.mjs
```

Create `/etc/systemd/system/xpn-native.service.d/checkout.conf`:

```ini
[Service]
BindReadOnlyPaths=/root/repo/xpn:/run/xpn-source
ExecStart=
ExecStart=/usr/bin/env /run/xpn-source/build/native/xpnd server 3301 /run/xpn/control.sock /xpn/vpn xpn0 --loopback
```

Create `/etc/systemd/system/xpn-network.service.d/checkout.conf`:

```ini
[Service]
ExecStart=
ExecStart=/bin/sh /root/repo/xpn/deploy/network.sh
ExecStop=
ExecStop=/bin/sh /root/repo/xpn/deploy/network.sh stop
```

`/run/xpn-source` is a mount view inside each service's private namespace, not a second source tree. `ProtectHome=yes` stays enabled; `/root` stays mode `0700`. The read-only mapping and private Node execution were verified with a temporary `systemd-run` service as `xpn`. Actual production unit startup remains untested. Both Node and the packet daemon use `xpn:xpn`; only the short-lived network setup runs as root. State remains `/var/lib/xpn`, created by systemd. Keep checkout files root-owned and unwritable by `xpn`. Stop services before updating/rebuilding their in-place files. Use either this manual layout or the future `.deb` layout, not both concurrently.

## 4. Create the configuration once

Only if `/etc/xpn.env` does not already exist:

```sh
sudo test -e /etc/xpn.env || sudo install -m 600 -o root -g root \
  deploy/xpn.env.example /etc/xpn.env
openssl rand -hex 32
openssl rand -hex 32
sudoedit /etc/xpn.env
```

Set these values, using the two independent generated values as secrets:

```ini
PUBLIC_URL=https://alta.jeffhansen.com/xpn
MASTER_KEY=<first-generated-64-hex-value>
ADMIN_TOKEN=<second-generated-64-hex-value>
DATA_DIR=/var/lib/xpn
CONTROL_SOCKET=/run/xpn/control.sock
PORT=3000
```

Keep SMTP unset for the first test. Preserve `MASTER_KEY` once the database exists; changing it prevents stored credentials from decrypting. The admin token unlocks the web console and is not a VPN device key.

Initially omit `VPN_SNI`: the client sends the endpoint name `alta.jeffhansen.com`. Pinning can still be enabled independently. To pin the existing certificate, compute its fingerprint from the trusted local **leaf/fullchain PEM actually named in nginx's `ssl_certificate` directive**:

```sh
sudo build/tools/node-v24.22.1-linux-x64/bin/node server/cert-pin.mjs /ACTUAL/NGINX/CERTIFICATE/fullchain.pem
```

Replace the path; Let's Encrypt lineage directories do not always equal the hostname. Use your selected Node executable if it is not `/usr/bin/node`. Put the printed digest into `VPN_CERTIFICATE_PINS` before creating users, or enter it in each user's Certificate / SNI settings. Later, set `VPN_SNI=app.jeffhansen.com` only after configuring nginx to route that SNI to this certificate/service, while also handling HTTP Host `alta.jeffhansen.com`.

Exact-certificate pins change at Let's Encrypt renewal, even with the same private key. Plan pin rotation and redistribute profiles before switching to an unrecognized certificate; pin mismatches fail closed. See [pin rotation](PINNING.md). Do not silently learn replacement pins from the network.

## 5. Add two nginx includes

Install the HTTP-level declarations once:

```sh
sudo install -m 644 deploy/nginx-xpn-http.conf /etc/nginx/conf.d/xpn-http.conf
sudo install -d -m 755 /etc/nginx/snippets
sudo install -m 644 deploy/nginx-xpn-locations.conf /etc/nginx/snippets/xpn-locations.conf
sudo sed -i 's|127.0.0.1:3001|127.0.0.1:3301|g' /etc/nginx/snippets/xpn-locations.conf
```

Confirm `/etc/nginx/nginx.conf` includes `/etc/nginx/conf.d/*.conf` **inside `http {}`**. If your nginx layout differs, explicitly include `xpn-http.conf` there once. Do not also install the whole standalone `deploy/nginx.conf`: it duplicates the map/zones and would create another HTTPS server block.

Back up the actual existing alta virtual-host file, then edit it. Inside its existing **HTTPS** `server {}`, add:

```nginx
include /etc/nginx/snippets/xpn-locations.conf;
```

Keep the existing `listen`, `server_name`, `ssl_certificate`, `ssl_certificate_key` and other services' locations. No replacement certificate directives are needed. The snippet routes only `/xpn` and `/xpn/...`; its `^~` prefix prevents unrelated regex static-asset locations from taking the console's JavaScript/CSS. An existing exact `/xpn` location must be merged rather than duplicated.

The upstream URLs intentionally have **no trailing slash**. This retains `/xpn/...` for Node and C, which both expect that prefix. The native location supplies the WebSocket Upgrade/Connection headers. See [nginx WebSocket proxying](https://nginx.org/en/docs/http/websocket.html) and [proxy_pass URI rules](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass).

Check for server-level authentication or rewrite rules inherited by the new locations. Browser SSO/basic-auth challenges on `/xpn/vpn` prevent native clients from connecting; redirects/challenges on `/xpn/api/enroll` prevent QR enrollment. Keep your access policy intentional and account for these native paths. XPN's admin API independently requires its bearer admin token; enrollment requires a one-time secret and the tunnel requires the device PSK.

## 6. Start, verify, then reload nginx

Before starting, review `deploy/network.sh`: it creates `xpn0`, enables IPv4 forwarding and creates its own `inet xpn` nftables table. Ensure `10.77.0.0/24` does not overlap the host's networks and `xpn0`/`inet xpn` are not used by another service. Existing FORWARD-drop policies may need explicit allow rules too. There is no need to expose ports 3000/3301 in the AWS security group.

```sh
sudo systemctl daemon-reload
sudo systemctl start xpn-network xpn-control xpn-native
systemctl status xpn-control xpn-native xpn-network --no-pager
curl --fail http://127.0.0.1:3000/xpn/ -o /dev/null
sudo nginx -t && sudo systemctl reload nginx
curl --fail https://alta.jeffhansen.com/xpn/ -o /dev/null
```

Open **https://alta.jeffhansen.com/xpn/**, unlock with `ADMIN_TOKEN`, and create one identity for the Mac and another for the iPhone. Use **Fast** and a split subnet containing a separate permitted test host first. The VPN server's own addresses and other VPN clients are deliberately blocked; use another host for traffic/iperf tests. A plain `curl` request to `/xpn/vpn` is not a VPN connection and does not prove a successful WebSocket/inner-TLS handshake.

If anything fails:

```sh
journalctl -u xpn-control -u xpn-native -u xpn-network -n 100 --no-pager
```

Once the functional tests pass, enable boot startup:

```sh
sudo systemctl enable xpn-network xpn-control xpn-native
```

To stop this deployment, stop the native/control services and then the network service. Stopping `xpn-network` removes only its `xpn0` interface and `inet xpn` table; global forwarding remains enabled because other services may depend on it. Remove the location include and HTTP declarations, test nginx, and reload only if you want to remove the proxy routes too. Keep `/etc/xpn.env` and `/var/lib/xpn` backed up together.

After this source-based deployment works, continue [Noble/Resolute package testing](LOCAL-TESTING.md) on clean hosts. Alta validates its own OS/architecture; it does not replace testing both supported package targets before publishing a PPA.
