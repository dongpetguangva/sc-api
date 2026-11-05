# sc-api — cek saldo & pemakaian SinarCloud tanpa buka dashboard

Klien read-only untuk `console.sinarcloud.com`. Semua request adalah `GET`;
tidak ada yang menulis, mengubah, atau menghapus apa pun di akunmu.

Dibuat karena dashboard SinarCloud tidak menyediakan endpoint billing untuk
API key. Satu-satunya kredensial yang bisa dipakai adalah **cookie sesi**.

```
$ ./sinar.py

Saldo          : IDR 18,292
Rata-rata/hari : IDR 3,277
Bulan berjalan : IDR 18,418
Proyeksi bulan : IDR 100,788
Sisa bertahan : 5.6 hari  ⚠️  SALDO MENIPIS

Request 5 hari : 1,681
Token          : masuk 245,101,883 / keluar 1,077,933
Total terpakai : IDR 18,418

Token credits  : tidak ada (total 0)
```

---

## Quick start

Butuh **Python 3.9+**. Tanpa dependensi — stdlib saja.

```bash
git clone https://github.com/dongpetguangva/sc-api.git sinarcloud
cd sinarcloud

./import_cookie.py     # tempel cURL dari DevTools, Enter, lalu Ctrl-D
./sinar.py --check     # pastikan sesi hidup
./sinar.py             # ringkasan
```

### Ambil cookie-nya (sekali per sesi)

1. Login ke <https://console.sinarcloud.com>
2. Tekan **F12** → tab **Network**
3. Refresh halaman (**F5**)
4. Klik request apa pun ke `console-api.sinarcloud.com` — biasanya `csrf` atau `me`
5. Klik kanan → **Copy** → **Copy as cURL**
6. Jalankan `./import_cookie.py`, tempel, **Enter**, lalu **Ctrl-D**

Ketiga format cURL didukung: bash/Linux (`-b '...'`), macOS, dan Windows `cmd`
(yang penuh `^"` dan `^%^22` — biasanya dari Chrome Windows).

Cookie disimpan di `~/.config/sinarcloud/cookies.txt` dengan permission `600`.
Tidak dikirim ke mana pun selain `console-api.sinarcloud.com`.

---

## Perintah

| Perintah | Fungsi |
|---|---|
| `./sinar.py` | Ringkasan: saldo, runway, pemakaian, token credits |
| `./sinar.py --days 7` | Jendela 7 hari (pilihan: `7` atau `30`) |
| `./sinar.py --daily` | Tabel pemakaian per hari |
| `./sinar.py --models` | Tabel biaya per model |
| `./sinar.py --json` | JSON mentah dari semua endpoint |
| `./sinar.py --check` | Verifikasi cookie masih hidup |
| `./sinar.py --watch 3` | Mode cron: diam kalau aman, bicara kalau runway < 3 hari |

Override lokasi cookie: `SINAR_COOKIE_FILE=/path/lain ./sinar.py`

---

## Pantau otomatis (opsional)

`--watch` sengaja hanya mengeluarkan output saat saldo menipis, jadi cocok
untuk cron tanpa spam:

```bash
# cek tiap 6 jam; kirim ke Discord hanya kalau runway < 3 hari
0 */6 * * * cd ~/sinarcloud && ./sinar.py --watch 3 | \
  xargs -r -I{} curl -s -H "Content-Type: application/json" \
  -d "{\"content\":\"{}\"}" "$DISCORD_WEBHOOK_URL" >/dev/null
```

Atau simpan ke log:

```bash
0 7 * * * cd ~/sinarcloud && ./sinar.py >> ~/.local/state/sinar-usage.log 2>&1
```

Satu hal yang perlu diketahui: **cookie akan kedaluwarsa**. SinarCloud tidak
punya refresh token (diverifikasi — `refresh_token` dan `expiresIn` nol
kemunculan di bundle frontend), dan satu respons 401 langsung memicu logout di
dashboard. Kalau `--check` mulai gagal, ulangi `import_cookie.py` (±30 detik).

---

## Kenapa tidak pakai API key?

Sudah dicoba, tidak bisa:

- `console-api.sinarcloud.com` menolak API key di semua endpoint (401).
  Filter auth-nya jalan **sebelum** routing, jadi path yang tidak ada pun
  balas 401, bukan 404.
- `ai.sinarcloud.com` (host inference) tidak punya endpoint billing sama sekali:
  `/v1/dashboard/billing/subscription`, `/v1/dashboard/billing/usage`,
  `/v1/usage`, `/v1/credits`, `/v1/auth/key` → semuanya 404
  `inference endpoint is not supported`.

Login juga tidak bisa diotomasi: form sign-in dilindungi Cloudflare Turnstile,
dan di Chromium headless widget-nya tidak pernah mengeluarkan token.

---

## API yang dipakai

Base: `https://console-api.sinarcloud.com` · header wajib `API-Version: 1.0`
· sesi lewat cookie · `X-XSRF-TOKEN` dari `/api/auth/bff/csrf` hanya untuk
request non-GET (skrip ini tidak melakukannya).

| Path | Isi |
|---|---|
| `GET /api/auth/bff/me` | identitas, organisasi, timezone |
| `GET /api/wallet/current` | `availableBalance`, `reservedBalance`, `currency` |
| `GET /api/ai/usage/overview` | total & harian: request, token |
| `GET /api/ai/usage/dashboard?days=7\|30` | totals + `daily[]` + `recentRequests[]` |
| `GET /api/ai/usage/reports?days=7\|30` | `forecast`, `modelPerformance[]`, `spending`, `promotionSavings` |
| `GET /api/ai/credits/grants?page=&size=` | grant token credit |
| `GET /api/ai/credits/ledger?page=&size=` | mutasi token credit |
| `GET /api/auth/bff/csrf` | bootstrap CSRF (satu-satunya tanpa sesi) |

Bentuk data yang perlu diketahui:

- Uang selalu objek `{ "amount": "18113.60", "currency": "IDR" }`, bukan angka.
- `runwayDays` ada di `reports.forecast`, bukan di dashboard.
- API **tidak** menyediakan biaya per hari; `overview.daily` hanya berisi
  request dan token. `--daily` menampilkan itu apa adanya dan tidak mengarang
  alokasi biaya.

---

## Batas & etika

- Read-only. Skrip tidak pernah memanggil endpoint yang mengubah state.
- Cookie adalah kredensial penuh akunmu — jangan di-commit, jangan dibagikan.
  `.gitignore` sudah menutup `cookies.txt`, `.env`, dan `*.cookie`.
- Kalau dipakai bersama, tiap orang pakai cookie-nya sendiri. Jangan satu
  cookie untuk banyak orang.
- Ini klien tidak resmi. Endpoint bisa berubah kapan saja tanpa pemberitahuan;
  kalau itu terjadi, `--json` adalah cara tercepat melihat bentuk data baru.

---

## Troubleshooting

| Gejala | Sebab & solusi |
|---|---|
| `cookie file not found` | Belum pernah menjalankan `import_cookie.py`. |
| `PERINGATAN: tidak ada cookie *SESSION*` | Meng-copy request dari `console.sinarcloud.com`, bukan `console-api.sinarcloud.com`. Ulangi langkah 4. |
| `HTTP 401 — session cookie missing or expired` | Sesi habis. Login lagi, import ulang. |
| Token credits `tidak ada` | Akun memang tidak punya grant aktif. Bukan error. |
| `--daily` tanpa kolom biaya | Normal — API tidak menyediakan biaya per hari. |

---

Lisensi MIT. Tidak berafiliasi dengan SinarCloud.