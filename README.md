# BLINK V5 — Repository GitHub

Kode utama website BLINK V5. Foto menggunakan jalur AI lokal yang tersedia; **Video Studio menggunakan filter warna non-AI**. Live Photo tetap terpisah.

## Unggah ke GitHub

1. Ekstrak ZIP ini. **Unggah isi foldernya**, bukan file ZIP dan bukan folder pembungkus.
2. Pastikan `docs/`, `backend/`, `frontend/`, `qa/`, `scripts/`, `.github/`, `.env.example` dan `docker-compose.yml` berada di akar repository. Jangan unggah `.env`, password, token, atau bukti transfer pelanggan.
3. Pada repository GitHub, buka **Settings → Pages → Build and deployment → Source: GitHub Actions**. Branch utama: `main`.
4. Pada tab **Actions**, periksa workflow **BLINK — Verify and Deploy GitHub Pages**. Halaman statis publik dibuat dari `docs/`.
5. Untuk login, registrasi, QRIS manual dan admin nyata, **backend FastAPI + database dan panel Next.js harus di-host terpisah**. GitHub Pages tidak menjalankan backend.
6. Di **Settings → Secrets and variables → Actions → Variables**, atur `BLINK_API_BASE_URL` (origin HTTPS backend, contoh `https://api.domain.com`) dan `BLINK_ADMIN_URL` (origin HTTPS dashboard admin). Jangan menaruh password sebagai Actions variable publik.
7. Periksa website publik dan uji registrasi, pemrosesan media, serta transaksi QRIS manual dengan dana masuk yang diverifikasi admin sebelum mengaktifkan fitur berbayar.

## Lokasi kode

- `docs/` — website publik, Foto AI, Video Filter non-AI, Live Photo, aset QRIS.
- `backend/` — API, pembayaran QRIS manual, akun, database, unit tests.
- `frontend/` — dashboard server/admin.
- `.github/workflows/blink.yml` — tes dan deployment GitHub Pages.
- `qa/` dan `scripts/` — tes wajib dan alat build CI.
- `infra/ai-models/` — placeholder model AI server (model/binary belum termasuk).

## Perhatian

**ZIP ini adalah source code bersih, bukan bukti semua layanan sudah aktif di internet.** Website statis bisa dipublikasikan melalui Pages; layanan akun, admin, QRIS, dan AI server memerlukan hosting dan pengaturan tersendiri. Model CNN lokal ringan bukan jaminan pemulihan blur berat. Untuk menjalankan tes lokal, lihat `.github/workflows/blink.yml`.
