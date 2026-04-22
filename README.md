# geosite

Custom geosite.dat for Xray/V2Ray routing.

Fork of [hydraponique/roscomvpn-geosite](https://github.com/hydraponique/roscomvpn-geosite) — all upstream categories preserved, additional categories aggregated from other sources via a declarative manifest.

## Added categories

All categories below are pulled from [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community) and refreshed daily.

| Category | Description |
|---|---|
| `category-ip-geo-detect` | IP geolocation domains (used in INCY DirectSites) |
| `ipip` | Transitive dependency of `category-ip-geo-detect` (`include:ipip`) |
| `yandex` | Yandex services (used in RU split routing → direct) |
| `vk` | VKontakte and Mail.ru services (used in RU split routing → direct) |
| `category-gov-ru` | Russian government domains (used in RU split routing → direct) |
| `category-ads-all` | Wide ad/tracker blocklist (used by EU nodes → blocked) |

## Download

```
https://cdn.jsdelivr.net/gh/aireps/geosite@release/geosite.dat
```

## Sync

- [sync-upstream.yml](.github/workflows/sync-upstream.yml) — daily 05:00 UTC, merges from [hydraponique/roscomvpn-geosite](https://github.com/hydraponique/roscomvpn-geosite).
- [sync-sources.yml](.github/workflows/sync-sources.yml) — daily 06:00 UTC, fetches the categories listed above per [`sources.yaml`](sources.yaml).

Both workflows trigger [build.yml](.github/workflows/build.yml) on changes; the resulting `geosite.dat` is published to the `release` branch (CDN-served via `@release`).
