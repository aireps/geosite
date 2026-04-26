# geosite

Custom geosite.dat for Xray/V2Ray routing.

Fork of [hydraponique/roscomvpn-geosite](https://github.com/hydraponique/roscomvpn-geosite) — all upstream categories preserved, additional categories aggregated from other sources via a declarative manifest.

## Added categories

### From [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community)

| Category | Description |
|---|---|
| `category-ip-geo-detect` | IP geolocation domains (used in INCY DirectSites) |
| `ipip` | Transitive dependency of `category-ip-geo-detect` (`include:ipip`) |
| `yandex` | Yandex services (used in RU split routing → direct) |
| `kinopoisk` | Transitive dependency of `yandex` (`include:kinopoisk`) |
| `vk` | VKontakte and Mail.ru services (used in RU split routing → direct) |
| `category-gov-ru` | Russian government domains (used in RU split routing → direct) |

### From [hagezi/dns-blocklists](https://github.com/hagezi/dns-blocklists)

| Category | Source list | Domains | Description |
|---|---|---|---|
| `category-ads` | Light | ~135k | Ad/tracking blocklist (near-zero false positives) |

Self-contained flat domain list with no transitive dependencies, refreshed daily.

**Quick switch to Pro (~395k domains):** change `path: domains/light.txt` to `path: domains/pro.txt` in [`sources.yaml`](sources.yaml), push to master, and trigger `sync-sources.yml`. The category name stays the same — no config changes needed anywhere.

## Download

### Full (all categories)

```
https://cdn.jsdelivr.net/gh/aireps/geosite@release/geosite.dat
```

For nodes and routers that use `geosite:category-ads` in routing rules.

### Lite (without category-ads)

```
https://cdn.jsdelivr.net/gh/aireps/geosite@release/geosite-lite.dat
```

For mobile clients where ads are blocked server-side. Same categories minus `category-ads` (~75 KB vs ~1.8 MB).

## Sync

- [sync-upstream.yml](.github/workflows/sync-upstream.yml) — daily 05:00 UTC, merges from [hydraponique/roscomvpn-geosite](https://github.com/hydraponique/roscomvpn-geosite).
- [sync-sources.yml](.github/workflows/sync-sources.yml) — daily 06:00 UTC, fetches the categories listed above per [`sources.yaml`](sources.yaml).

Both workflows trigger [build.yml](.github/workflows/build.yml) on changes; the resulting `geosite.dat` is published to the `release` branch (CDN-served via `@release`).
