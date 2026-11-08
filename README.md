# geosite

Routing data for Xray, V2Ray, Mihomo and sing-box, rebuilt daily.

Fork of [hydraponique/roscomvpn-geosite](https://github.com/hydraponique/roscomvpn-geosite). Every upstream category is preserved; a few more are pulled in from [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community) and [hagezi/dns-blocklists](https://github.com/hagezi/dns-blocklists) through a declarative manifest, [`sources.yaml`](sources.yaml).

## Download

Everything below is served from the `release` branch via jsDelivr and attached to every [GitHub Release](https://github.com/aireps/geosite/releases).

The `release/` folder on `master` is not where this fork publishes: the build never writes to `master`, and the folder is the upstream's build, byte for byte, kept in step by the merge. Use the `release` branch or the GitHub Releases.

### Xray / V2Ray

```
https://cdn.jsdelivr.net/gh/aireps/geosite@release/geosite.dat
https://cdn.jsdelivr.net/gh/aireps/geosite@release/geosite-lite.dat
```

| File | Contents |
|---|---|
| `geosite.dat` | All categories |
| `geosite-lite.dat` | Everything except `category-ads` |

The lite build is for clients sitting behind a server that already filters ads, so they do not need to carry the blocklist themselves — that one category is the whole difference in size. Each file has a `.sha256` next to it, and every GitHub Release shows the size of each file.

Drop the file into Xray's asset directory (`/usr/local/share/xray/` by default) and reference a category by name:

```json
{
  "type": "field",
  "domain": ["geosite:category-ads"],
  "outboundTag": "block"
}
```

### Mihomo / sing-box

One rule set per category:

```
https://cdn.jsdelivr.net/gh/aireps/geosite@release/mihomo/<category>.mrs
https://cdn.jsdelivr.net/gh/aireps/geosite@release/sing-box/<category>.srs
```

Or all of them at once, as [`mihomo.tar.gz`](https://cdn.jsdelivr.net/gh/aireps/geosite@release/mihomo.tar.gz) and [`sing-box.tar.gz`](https://cdn.jsdelivr.net/gh/aireps/geosite@release/sing-box.tar.gz).

## Categories

Maintained here through the manifest:

| Category | Source | Purpose |
|---|---|---|
| `category-ads` | hagezi, Light tier | Ads and tracking, tuned for near-zero false positives |
| `category-gov-ru` | v2fly | Russian government domains |
| `category-ip-geo-detect` | v2fly | IP geolocation services |
| `ipip` | v2fly | Required by `category-ip-geo-detect` (`include:ipip`) |
| `kinopoisk` | v2fly | Required by `yandex` (`include:kinopoisk`) |
| `test-ipv6` | v2fly | Required by `category-ip-geo-detect` (`include:test-ipv6`) |
| `vk` | v2fly | VK and Mail.ru services |
| `yandex` | v2fly | Yandex services |

Inherited from upstream: `apple`, `category-geoblock-ru`, `category-ru`, `epicgames`, `escapefromtarkov`, `faceit`, `github`, `google-deepmind`, `google-play`, `microsoft`, `origin`, `pinterest`, `private`, `riot`, `steam`, `telegram`, `torrent`, `twitch`, `twitch-ads`, `whitelist`, `win-spy`, `youtube`.

## Choosing an ad blocklist tier

`category-ads` follows hagezi's Light tier, which covers the common ad and tracking hosts and stays conservative about false positives. Heavier tiers are drop-in replacements:

| Tier | Path in `hagezi/dns-blocklists` |
|---|---|
| Light (current) | `wildcard/light-onlydomains.txt` |
| Multi | `wildcard/multi-onlydomains.txt` |
| Pro | `wildcard/pro-onlydomains.txt` |
| Pro++ | `wildcard/pro.plus-onlydomains.txt` |
| Ultimate | `wildcard/ultimate-onlydomains.txt` |

Each list states its current size in the `Number of entries` line of its header. The numbers change from day to day, so they are not repeated here.

To switch, change `path:` on the `category-ads` entry in [`sources.yaml`](sources.yaml), push to `master`, then run `sync-sources.yml`. The category name stays the same, so nothing downstream has to change.

These lists hold base domains only, which is not a gap in coverage: a line with no prefix compiles to a `RootDomain` rule, and that matches the domain along with every subdomain under it.

## How it stays current

| Workflow | Schedule | Job |
|---|---|---|
| [`sync-upstream.yml`](.github/workflows/sync-upstream.yml) | daily, 05:00 UTC | Merge from the upstream fork |
| [`sync-sources.yml`](.github/workflows/sync-sources.yml) | daily, 06:00 UTC | Fetch the categories listed in the manifest |
| [`build.yml`](.github/workflows/build.yml) | on change | Build and publish |

Either sync triggers a build once something has actually changed. The build compiles the categories with [v2fly's generator](https://github.com/v2fly/domain-list-community), converts them into Mihomo and sing-box rule sets, pushes the result to the `release` branch and cuts a dated GitHub Release.

One dead source does not hold up the rest: the sync records the failure, commits whatever it did fetch, and reports the run as failed at the end. The same holds for a source the generator would refuse: every fetched list is checked line by line against the generator's grammar, affiliations (`&list`) are not accepted at all, and an `include:` must name a target of the manifest that will exist after the run, without forming an include cycle. A list that fails any of this keeps its previous version, so one bad upstream change cannot break the build.

Before fetching anything, `sync-sources.yml` runs the unit tests of the sync script, and a failing test stops the run. When any of the three workflows fails, [`notify-failure.yml`](.github/workflows/notify-failure.yml) sends a Telegram message that names the failed job and step and quotes the error lines from that job's log.

## License

MIT, see [LICENSE](LICENSE).
