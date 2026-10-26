# Local Ubuntu builds, installation and VPN acceptance

For the existing server checkout at `alta.jeffhansen.com:~/repo/xpn` and its current nginx/Let's Encrypt setup, start with [the alta deployment guide](ALTA-DEPLOYMENT.md). The VM workflow below remains useful for clean Noble/Resolute package validation afterward.

Test before publishing. Use a dedicated Ubuntu VM or test host for the server and a separate client device/VM; the server deliberately blocks traffic to itself and to other VPN clients. Test the software on both **Noble (24.04 LTS)** and **Resolute (26.04 LTS)**. A package built on one series is not validation of the other.

The repository includes a draft Debian source recipe producing exactly two user-facing packages:

| Package | Contents |
| --- | --- |
| `xpn-client` | `/usr/bin/xpn` Python launcher, private native executable, camera enrollment support |
| `xpn-server` | private native executable, Node console/enrollment, bundled locked JS dependencies, systemd units and example nginx/config files |

The shared native executable is installed in different private paths, so the two packages can coexist without file conflicts. Installing either does not require the other. Server installation creates one `xpn` account for both control and packet services but **does not start or enable services or alter nginx/firewall configuration**. Upgrading/removing the server stops its services; restart explicitly after checking configuration. User credentials/data are retained.

## 1. Create test VMs on your Mac

