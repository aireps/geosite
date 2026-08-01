# geosite

Routing data for Xray, V2Ray, Mihomo and sing-box, rebuilt daily.

Fork of [hydraponique/roscomvpn-geosite](https://github.com/hydraponique/roscomvpn-geosite). Every upstream category is preserved; a few more are pulled in from [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community) and [hagezi/dns-blocklists](https://github.com/hagezi/dns-blocklists) through a declarative manifest, [`sources.yaml`](sources.yaml).

## Download

Everything below is served from the `release` branch via jsDelivr and attached to every [GitHub Release](https://github.com/aireps/geosite/releases).

### Xray / V2Ray

```
https://cdn.jsdelivr.net/gh/aireps/geosite@release/geosite.dat
https://cdn.jsdelivr.net/gh/aireps/geosite@release/geosite-lite.dat
```

| File | Size | Contents |
|---|---|---|
| `geosite.dat` | ~1 MiB | All categories |
| `geosite-lite.dat` | ~75 KiB | Everything except `category-ads` |

The lite build is for clients sitting behind a server that already filters ads, so they do not need to carry the blocklist themselves — that one category is the whole difference in size. Each file has a `.sha256` next to it.

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
| `vk` | v2fly | VK and Mail.ru services |
| `yandex` | v2fly | Yandex services |

Inherited from upstream: `apple`, `category-geoblock-ru`, `category-ru`, `epicgames`, `escapefromtarkov`, `faceit`, `github`, `google-deepmind`, `google-play`, `microsoft`, `origin`, `pinterest`, `private`, `riot`, `steam`, `telegram`, `torrent`, `twitch`, `twitch-ads`, `whitelist`, `win-spy`, `youtube`.

## Choosing an ad blocklist tier

`category-ads` follows hagezi's Light tier, which covers the common ad and tracking hosts and stays conservative about false positives. Heavier tiers are drop-in replacements:

| Tier | Domains | Path in `hagezi/dns-blocklists` |
|---|---|---|
| Light (current) | ~42k | `wildcard/light-onlydomains.txt` |
| Multi | ~181k | `wildcard/multi-onlydomains.txt` |
| Pro | ~216k | `wildcard/pro-onlydomains.txt` |
| Pro++ | ~239k | `wildcard/pro.plus-onlydomains.txt` |
| Ultimate | ~263k | `wildcard/ultimate-onlydomains.txt` |

To switch, change `path:` on the `category-ads` entry in [`sources.yaml`](sources.yaml), push to `master`, then run `sync-sources.yml`. The category name stays the same, so nothing downstream has to change.

These lists hold base domains only, which is not a gap in coverage: a line with no prefix compiles to a `RootDomain` rule, and that matches the domain along with every subdomain under it.

## How it stays current

| Workflow | Schedule | Job |
|---|---|---|
| [`sync-upstream.yml`](.github/workflows/sync-upstream.yml) | daily, 05:00 UTC | Merge from the upstream fork |
| [`sync-sources.yml`](.github/workflows/sync-sources.yml) | daily, 06:00 UTC | Fetch the categories listed in the manifest |
| [`build.yml`](.github/workflows/build.yml) | on change | Build and publish |

Either sync triggers a build once something has actually changed. The build compiles the categories with [v2fly's generator](https://github.com/v2fly/domain-list-community), converts them into Mihomo and sing-box rule sets, pushes the result to the `release` branch and cuts a dated GitHub Release.

One dead source does not hold up the rest: the sync records the failure, commits whatever it did fetch, and reports the run as failed at the end.

## License

MIT, see [LICENSE](LICENSE).
