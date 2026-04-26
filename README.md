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
| `category-ads-lite` | Light | ~135k | Conservative ad/tracking blocklist (near-zero false positives) |
| `category-ads-pro` | Pro | ~395k | Comprehensive ad/tracking/malware blocklist |

Lite is a functional subset of Pro. Both are self-contained flat domain lists with no transitive dependencies, refreshed daily.

## Download

```
https://cdn.jsdelivr.net/gh/aireps/geosite@release/geosite.dat
```

## Sync

- [sync-upstream.yml](.github/workflows/sync-upstream.yml) — daily 05:00 UTC, merges from [hydraponique/roscomvpn-geosite](https://github.com/hydraponique/roscomvpn-geosite).
- [sync-sources.yml](.github/workflows/sync-sources.yml) — daily 06:00 UTC, fetches the categories listed above per [`sources.yaml`](sources.yaml).

Both workflows trigger [build.yml](.github/workflows/build.yml) on changes; the resulting `geosite.dat` is published to the `release` branch (CDN-served via `@release`).