If you already have Ubuntu test hosts, skip VM creation. Otherwise install [Canonical Multipass](https://canonical.com/multipass/install), then in macOS Terminal:

```sh
multipass launch noble --name xpn-noble --cpus 4 --memory 4G --disk 30G
multipass launch resolute --name xpn-resolute --cpus 4 --memory 4G --disk 30G
multipass list
```

Apple Silicon produces arm64 VMs/packages. Later test amd64 separately for common EC2/x86 machines; arm64 results do not validate amd64. Stop an unused VM to save memory with `multipass stop xpn-resolute`. [Canonical's VM tutorial](https://canonical.com/multipass/docs/stable/tutorial/getting-started/) covers installation and shell access.

## 2. Prepare source snapshots on the Mac

From `/Users/ninkid/repo/xpn`, with Node **24.13.1+** and npm installed:

```sh
node --version
python3 packaging/prepare-source.py noble --output build/packages/noble-current
python3 packaging/prepare-source.py resolute --output build/packages/resolute-current
```

Each command copies the current source (including uncommitted work), downloads production npm sources according to the lockfile with install scripts disabled, and creates a clean source tree plus `.orig.tar.xz` in `build/packages/<series>`. It never installs a package or uploads anything. It refuses nonempty output directories; use a fresh `--output` directory to repeat. `--revision 2` changes the series-specific package revision when preparing a new build. The recipe does not perform network downloads during Debian builds.

The initial snapshots in `build/packages/noble` and `build/packages/resolute` predate the privilege-separation changes. Prepare fresh snapshots with the commands above before building packages. After further edits, choose another empty output directory and update the transfer path.

Transfer the prepared source to each VM:

```sh
multipass transfer --recursive build/packages/noble-current/xpn-0.1.0 xpn-noble:/home/ubuntu/xpn-0.1.0
multipass transfer --recursive build/packages/resolute-current/xpn-0.1.0 xpn-resolute:/home/ubuntu/xpn-0.1.0
multipass shell xpn-noble
```

The following commands run **inside the Ubuntu VM**, not macOS. Repeat in Resolute after Noble passes.

## 3. Install build dependencies and build the two packages

```sh
sudo apt-get update
sudo apt-get install -y build-essential debhelper cmake ninja-build pkg-config \
  libssl-dev libwebsockets-dev libjansson-dev libcurl4-openssl-dev \
  devscripts lintian nginx openssl curl
cd ~/xpn-0.1.0
dpkg-buildpackage -us -uc -b
ls ../xpn-client_*.deb ../xpn-server_*.deb
lintian ../xpn-client_*.deb ../xpn-server_*.deb
```

Enable Ubuntu's `universe` component if a dependency is unavailable. `dpkg-buildpackage` runs native C unit tests as part of the build. It does not install the output. Expect release-metadata/license warnings from this local packaging draft; resolve these before public upload rather than ignoring them in a release pipeline.

For an unpackaged native-only build instead:

```sh
cmake -S native -B build-native-manual -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build build-native-manual
ctest --test-dir build-native-manual --output-on-failure
```

Do not install both the `/usr/local` manual layout from README and the packaged server layout on the same test host. Prefer the packages for repeatable install/upgrade/removal tests.

## 4. Supply the server's Node runtime and run loopback tests

The Node service currently requires **Node 24.13.1+** (`node:sqlite` and the pinned dependency set). Ubuntu's default Node packages are insufficient: Noble ships Node 18, and [Resolute ships Node 22](https://packages.ubuntu.com/resolute/nodejs). The Debian package deliberately declares `nodejs (>= 24.13.1)` instead of letting an unsupported runtime install silently. The native client has no Node dependency.

For these **disposable local VMs**, one option is NodeSource's Node 24 apt package. Review the [official NodeSource installation recipe](https://github.com/nodesource/distributions/blob/master/scripts/deb/setup_24.x) before adding this third-party repository. Download the script, inspect it, then execute it inside the VM:

```sh
curl -fsSL https://deb.nodesource.com/setup_24.x -o /tmp/xpn-node-setup.sh
less /tmp/xpn-node-setup.sh
sudo bash /tmp/xpn-node-setup.sh
sudo apt-get install -y nodejs
node --version
dpkg-query -W nodejs
node -e 'const [a,b,c]=process.versions.node.split(".").map(Number); if(a<24 || (a===24 && (b<13 || (b===13 && c<1)))) process.exit(1)'
```

This installs a Debian-visible `nodejs` package. An `nvm` shell installation alone does not satisfy apt dependencies or `/usr/bin/node` in systemd. Verify the candidate meets the minimum before installing `xpn-server`; repository lag can leave older Node 24 builds available.

From the prepared source tree, link the already-vendored JS sources for tests and run:

```sh
ln -s vendor/node_modules node_modules
npm test
npm run check
node server/native-integration.mjs build-native/test_transport
for scenario in sni wrong-pin trusted-wrong-pin rotation pin-only; do
  XPN_TEST_PINNING="$scenario" node server/native-integration.mjs build-native/test_transport || break
done
```

These tests use temporary loopback nginx/listeners and no TUN or real SMTP. `ln -s` is a one-time step; omit it if the symlink already exists. Start with **Fast PSK** mode on both series. ML-KEM hybrid requires OpenSSL 3.5+ on both ends; do not select it just because the client supports it.

## 5. Install and configure the test server

```sh
sudo apt-get install ../xpn-server_*.deb
sudo install -m 600 -o root -g root \
  /usr/share/doc/xpn-server/examples/xpn.env.example /etc/xpn.env
openssl rand -hex 32
openssl rand -hex 32
sudoedit /etc/xpn.env
```

Use the two independently generated values for `MASTER_KEY` and `ADMIN_TOKEN`. Set `PUBLIC_URL` to your reachable HTTPS hostname and `/xpn` prefix. Leave SMTP unset for the first test. Optionally set `VPN_SNI` and `VPN_CERTIFICATE_PINS` using [the pinning guide](PINNING.md). Preserve `/xpn/vpn` while following these first-test steps; another prefix also requires changing the native unit's path and nginx locations.

For the first Apple/iOS test, use a test DNS name you control with a normally valid certificate at the HTTPS ingress. Point its nginx proxy at this VM or use a reachable Ubuntu test host. A local `localhost` name or Mac-only hosts-file entry will not make the endpoint reachable from an iPhone. Multipass private NAT addresses may only be reachable from the host Mac. Enrollment still needs normally trusted HTTPS, even when the later VPN connection uses a pinned mismatched certificate/custom SNI.

Review `/usr/share/doc/xpn-server/examples/nginx.conf`. Merge its `map`, rate zones, server and locations into your test nginx configuration; replace the sample hostname/certificate paths. When nginx runs on the Ubuntu server, ports 3000/3001 stay on loopback. If nginx is elsewhere, use an explicit protected forwarding path; simply pointing it at a loopback-only service on another machine will not work.

```sh
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable --now xpn-network xpn-control xpn-native
sudo systemctl reload nginx
systemctl status xpn-control xpn-native xpn-network --no-pager
journalctl -u xpn-control -u xpn-native -n 100 --no-pager
```

The network service creates `xpn0`, enables IPv4 forwarding, and installs only its own `inet xpn` nftables table. Check any existing FORWARD-drop firewall separately. The first setup intentionally requires reviewing these changes before starting services.

Open `https://YOUR-HOST/xpn/`, unlock with the admin token, and create one identity per test device. Choose **Fast** and **Selected subnets** first. Select a subnet containing a separate reachable test endpoint, not the VPN server, loopback, link-local or `10.77.0.0/24`. Scan/import the new QR in the Apple app as described in [Apple local builds](APPLE-LOCAL.md).

## 6. Install and test the Linux client

Use another Ubuntu VM/host, or transfer the `.deb` built for that same series/architecture to it. Install:

```sh
sudo apt-get install ./xpn-client_0.1.0-0ubuntu1~noble1_arm64.deb
xpn enroll ./my-device.json
sudo xpn connect ./my-device.json
```

Adjust the filename for Resolute or amd64. Paste the one-use invitation at the prompt; it will not appear as a shell argument. A desktop Linux machine with a camera can use `xpn enroll ./my-device.json --scan` after installing `zbar-tools`. A headless Multipass VM generally has no camera passthrough. A JSON download can be used directly with `chmod 600 my-device.json`.

Enrollment refuses to overwrite an existing file. For a refreshed QR/profile, use a new filename, verify it, then retire the old credential file. Press Ctrl-C to disconnect and restore routes/firewall state created by this client invocation.

## 7. Acceptance checklist before any PPA upload

Record OS series, architecture, package version, OpenSSL version and results:

1. **Split routing:** selected subnet works; other traffic keeps its ordinary route. Confirm the server rejects packets outside the user's allowed policy.
2. **Full routing:** after switching to a full-tunnel device profile, verify outbound IPv4 at a separate controlled endpoint uses the server's egress. Verify DNS uses the configured tunnel DNS and IPv6 does not escape locally.
3. **Trust:** correct pin + custom SNI connects; wrong pin rejects; expired pinned certificate rejects; nginx logs confirm the requested SNI and original HTTP Host.
4. **Lifecycle:** disconnect restores routing, revoke disconnects an active session, key rotation invalidates old credentials, fresh QR is single-use. Reboot and test systemd startup.
5. **Throughput:** run `iperf3 -P 4 -t 30` and `-R` against a permitted separate test host. Measure CPU and repeat with realistic WAN conditions. Local nginx synthetic results are not a device/TUN/AWS throughput guarantee.
6. **Apple:** test real camera permission, JSON import, shared Keychain and tunnel activation; test Wi-Fi/cellular switching and sleep. Reconnect manually after closure; automatic roaming is not implemented.
7. **Packaging:** clean install, client/server coexistence, upgrade, stop/restart and removal on Noble and Resolute, arm64 and amd64 as needed. Check no service starts on first install before configuration.

Stop the test server when finished:

```sh
sudo systemctl disable --now xpn-native xpn-control xpn-network
```

Stopping `xpn-network` removes the XPN table and `xpn0`; it leaves global IPv4 forwarding enabled because other services may depend on it. It never flushes unrelated firewall rules. Back up `/var/lib/xpn` and `/etc/xpn.env` together before upgrades. Uninstallation retains this private state; delete it only when intentionally retiring the deployment.

## 8. PPA publication comes after these checks

The source recipe is a **local packaging draft**, not a published PPA or a tested Ubuntu release. Before uploading:

- Choose your upstream distribution license and copyright identity. `debian/copyright` explicitly records that these are unresolved. Audit and record licenses of the bundled npm dependencies.
- Replace the local builder identity with your real `DEBFULLNAME` and `DEBEMAIL` when preparing the source. Decide the Launchpad owner/PPA name and register its signing key.
- Resolve Node 24 distribution: a PPA can build the native packages using Ubuntu build dependencies, but the server still needs a satisfiable Node 24 runtime dependency on installed systems. NodeSource can serve local tests; it is not automatically enabled for PPA users. A source-built Node 24 backport/dependency PPA or a deliberate runtime compatibility change needs separate validation. Do not bundle a downloaded Node binary into a PPA source package.
- Build each series independently. Use distinct versions such as `0.1.0-0ubuntu1~noble1` and `0.1.0-0ubuntu1~resolute1`; increment revisions after upload. The prepared `.orig.tar.xz` contains locked npm source dependencies so Launchpad does not need `npm install` network access during builds.
- Run clean `sbuild` builds, lintian and install/upgrade tests on both series. Review source contents for secrets before signing. Only then create a signed source upload with `debuild -S -sa -kYOUR_GPG_KEY_ID` and upload its `_source.changes` using `dput ppa:YOUR_OWNER/YOUR_PPA ...`.

Launchpad takes source uploads and builds binary packages; uploading the locally built `.deb` files is not the PPA workflow. See [Launchpad's upload instructions](https://ubuntu.com/docs/launchpad/user/how-to/packaging/ppa-package-upload/). No PPA, upload, account change or cloud deployment has been performed here.
