# Sistem Informasi Arsip Surat Digital

Prototipe sistem arsip surat digital berbasis web untuk kantor desa.

## Fitur utama
- Login admin/petugas
- Upload surat PDF/gambar
- OCR sederhana dan ekstraksi metadata
- Klasifikasi otomatis surat
- Arsip digital dengan pencarian kata kunci, kategori, dan rentang tanggal
- Dashboard statistik dan laporan dengan filter periode
- Ekspor detail dan ringkasan laporan ke Excel
- Riwayat aktivitas admin untuk perubahan arsip
- Backup database dan file arsip dalam satu file ZIP
- Manajemen akun admin/petugas dengan status aktif dan reset password
- Tempat sampah arsip dengan pemulihan dan penghapusan permanen oleh admin

## Cara menjalankan
1. Buat environment virtual dan install dependency:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Jalankan aplikasi:
   ```bash
   python app.py
   ```
3. Buka aplikasi di browser: http://localhost:5000/

## Kredensial default
- Admin: admin / admin123
- Petugas: petugas / petugas123
- Ganti password setelah login melalui menu **Ubah Password**. Password baru minimal 12 karakter.

## Konfigurasi keamanan
Untuk instalasi baru, atur variabel berikut sebelum menjalankan aplikasi:
- `FLASK_SECRET_KEY`: nilai acak panjang untuk menandatangani session.
- `FLASK_DEBUG`: default `0`; hanya aktifkan `1` untuk pengembangan lokal.
- `FLASK_HOST`: default `127.0.0.1`; gunakan `0.0.0.0` hanya jika memang perlu menerima koneksi dari perangkat lain di jaringan.
- `TESSDATA_DIR`: lokasi traineddata Tesseract; default folder `tessdata` di dalam project.
- `ARCHIVE_ADMIN_PASSWORD`: password awal akun admin.
- `ARCHIVE_STAFF_PASSWORD`: password awal akun petugas.

Di PowerShell, contoh pengaturan untuk terminal saat ini:
```powershell
$env:FLASK_SECRET_KEY = "ganti-dengan-secret-acak-yang-panjang"
$env:FLASK_DEBUG = "0"
$env:FLASK_HOST = "127.0.0.1"
$env:ARCHIVE_ADMIN_PASSWORD = "password-admin-awal-yang-kuat"
$env:ARCHIVE_STAFF_PASSWORD = "password-petugas-awal-yang-kuat"
```
Kredensial awal hanya dipakai saat akun dibuat pertama kali. Aplikasi menyimpan password sebagai hash, bukan teks biasa.

## Audit dan backup
- Admin membuka **Manajemen Pengguna** untuk membuat akun, mengubah peran/status, atau mereset password. Password awal minimal 12 karakter.
- Penghapusan arsip satuan maupun pemindahan massal hanya memindahkan arsip ke **Tempat Sampah**. Admin dapat memulihkan arsip atau menghapusnya permanen; file baru dihapus ketika purge permanen dilakukan.
- Admin membuka **Riwayat Aktivitas** untuk melihat hingga 500 aktivitas terbaru.
- Admin memilih **Unduh Backup** untuk mengunduh ZIP berisi `archive.db` dan file yang terhubung ke arsip.
- Untuk pemulihan, hentikan aplikasi, ekstrak ZIP di luar folder proyek sebagai pemeriksaan, lalu salin `archive.db` dan isi folder `uploads` ke folder proyek setelah membuat salinan data saat ini. Jalankan kembali aplikasi.
- Simpan backup di lokasi terpisah dari komputer/server aplikasi.

## Keamanan upload dan formulir
- Formulir yang mengubah data dilindungi token CSRF.
- Upload dibatasi maksimal 16 MB dan menerima PDF, PNG, JPG, atau JPEG dengan signature file yang sesuai.
- Nama file penyimpanan dibuat unik agar file bernama sama tidak menimpa arsip sebelumnya.

## Bahasa OCR
- Traineddata `ind` dan `eng` tersedia di folder `tessdata` project; OCR otomatis memakai keduanya.
- Untuk instalasi Tesseract baru, tetap pasang engine Tesseract. Folder model dapat dipindah dan diarahkan dengan `TESSDATA_DIR`.
- Jika data bahasa Indonesia belum terpasang, aplikasi tetap memakai OCR bahasa Inggris sebagai fallback.

## Catatan
Pada lingkungan tanpa tesseract atau library OCR, sistem tetap dapat menyimpan dokumen dan mengekstraksi metadata dari teks yang tersedia.
