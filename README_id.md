<p align="center">
  <a href="README.md">English</a> | <a href="README_zh.md">中文</a> | <a href="README_ja.md">日本語</a> | <a href="README_ko.md">한국어</a> | <a href="README_ar.md">العربية</a> | <a href="README_es.md">Español</a> | <b>Bahasa Indonesia</b>
</p>

<p align="center">
  <img src="assets/icon.png" width="120" alt="Logo Vibe-Trading"/>
</p>

<h1 align="center">Vibe-Trading: Agent Trading Pribadi Anda</h1>

<p align="center">
  <b>Satu Perintah untuk Membekali Agent Anda dengan Kapabilitas Trading yang Lengkap</b>
</p>

<p align="center">
  <a href="https://www.star-history.com/HKUDS/Vibe-Trading"><img src="https://api.star-history.com/badge?repo=HKUDS/Vibe-Trading&amp;type=trending" height="55" alt="Star History: GitHub Trending"/></a>
  <a href="https://trendshift.io/repositories/25527"><img src="https://trendshift.io/api/badge/trendshift/repositories/25527/daily" height="55" alt="Trendshift: daily ranking"/></a>
  <a href="https://www.star-history.com/HKUDS/Vibe-Trading"><img src="https://api.star-history.com/badge?repo=HKUDS/Vibe-Trading" height="55" alt="Star History: global star ranking"/></a>
</p>

<p align="center">
  <b>Peringkat topik GitHub menurut jumlah bintang</b> · 4 November 2026<br>
  <a href="https://github.com/search?q=topic%3Abacktesting&amp;type=repositories&amp;s=stars&amp;o=desc">#1 Backtesting</a> &nbsp;·&nbsp;
  <a href="https://github.com/search?q=topic%3Aalgorithmic-trading&amp;type=repositories&amp;s=stars&amp;o=desc">#3 Trading algoritmik</a> &nbsp;·&nbsp;
  <a href="https://github.com/search?q=topic%3Aquantitative-finance&amp;type=repositories&amp;s=stars&amp;o=desc">#4 Keuangan kuantitatif</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Backend-FastAPI-009688?style=flat" alt="FastAPI">
  <img src="https://img.shields.io/badge/Frontend-React%2019-61DAFB?style=flat&logo=react&logoColor=white" alt="React">
  <a href="https://pypi.org/project/vibe-trading-ai/"><img src="https://img.shields.io/pypi/v/vibe-trading-ai?style=flat&logo=pypi&logoColor=white" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=flat" alt="License"></a>
  <br>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat-square&logo=feishu&logoColor=white" alt="Feishu"></a>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat-square&logo=wechat&logoColor=white" alt="WeChat"></a>
  <a href="https://discord.gg/6TdQnT5xcF"><img src="https://img.shields.io/badge/Discord-Join-7289DA?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
</p>

<p align="center">
  <a href="https://vibetrading.wiki/">Situs</a> &nbsp;&middot;&nbsp;
  <a href="https://vibetrading.wiki/docs/">Dokumentasi</a> &nbsp;&middot;&nbsp;
  <a href="#-berita">Berita</a> &nbsp;&middot;&nbsp;
  <a href="#-fitur-utama">Fitur utama</a> &nbsp;&middot;&nbsp;
  <a href="#akun-dan-transaksi">Akun bayangan</a> &nbsp;&middot;&nbsp;
  <a href="#-demo">Demo</a> &nbsp;&middot;&nbsp;
  <a href="#-mulai-cepat">Mulai cepat</a> &nbsp;&middot;&nbsp;
  <a href="#-contoh">Contoh</a> &nbsp;&middot;&nbsp;
  <a href="#-server-api">API / MCP</a> &nbsp;&middot;&nbsp;
  <a href="#-peta-jalan">Peta jalan</a> &nbsp;&middot;&nbsp;
  <a href="#kontributor">Kontributor</a>
</p>

<p align="center">
  <a href="#-mulai-cepat"><img src="assets/pip-install.svg" height="45" alt="pip install vibe-trading-ai"></a>
</p>

## 📰 Berita

- **2026-11-12** 🛠️ **Perbaikan waktu eksekusi, angka laporan, dan status riset** — Akun bayangan memakai modal awal yang diminta; respons worker yang terpotong oleh batas token tidak lagi dianggap selesai. PM komite dapat menyintesis laporan hulu yang valid tanpa mengambil ulang data. Adaptor Anthropic native memakai batas keluaran default 16.384 token yang dapat diubah.
  Strategi yang dihasilkan menolak pergeseran tambahan yang terdeteksi pada target keluaran kecuali dinyatakan sebagai penundaan yang disengaja; lookback indikator tetap diizinkan. Grounding mendukung variasi penulisan satuan besaran dan deklarasi nilai observasi yang presisi tanpa melonggarkan pemeriksaan bukti. Backtest SPY/GLD cocok dengan pembukuan independen untuk seluruh 206/140 eksekusi dan imbal hasil total. **Belum dirilis.**

- **2026-11-11** 🧾 **Eksekusi parsial pada simulasi perdagangan dan rekonsiliasi buku besar** — Aktifkan secara opsional batas volume per order, eksekusi parsial, dan keluaran status order untuk simulasi saham A Tiongkok dengan bar lima menit ([#2128](https://github.com/HKUDS/Vibe-Trading/pull/2128)). Tool Agent/MCP baru `paper_trade_reconcile` merekonsiliasi biaya, kas, posisi, dan perhitungan nilai aset bersih secara independen berdasarkan catatan eksekusi yang dikembalikan ([#2197](https://github.com/HKUDS/Vibe-Trading/pull/2197)).
  Format header persentase beberapa baris yang didukung serta kutipan eksplisit bilangan bulat dari dokumen kini ditangani dengan benar, dengan tetap mempertahankan label aslinya ([#2185](https://github.com/HKUDS/Vibe-Trading/pull/2185), [#2192](https://github.com/HKUDS/Vibe-Trading/pull/2192)). Juga memperbaiki input benchmark faktor ketat ([#2195](https://github.com/HKUDS/Vibe-Trading/pull/2195)) dan mencegah giliran percakapan melalui kanal mengembalikan jawaban sebelumnya saat waktu tunggu habis ([#2194](https://github.com/HKUDS/Vibe-Trading/pull/2194)).
  Terima kasih [@shadowinlife](https://github.com/shadowinlife), [@he-yufeng](https://github.com/he-yufeng), [@Jackzigen](https://github.com/Jackzigen), dan [@divya0795](https://github.com/divya0795)! **Tersedia di `main` untuk rilis pip berikutnya.**

- **2026-11-10** 📊 **Permukaan IV interaktif dan perbaikan analisis opsi** — Edit grid IV berdasarkan harga kesepakatan dan jatuh tempo di Options Lab, dengan penanda nilai observasi/interpolasi dan tanpa ekstrapolasi ([#2186](https://github.com/HKUDS/Vibe-Trading/pull/2186)).
  Memperbaiki preset untuk aset berharga rendah, kuantitas, tanggal jatuh tempo, percobaan ulang, pemuatan yang macet saat bahasa diganti, serta batas 20 kaki opsi. Kode kontrak Zhengzhou dengan bagian jatuh tempo tiga digit seperti `CF501` kini menggunakan aturan futures Tiongkok dalam backtest ([#2193](https://github.com/HKUDS/Vibe-Trading/pull/2193)).
  Terima kasih [@he-yufeng](https://github.com/he-yufeng) dan [@GPT-AGI](https://github.com/GPT-AGI)! **Tersedia di `main` untuk rilis pip berikutnya.**

- **2026-11-09** 🧭 **Ekspor perbandingan revisi yang dipilih; backtest menolak kode yang tidak dikenali** — Unduh pasangan revisi riset yang sedang Anda bandingkan sebagai JSON atau Markdown dari Web, API, atau CLI ([#2189](https://github.com/HKUDS/Vibe-Trading/pull/2189)). Kode backtest yang tidak dikenali aturan pasar mana pun (seperti `local:BHP.AX` atau `7203.T`) kini ditolak sebelum data diambil, alih-alih dijalankan dengan aturan saham A Tiongkok; kode enam digit dan penulisan `.SS` Shanghai tetap berfungsi. Balasan OpenRouter tidak lagi menampilkan nama model dua kali ([#2191](https://github.com/HKUDS/Vibe-Trading/pull/2191)), dan id revisi kosong pada `research-artifact export` kini menjadi galat. Terima kasih [@he-yufeng](https://github.com/he-yufeng) dan [@Gloubiboulgator](https://github.com/Gloubiboulgator)! **Tersedia di `main` untuk rilis pip berikutnya.**

<details>
<summary>Berita sebelumnya</summary>

- **2026-11-08** 📝 **Perbandingan revisi riset dan ekspor seluruh riwayat** — Bandingkan isi, bukti, dan metadata antara dua revisi mana pun ([#2168](https://github.com/HKUDS/Vibe-Trading/pull/2168)), lalu ekspor seluruh riwayat riset sebagai JSON atau Markdown ([#2170](https://github.com/HKUDS/Vibe-Trading/pull/2170)). Saat berpindah catatan riset, respons lama diabaikan; ekspor Markdown mempertahankan isi asli dalam blok kode terpisah. Juga diperbaiki: bobot faktor yang hilang, atribusi saat sebagian imbal hasil tidak tersedia, sampel IC yang tidak cukup, input valuasi tidak berhingga, serta perhitungan margin untuk harga masuk negatif. **Tersedia di `main` untuk rilis pip berikutnya.**

- **2026-11-07** 🧪 **Research Lab: biaya perdagangan dan validasi di luar sampel** — Jalankan ulang backtest dengan data harga tersimpan, biaya, dan slippage yang berbeda. Parameter dipilih hanya dari hasil pelatihan, lalu dikunci untuk pengujian di luar sampel dan pengujian akhir pada data terpisah yang disisihkan. [Research Lab](guides/research-lab.md) memakai alur yang sama di Web, CLI, API, dan Agent/MCP, dengan dukungan kesebelas bahasa antarmuka. Perhitungan imbal hasil di batas jendela, masa inisialisasi faktor, dan jendela panjang juga diperbaiki. Ditambahkan 20 kasus verifikasi ulang tugas tersimpan secara luring yang menampilkan bukti yang belum tersedia. Catatan riset berversi kini dapat menyimpan fakta keuangan terstruktur ([#2164](https://github.com/HKUDS/Vibe-Trading/pull/2164)), dan pengenalan kode kontrak berjangka Tiongkok tanpa akhiran bursa diperbaiki ([#2177](https://github.com/HKUDS/Vibe-Trading/pull/2177)). **Tersedia di `main` untuk rilis pip berikutnya.**

- **2026-11-06** 📈 **Grid volatilitas tersirat dan perbaikan simulasi perdagangan** — Susun grid IV berdasarkan harga pelaksanaan dan waktu jatuh tempo dari observasi opsi yang diberikan, dengan penanda titik observasi/interpolasi dan tanpa ekstrapolasi ([#2172](https://github.com/HKUDS/Vibe-Trading/pull/2172)). Input numerik ekstrem kini menghasilkan nilai berhingga atau kesalahan yang jelas. Dalam simulasi saham A per lima menit, order pasar yang terhalang batas harga langsung dibatalkan ([#2176](https://github.com/HKUDS/Vibe-Trading/pull/2176)); mesin juga memproses simbol secara kronologis agar hasil penjualan di waktu berikutnya tidak membiayai pembelian sebelumnya. **Tersedia di `main` untuk rilis pip berikutnya; permintaan publik lima menit tetap dibatasi satu simbol per langkah.**

- **2026-11-05** 🚀 **v0.1.19 dirilis** ([Catatan rilis](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.19), `pip install -U vibe-trading-ai`): riset yang bertahan melampaui obrolan — simpan artefak riset berversi beserta buktinya lalu revisi, gunakan kembali backtest dari giliran dan sesi sebelumnya, dan sunting tujuan riset di tempat. Fitur opsional baru: simulasi saham A per lima menit, serta kueri keuangan, seleksi saham, dan diagnosis portofolio Shannon dari Gildata (QVeris dihapus; `GILDATA_TOKEN` yang sudah ada kini tidak lagi mengaktifkan apa pun dengan sendirinya). Juga backtest Argentina (BYMA), pencarian web Parallel, penemuan model lewat Codex OAuth, dan perbaikan kedua regresi 0.1.18. 116 pull request digabung ditambah 21 yang masuk lewat commit maintainer, dari 26 kontributor ([CHANGELOG](CHANGELOG.md)).
  **Diperbaiki hari ini:** backtest melaporkan tolok ukur yang benar-benar dievaluasinya, portofolio long/short mendapat risk x-ray, alfa GTJA 17 tetap kosong selama inputnya masih dalam masa pemanasan, panel Shannon tersedia dalam kesebelas bahasa antarmuka, dan dua perbaikan kontributor yang sudah ditinjau tetapi belum masuk kini disertakan ([#2042](https://github.com/HKUDS/Vibe-Trading/pull/2042) jumlah TTM yang melintasi kuartal yang hilang, [#1985](https://github.com/HKUDS/Vibe-Trading/pull/1985) deteksi pemecahan saham 3:2). Terima kasih [@rudycelekli](https://github.com/rudycelekli), [@he-yufeng](https://github.com/he-yufeng), [@Jackzigen](https://github.com/Jackzigen), [@Shizoqua](https://github.com/Shizoqua), [@cgycorey](https://github.com/cgycorey), [@dajiaohuang](https://github.com/dajiaohuang), [@zeus229](https://github.com/zeus229), [@alexwan02](https://github.com/alexwan02), [@BHhhh-123](https://github.com/BHhhh-123), [@remote-controlled-man](https://github.com/remote-controlled-man), [@shadowinlife](https://github.com/shadowinlife), [@TWJxi](https://github.com/TWJxi), [@lishuanghong1989-netizen](https://github.com/lishuanghong1989-netizen), [@TerryF7](https://github.com/TerryF7), [@davidalmeida90](https://github.com/davidalmeida90), [@DrDLyuan](https://github.com/DrDLyuan), [@goatyyc](https://github.com/goatyyc), [@hnq-ai](https://github.com/hnq-ai), [@kadyrbekovhamit-cyber](https://github.com/kadyrbekovhamit-cyber), [@MetaAviator](https://github.com/MetaAviator), [@octo-patch](https://github.com/octo-patch), [@RowanAldean](https://github.com/RowanAldean), [@VectorPeak](https://github.com/VectorPeak), [@wavebyrd](https://github.com/wavebyrd) dan [@yufengsika](https://github.com/yufengsika)!
  **Diperbaiki di main setelah rilis (masuk rilis pip berikutnya):** benchmark backtest kini dibeli pada harga pembukaan bar evaluasi pertama, sama seperti strategi, bukan dari harga penutupan terakhir masa pemanasan; excess return tidak lagi memuat pergerakan itu (contoh AAPL SMA 20/60: 22,5% → 18,4%).

- **2026-11-04** 📊 **Kueri keuangan, seleksi saham, dan diagnosis portofolio Shannon dengan Gildata** — Satu kueri dapat menampilkan tiga saham dengan kapitalisasi pasar terbesar beserta pendapatan semesterannya. Shannon menunjukkan eksposur portofolio terhadap sepuluh faktor dan kontribusi tiap posisi terhadap volatilitas. Kesembilan fitur harus diaktifkan satu per satu, termasuk jika token sudah tersimpan. Jika sumber gratis gagal, sistem tidak beralih ke Gildata. [#2117](https://github.com/HKUDS/Vibe-Trading/pull/2117) · [#2118](https://github.com/HKUDS/Vibe-Trading/pull/2118) · [#2119](https://github.com/HKUDS/Vibe-Trading/pull/2119)
  Panduan backtest kini menjelaskan bahwa sinyal dieksekusi pada harga pembukaan bar berikutnya. Deteksi batas waktu Swarm juga diperbaiki dan pemeriksaan duplikat riset dipercepat. [#2137](https://github.com/HKUDS/Vibe-Trading/pull/2137) · [#2155](https://github.com/HKUDS/Vibe-Trading/pull/2155) · [#2159](https://github.com/HKUDS/Vibe-Trading/pull/2159)

- **2026-11-03** 🛠️ **Integritas catatan dan bahasa**. Jejak eksekusi, buku audit, dan pencarian sesi mempertahankan U+2028/U+2029 dalam JSONL sehingga entri berikutnya tetap valid. Nama model bergaris bawah dinormalkan dan ringkasan serah terima dipertahankan saat pemadatan lapis kedua. Metadata dengan BOM serta tata letak kanan ke kiri didukung dan uji regresi ditambahkan.

- **2026-11-02** 🛠️ **Metadata dan hasil berukuran besar**. Nilai skalar bertanda kutip dibaca dengan benar. Hasil yang terlalu besar untuk dikodekan dipotong agar tetap terbaca. Tata letak sambutan dan kartu pilihan disesuaikan serta diuji.

- **2026-11-01** 🛠️ **Waktu sesi dan halaman sambutan**. Pembaruan sesi dicatat dalam UTC. Tombol utama lebih terbaca pada mode gelap. Contoh di panel samping bisa diklik dan diberi kategori yang jelas. Uji regresi ditambahkan.

- **2026-10-31** 🛠️ **Halaman awal dan kode saham**. Tata letak dua kolom bernuansa kertas hangat memperjelas contoh dan tindakan di panel. Huruf di akhir simbol tidak lagi dianggap sebagai batasan saham A atau A/H.

[Arsip berita](guides/news.md) · [Riwayat perubahan](CHANGELOG.md)

</details>

## ✨ Fitur utama

<div align="center">
<a href="assets/features/id/feature-market-research-card.svg"><img src="assets/features/id/feature-market-research-card.svg" width="50%" alt="🔍 Riset pasar · Telusuri harga, laporan emiten, dan isi portofolio ETF · Nilai perusahaan lewat DCF dan kelipatan pembanding · Pantau laba dan jadwalkan ringkasan sebelum pasar buka"/></a><a href="assets/features/id/feature-research-teams-card.svg"><img src="assets/features/id/feature-research-teams-card.svg" width="50%" alt="🐝 Tim riset · 30 tim untuk saham, kuantitatif, kripto, dan risiko · Tinjau tesis optimistis, pesimistis, dan penilaian risiko · Bagikan tugas riset di Pixel Office"/></a><br/>
<a href="assets/features/id/feature-quant-lab-card.svg"><img src="assets/features/id/feature-quant-lab-card.svg" width="50%" alt="📊 Lab kuantitatif · Bandingkan 478 alfa dari lima pustaka · Uji strategi lintas pasar dan di luar sampel · Modelkan imbal hasil opsi, Greeks, dan risiko portofolio"/></a><a href="assets/features/id/feature-trading-portfolio-card.svg"><img src="assets/features/id/feature-trading-portfolio-card.svg" width="50%" alt="👥 Trading dan portofolio · 19 konektor dengan izin khusus per broker · Pantau eksekusi simulasi dan batasi transaksi riil · Putar ulang aturan trading sendiri di akun bayangan"/></a>
</div>

## 💡 Apa itu Vibe-Trading?

Ubah pertanyaan keuangan menjadi laporan riset, backtest yang dapat dijalankan, dan portofolio simulasi. Anda dapat memberi mandat kepada broker yang didukung untuk bertransaksi sesuai batas yang Anda tetapkan dan menghentikannya kapan saja. Dana tetap berada di broker.

## ✨ Yang dapat Anda lakukan

| Tugas | Mulai dari |
|---|---|
| Meneliti pasar atau dokumen | Tanyakan lewat chat web atau [lampirkan laporan](guides/research.md#upload--analyze-documents). |
| Menguji strategi atau alfa | Periksa grafik dan transaksi di Run Detail atau bandingkan faktor di `/alpha-zoo`. |
| Simulasi dan evaluasi transaksi | Pantau eksekusi harian dan nilai aset bersih di `/paper-trading`. Gunakan `/journal` dan `/shadow` di CLI untuk evaluasi. |
| Menggabungkan akun atau membandingkan alokasi | Buka `/portfolio` untuk melihat posisi dan usulan alokasi. [Dukungan broker](#dukungan-broker) |
| Meneliti opsi dan korelasi | Buka `/options` untuk profil laba rugi dan Greeks strategi multikaki, atau `/correlation` untuk kondisi pasar. |
| Mengatur riset berulang | Jalankan [tim Swarm](guides/research.md#swarm-workflows), bagikan tugas di Pixel Office, atau jadwalkan laporan di `/scheduled`. |
| Meninjau bukti riset | Cari [riwayat riset bertanggal](guides/research.md#versioned-research-artifacts) di `/research-artifacts`, bandingkan dua revisi, dan ekspor seri lengkap atau perbandingan terpilih sebagai JSON atau Markdown. |

## ⚡ Contoh singkat

Setelah menjalankan `vibe-trading init`, minta backtest dalam bahasa sehari-hari atau uji pustaka alfa dari terminal.

```bash
vibe-trading run -p "Uji strategi persilangan rata-rata bergerak 20 dan 50 periode pada BTC-USDT selama 2024. Bandingkan dengan beli dan tahan, lalu laporkan penurunan maksimum."
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

Buka **Run Detail** untuk membandingkan hasil dengan beli dan tahan, meninjau transaksi saat penurunan, dan memeriksa sumber data pada kartu eksekusi.

## 🧪 Alur riset

| Tahap | Contoh persilangan rata-rata |
|---|---|
| Rencanakan | Tentukan pasangan, rentang tanggal, rata-rata bergerak, dan tolok ukur dari pertanyaan. |
| Siapkan data | Ambil data kandil historis BTC-USDT dan periksa sumber serta tanggalnya. |
| Jalankan | Tulis strategi lalu jalankan backtest. Direktori hasil menyimpan strategi, transaksi, dan kurva ekuitas. |
| Validasi | Bandingkan dengan beli dan tahan. Periksa perputaran, penurunan, dan peringatan validasi bersama imbal hasil. |
| Tinjau kembali | Buka hasil tersimpan atau ubah parameter. Anda juga dapat menyimpan kesimpulan bertanggal dan merevisinya ketika ada bukti baru. |

## 📡 Sumber data dan peralihan otomatis

Tersedia **28 sumber data pasar**. Dengan `source: "auto"`, sistem mengenali pasar dari simbol dan mencoba sumber sesuai urutan konfigurasi.

| Pasar | Urutan sumber |
|---|---|
| Saham A dan Hong Kong | Mulai dari Tencent. Jika kandil tidak tersedia, coba Eastmoney lalu sumber lain untuk pasar tersebut. |
| Saham AS | Mulai dari Yahoo, kemudian Stooq dan Sina. |
| Kripto | Coba OKX, Binance, dan CCXT sebelum sumber lain. |
| Kontrak berjangka | Gunakan AKShare atau data lokal untuk kontrak Tiongkok. Sediakan data lokal untuk kontrak global. |

Anda juga dapat memilih sumber tertentu. Instal `vibe-trading-ai[ashare]` untuk mengambil data harian saham A dari BaoStock tanpa token. Lihat [referensi sumber data](guides/capabilities.md#-data-sources--smart-fallback) untuk urutan lengkap dan persyaratan kredensial.

## 🔩 Rincian fitur

### Riset pasar

| Fitur | Kegunaan |
|---|---|
| Laporan dan kepemilikan | Bandingkan posisi manajer investasi antartriwulan melalui SEC 13F atau lihat aset dasar ETF. Setiap laporan memuat tanggal pelaporan. |
| Valuasi perusahaan | Uji tingkat diskonto dan pertumbuhan terminal dengan `/dcf`, bandingkan kelipatan dengan `/comps`, atau ekspor model tiga laporan keuangan terpadu ke Excel. |
| Makalah dan dokumen | Cari sinyal di arXiv dan OpenAlex, periksa definisi penulis, lalu uji pada himpunan aset sendiri. Unggah laporan, lembar kerja, atau slide untuk menanyakan tabel tertentu. |
| Penyaringan saham | Aktifkan Gildata untuk menyaring menurut kapitalisasi dan mengambil pendapatan semesteran sekaligus. Penyaringan dan diagnosis faktor portofolio diaktifkan terpisah. |

### Riset kuantitatif

| Fitur | Kegunaan |
|---|---|
| Alpha Zoo | Uji sinyal Qlib, Alpha101, GTJA, serta pustaka akademis dan fundamental. Bandingkan koefisien informasi antarhorizon lalu uji dengan jendela waktu bergulir. |
| Mesin backtest | Modelkan batas harga saham A, biaya pendanaan kripto, atau margin kontrak berjangka. Gunakan modal bersama lintas pasar dan periksa setiap eksekusi. |
| Lab opsi | Susun spread per kaki, bandingkan hasil saat jatuh tempo dan Greeks, lalu uji perubahan harga spot dan volatilitas tersirat. |
| Risiko portofolio | Periksa drawdown, VaR, dan expected shortfall. Pisahkan pengaruh alokasi dan pemilihan saham lewat atribusi Brinson dan lihat perubahan korelasi pasar. |
| Pemantauan strategi | Daftarkan strategi beserta bukti dan pantau perubahan rasio Sharpe atau koefisien informasi faktor saat hasil baru masuk. |

### Akun dan transaksi

| Fitur | Kegunaan |
|---|---|
| Portofolio | Gabungkan posisi broker dalam satu snapshot hanya baca atau impor berkas extraETF. Masukkan bobot sasaran untuk memperkirakan perubahan nilai tiap posisi. |
| Trading simulasi | Majukan akun tersimpan satu hari bursa untuk melihat transaksi, kas, dan nilai aset bersih. Anda juga dapat memutar ulang sesi saham A per lima menit dalam simulasi terpisah. Alat `paper_trade_reconcile` agent/MCP memeriksa biaya, kas, posisi, dan aritmetika NAV secara independen tanpa akses pasar atau broker. |
| Akun bayangan | Impor jurnal broker, periksa biaya dan kebiasaan transaksi, lalu bandingkan hasil aktual dengan simulasi berbasis aturan. |
| Koneksi broker | Atur koneksi lewat CLI atau web dan uji dengan membaca data. Tetapkan batas simbol, order, dan eksposur sebelum transaksi riil. Tombol penghentian menghentikan aktivitas riil. |

### Tim dan riset berkala

| Fitur | Kegunaan |
|---|---|
| Swarm dan Pixel Office | Jalankan komite investasi dengan tesis berlawanan atau tim kuantitatif, lalu baca laporan anggota. Bagikan tugas dan catat hasil di papan bersama Pixel Office. |
| Laporan terjadwal | Pilih laporan prapembukaan, pelacak laba, atau pemeriksaan portofolio. Jadwalkan pengiriman ke Slack, Telegram, atau surel yang telah diatur. |
| Riwayat riset | Cari percakapan lama dan buka hasil tersimpan. Simpan kesimpulan bertanggal beserta bukti dan bandingkan revisi tesis investasi. |
| Catatan eksekusi | Periksa sumber data, model, log, dan rujukan metrik di balik backtest. Buka kembali transaksi dan kurva ekuitas untuk memeriksa angka. |

### Dukungan broker

<details>
<summary>Bandingkan akses baca, simulasi, dan transaksi riil</summary>

Baca berarti profil khusus hanya baca. Simulasi memakai sandbox broker atau simulasi lokal. Transaksi riil tunduk pada mandat. ✓ berarti dukungan dinyatakan, — berarti tidak ada profil yang sesuai.

<!-- BEGIN GENERATED broker-overview -->

| Broker | Baca | Sim. | Riil |
| --- | :---: | :---: | :---: |
| alpaca | ✓ | ✓ | ✓ |
| binance | ✓ | ✓ | ✓ |
| dhan | ✓ | ✓ | — |
| etoro | ✓ | ✓ | ✓ |
| futu | ✓ | ✓ | ✓ |
| ibkr | ✓ | — | — |
| kis | ✓ | ✓ | — |
| longbridge | ✓ | ✓ | — |
| mstock | ✓ | — | — |
| mt5 | ✓ | ✓ | ✓ |
| okx | ✓ | ✓ | ✓ |
| robinhood | ✓ | — | ✓ |
| scalable | ✓ | — | — |
| shoonya | ✓ | ✓ | — |
| tiger | ✓ | ✓ | ✓ |
| toss | ✓ | — | — |
| trading212 | ✓ | — | — |
| upbit | ✓ | ✓ | — |
| zerodha | ✓ | ✓ | — |

<!-- END GENERATED broker-overview -->

</details>

[Izin lengkap per profil](guides/portfolio-and-brokers.md#full-broker-permissions)

## 🎬 Demo

<table>
<tr><th width="50%">Web · Dari pertanyaan ke backtest</th><th width="50%">CLI · Terminal interaktif</th></tr>
<tr>
<td width="50%" valign="top">

https://github.com/user-attachments/assets/2c595ee1-c577-481a-9460-34ea12bcf41c

</td>
<td width="50%" valign="top">

https://github.com/user-attachments/assets/ac79426e-f3f7-4349-b0d5-d997a2725784

</td>
</tr>
<tr><td>Kirim permintaan strategi, ikuti pekerjaan agen, dan periksa hasilnya.</td><td>Jelajahi templat riset di terminal dan buka templat ringkasan prapasar.</td></tr>
</table>

## 🚀 Mulai cepat

Instal paket dengan Python 3.11+, pilih penyedia model melalui panduan penyiapan, lalu buka CLI interaktif.

```bash
pip install vibe-trading-ai
vibe-trading init
vibe-trading
```

Docker menyajikan web dan API di `http://localhost:8899`. Setelah mengkloning repositori, atur penyedia sebelum menjalankan kontainer.

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
cp agent/.env.example agent/.env
# Atur penyedia dan kunci API di agent/.env.
docker compose up --build
```

Paket PyPI berisi CLI, API, dan server MCP. Untuk pengembangan web atau model lokal, lihat [panduan instalasi](guides/installation.md).

## 🖥 Referensi CLI

Jalankan `vibe-trading` untuk membuka terminal. Ketik `/help` untuk menelusuri perintah.

| Perintah | Kegunaan |
|---|---|
| `/model` | Ganti penyedia atau model sesi. |
| `/history` | Telusuri dan lanjutkan percakapan lama. |
| `/show <run-id>` | Periksa hasil eksekusi tersimpan. |
| `/pine` | Ekspor strategi sebagai indikator Pine Script. |

Dari shell, `vibe-trading alpha list` menampilkan pustaka faktor dan `vibe-trading playbook list` menampilkan templat riset terjadwal.

## 💡 Contoh

- Bandingkan AAPL dan MSFT selama 2024. Bulan mana yang menyumbang selisih imbal hasil terbesar? Lanjutkan dengan `/history`.
- Gunakan `/journal` untuk menganalisis ekspor transaksi dan `/shadow` untuk membandingkannya dengan aturan alternatif.
- Pilih saham dan ikuti argumen optimistis dan pesimistis hingga laporan akhir komite.

```bash
vibe-trading --swarm-run investment_committee '{"target":"TSLA","market":"US"}'
```

## 🌐 Server API

Jalankan `vibe-trading serve --port 8899`. Di terminal lain, gunakan `curl http://localhost:8899/runs` untuk menampilkan daftar, lalu masukkan ID ke `GET /runs/{run_id}` untuk melihat hasil.

| Riset melalui HTTP | Endpoint |
|---|---|
| Buat percakapan | `POST /sessions` |
| Kirim pertanyaan | `POST /sessions/{id}/messages` |
| Ikuti perkembangan | `GET /sessions/{id}/events` |

Uji endpoint di `http://localhost:8899/docs`. [Klien terautentikasi](guides/cli-and-api.md#security-defaults) mengirim kunci API pada header `Authorization: Bearer`.

## 🔌 Plugin MCP

Klien MCP dapat menjalankan paket yang sama melalui stdio. Tambahkan entri ini ke `claude_desktop_config.json` milik Claude Desktop, mulai ulang klien, lalu panggil `list_skills`.

```json
{
  "mcpServers": {
    "vibe-trading": { "command": "vibe-trading-mcp" }
  }
}
```

Untuk klien lain atau direktori keluaran khusus, lihat [konfigurasi MCP](guides/mcp.md).

## 🏛 Ekosistem

Vibe-Trading adalah bagian dari ekosistem agent **[HKUDS](https://github.com/HKUDS)**:

<table>
  <tr>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/nanobot"><b>NanoBot</b></a><br>
      <sub>Asisten AI Pribadi Ultra-Ringan</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/AI-Trader"><b>AI-Trader</b></a><br>
      <sub>Platform Signal &amp; Copy Trading Agent-Native</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/CLI-Anything"><b>CLI-Anything</b></a><br>
      <sub>Membuat Semua Software Menjadi Agent-Native</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/OpenSpace"><b>OpenSpace</b></a><br>
      <sub>Skill Agent AI yang Berkembang Sendiri</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/ClawTeam"><b>ClawTeam</b></a><br>
      <sub>Intelligence Swarm Agent</sub>
    </td>
  </tr></table>

---

## 🗺 Peta jalan

| Bidang | Sudah tersedia | Berikutnya |
|---|---|---|
| Trading simulasi | Akun harian menyimpan kas, transaksi, dan nilai aset bersih lintas sesi. Simulasi terpisah memutar ulang sesi saham A per lima menit. | Pencocokan opsional berdasarkan porsi volume ([#2128](https://github.com/HKUDS/Vibe-Trading/pull/2128), draf). |
| Riset | Kartu eksekusi merekam metrik dan bukti backtest. Riset bertanggal menyimpan riwayat revisi dan dapat dicari. | Fakta keuangan terstruktur dalam artefak riset ([#2164](https://github.com/HKUDS/Vibe-Trading/pull/2164), sedang ditinjau). |
| Lab opsi | Profil laba rugi multikaki, Greeks, dan skenario spot × IV. | Grid permukaan volatilitas interaktif di `/options`. |

## Cara berkontribusi

Pilih [isu untuk kontributor baru](https://github.com/HKUDS/Vibe-Trading/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) atau buka isu untuk membahas perubahan besar. [Panduan kontribusi](CONTRIBUTING.md) mencakup penyiapan lokal dan pemeriksaan sebelum membuka PR.

## Kontributor

Terima kasih kepada semua orang yang telah berkontribusi pada Vibe-Trading!

### v0.1.19 · Kontributor

- @rudycelekli — 58 PRs (12 landed as maintainer ports): GTJA alpha formulas restored to the report (#2036/#2037/#2038/#2039/#2040/#2051), loaders that ask each vendor for the ticker form it serves and page at its own cap (Alpha Vantage #1997, AKShare #1998, CCXT #1999, Tushare minute lots #2001, Tiingo/Stooq class shares #2010/#2012, Nobitex Tehran days #1989, push2 decimals #1988), futures and market fees (micro index price limits #1992, the 30-year treasury fee #1994, India stamp duty on short covers #1995), quant-library and governance fixes (#1950/#1959/#1960/#1962/#1963/#2000/#2017), sub-penny prices kept in trades and charts (#1987/#1990), TTM sums that stop at a missing quarter (#2042), 3:2 splits and ST board limits in paper trading (#1985/#1984), a live halt key that cannot alias the global halt (#2003), session, memory, CLI and API fixes (#1969/#1970/#1982/#2002/#2006), and a string-"false" sweep across ten tools (#1976/#1977/#2008/#2009/#2011/#2013/#2014/#2015/#2016/#2018)
- @he-yufeng — 18 PRs (5 landed as ports): versioned research artifacts (#2079/#2159), background tasks scoped to their owner, reaped on cancel and reconciled after a restart (#2092/#2098/#2100/#2157), silent provider streams interrupted (#2099), cache and reasoning tokens kept in `llm_usage` (#2109), one tool policy across providers (#2087), Claude CLI tool-attempt recovery and structured finals (#2048/#2064/#2120), Qlib BETA/RESI/ROC/CORD semantics (#2062/#2069), magnitude suffixes in derived formulas (#2134), long/short risk x-ray and validation that refuses non-positive equity (#2162/#2161), and Unicode-safe swarm heartbeats (#2155)
- @Jackzigen — the bar-agnostic paper order lifecycle (#2066), swarm runs that stop when cancelled from the chat (#2059/#2060), document figures and percentage points in grounding (#2058/#2108), Robinhood portfolio reads with account selection (#2054), Moonshot reasoning effort for kimi-k3.1-pro (#2043), and Eastmoney JSONP, AKShare 1.20 forex and bare US ETF symbol fixes (#2082/#2083/#2086)
- @Shizoqua — research goals edited in place (#2093), Feishu, Teams, WeChat, WhatsApp and Discord channel fixes (#1957/#1958/#1967/#2078/#2114), heredoc commands in the bash tool (#2077), path-escape tests (#2094), and a run-directory fallback that no longer depends on the process cwd (#2116, landed as a port)
- @cgycorey — global futures priced on real contract multipliers and micro rates, with generic defaults reported (#1965/#1966/#1968/#1972), and a shadow account that honours every entry condition and currency (#2073/#2075)
- @dajiaohuang — transfer flow signs (#2023), aligned attribution benchmarks (#2044), overflow-free weight normalisation (#2046), and boolean payoff quantities refused (#2049)
- @zeus229 — the BYMA engine for Argentine shares and CEDEARs (#2071), backtests reused across turns and sessions (#2074), Codex OAuth model discovery (#2080), and financial units kept in grounding evidence (#2072)
- @alexwan02 — Longbridge per-currency cash (#1940), `.env` read by the MCP server (#1974), and Futu US symbol mapping (#2076)
- @BHhhh-123 — cross-sectional factor combination with walk-forward weights (#1953), field-level data availability in alpha bench (#2057), and factor research provenance (#2067)
- @remote-controlled-man — comma-grouped document integers (#2135), one bounded retry for a withheld final answer (#2136), and A-share source setup docs (#2138)
- @shadowinlife — the opt-in five-minute A-share paper step and its bar-by-bar matching (#2110/#2111), and JoinQuant limit fills (#2127, landed as a port)
- @TWJxi and @lishuanghong1989-netizen — Gildata stock discovery and financial queries (#2117), stock screening with report-period indicators (#2118), and Shannon portfolio style and risk analysis (#2119)
- @TerryF7 — IBKR and Futu gateway endpoints per connection (#1983), and connection deletion without a credential vault (#2153, landed as a port)
- @davidalmeida90 — the next-bar signal delay documented in the strategy skill (#2137)
- @DrDLyuan — STAR Market and Beijing buys sized on their own order grid (#2105)
- @goatyyc — Binance HTTP 451 read failures explained (#1937)
- @hnq-ai — a crawlable documentation wiki (#2165, landed as a port)
- @kadyrbekovhamit-cyber — Heston prices for short expiries (#2140)
- @MetaAviator — invalid journal quantities refused (#2052)
- @octo-patch — MiniMax M3.1 Flash as the default MiniMax model (#1936)
- @RowanAldean — optional Parallel search in `web_search` (#2113)
- @VectorPeak — voice notes forwarded in four IM adapters (#2106)
- @wavebyrd — Yahoo three-letter `=X` forex symbols read as USD pairs (#1980)
- @yufengsika — non-finite and boolean inputs refused by financial rigor checks (#2053)

<details>
<summary>Kontributor v0.1.17 dan v0.1.18</summary>

**v0.1.18** · @warren618 (Haozhe Wu) menambahkan skema alat sesuai kebutuhan, menyimpan hasil riset besar sebagai artefak eksekusi, dan memperbaiki penghitungan penggunaan saat panggilan model terputus.

- @rudycelekli — a 92-PR correctness sweep (13 of them landed as maintainer ports): quant-library guards and edge cases (implied-vol price tolerance #1657, gaps in VaR breach transitions #1658, Heston inputs #1719, scheduled CDS coupons #1716, Carino coincidence #1943, undefined probabilistic-Sharpe and bond-accrual inputs #1821/#1822), missing prices kept out of risk x-ray return pairs and OU lag pairs (#1717/#1713), an undefined three-scenario upside and unbounded journal ratios reported as such (#1921/#1884), document reading that keeps PDF text, Word order, PowerPoint groups and Excel missing-value markers (#1838/#1839/#1840/#1841), session search limits, locking and snippets (#1827/#1828/#1832/#1834), more secret formats redacted (#1874/#1880), A-share board limits and Beijing codes (#1913/#1914), standalone revalidation and attribution on the run's own annualisation (#1915/#1948), and settings the selected engine ignores now warned about (#1947)
- @Shizoqua — 25 PRs (2 landed as ports): memory and cross-session search that read back clean and match non-English text (#1682/#1686/#1697/#1771/#1772), skill headings and saved skill names resolved consistently (#1797/#1858), Telegram and Matrix replies no longer dropped when the stream preview never sent and one WeCom stream id per reply (#1860/#1903/#1929), SSE events no longer double-delivered on reconnect (#1798), parallel CLI tool results paired with their own call (#1859), goal evidence confined to the claimed run (#1895), Carhart momentum no longer leaking today's price (#1578), Wilder RSI in the shadow account (#1457), direct-SDK positions priced from `current_price`/`ltp`/`market_val` (#1581), the email SPF/DKIM spoofing check (#1508), and swarm artifacts cleared before each fresh task (#1455)
- @he-yufeng — 24 PRs (2 landed as ports): the declared grounding-check registry and the fired checks recorded in the validation artifact (#1628/#1691/#1661), corrections that keep the figures already passed (#1702), percent-named evidence read as points in derived checks (#1823), additive A-share qfq converted to multiplicative when the offsets validate (#1551), mootdx retired from the default A-share chain and the health canary (#1730), the channel-authoring contract (#1630), the compaction-helper split out of `loop.py` (#1631), the first bar's result counted against initial capital in the options engine and per-bar returns (#1750/#1844), config keys nothing reads warned about (#1935), the US early-bell close on half-days (#1706), and the ReportLab fallback for Shadow Account PDFs (#1683)
- @shadowinlife — 19 PRs (5 landed as ports): daily paper trading with saved accounts across CLI, API and Web (#1939), the shared scheduler kernel adopted by the research, back-office and live loops (#1893/#1899), token usage in Run Detail, chat and swarm (#1890), `read_run_artifact` and a structured backtest tool summary (#1647/#1646), `get_southbound_flow` and a northbound flow that no longer serves a silent empty envelope (#1486/#1484), guided Web UI setup for Feishu, Slack and Discord with runtime errors surfaced in channel status (#1572/#1764/#1777/#1738/#1737), and thirteen fundamental and valuation factors, industry-neutral A-share value alphas and a monthly-horizon IC bench (#1787/#1788/#1802/#1801)
- @zeus229 — 18 PRs (4 landed as ports): grounding that fails closed on unresolved derived refs and suggests exact refs (#1835/#1837/#1638), parses complete derived formulas after labels (#1728), keeps identity in ticker-keyed metrics and blank-corner matrices (#1851/#1850) and leaves execution metadata out of numeric evidence (#1767); rich Email scheduled reports with optional PDF password protection (#1680/#1709), channel-aware scheduled-run editing (#1649), reproducible indicator reads and pinned portfolio snapshots (#1768/#1769), redundant MCP payload copies removed before agent context (#1634), and goal tool-call provenance (#1688)
- @alexwan02 — 16 PRs (4 landed as ports): the `claude-cli` provider backed by a local `claude -p` (#1804), Hong Kong orders sized on each symbol's own board lot (#1813), the Longbridge SDK config built through `from_apikey` (#1805), Futu multi-currency balances with average-cost basis (#1814), SDM registration that keeps its trading rules and records bench history for decay monitoring (#1848/#1849), a lightweight run preview built off the event loop (#1853), run trades listed newest first from the full trades.csv (#1865), trades.csv entry rows, offline benchmarks and Brinson weights fixed (#1780/#1781/#1782), and runtime connectors ordered by status (#1845)
- @Jackzigen — 13 PRs (2 landed as ports): the first `loop.py` extractions for tool-result helpers, run outcome and tuning (#1636/#1641/#1678), a byte-stable system prompt for prefix caching (#1708), after-close SEC filings kept out of the IC until the next bar (#1794), a free BaoStock fallback for `val:*` panels (#1799), undefined correlation pairs published as null instead of 0.0 (#1933), journal PnL pooled per settlement currency (#1811), `BASE-USDT-PERP` routed to the crypto market (#1864), the mStock read-only profile (#1675), and the shared OHLCV contract assertion in per-loader suites (#1725)
- @cgycorey — 12 PRs (3 landed as ports): only the engine's own output grounds a backtest report (#1685), adjusted and raw prices never mixed in one series (#1684), a stooq challenge latch that stops probing and sees every refusal (#1637/#1640), a loader health lane that says why a source is empty and keeps labelled credentials out (#1643/#1698), `get_macro_series` reporting when it caps a series (#1676), env-style credential names, URL userinfo and Basic auth redacted (#1765/#1742/#1744/#1846), and suffixed HK codes normalized for the duplicate-asset guard (#1746)
- @MetaAviator — 12 PRs (2 landed as ports): full-sample downside deviation for Sortino in the metrics and options engines (#1693/#1727), initial capital in Monte Carlo path metrics (#1664), missing equity kept out of adjacent validation returns (#1754), standalone revalidation that honours saved settings and entry dates (#1815/#1842), break-even exits and zero-bar trades kept in trade artifacts and holding periods (#1779/#1876), and trade-journal fixes for reversal fees, split date/time columns, equal timestamps and invalid dates (#1891/#1900/#1941/#1942)
- @lorenzozanee — unsupported Robinhood option orders gated before the broker (#1585), run cards that flag backtests possibly inside the model's training data (#1618), and option evidence in the broker bring-up checklist (#1770)
- @Mikesad — LLM usage accounting extracted from `loop.py` (#1662), swarm presets that take their variables from the prompt (#1674, landed as a port), and the factor registry suite running without symlink privileges (#1696)
- @remote-controlled-man — options legs priced on the run's bar cadence (#1753), the Futu journal format claimed only when its value columns exist (#1766), and three-statement balance tolerance threaded into projected periods (#1786, landed as a port)
- @Romzhou — a kill-switch sweep that fails closed on its own bookkeeping and input (#1703), and a runner driver kept alive for the scheduler's lifetime (#1704)
- @sambazhu — three Gildata research tools with off-exchange fund NAV (#1485), and an env-configurable ReAct iteration cap (#1833)
- @wavebyrd — spread and swap rates for Yahoo `=X` forex pairs (#1930), and per-cent multipliers for ICE coffee, sugar and cotton (#1944)
- @BHhhh-123 — factor neutralisation and PCA in the quant library (#1817, landed as a port)
- @Bortlesboat — Calmar kept finite on explosive equity paths (#1901)
- @bygordon130-hub — Pixel Office, a shared manual research-task board, and the Turkish locale (#1616)
- @davidalmeida90 — profit factor reported as undefined when no trade lost (#1602)
- @DrDLyuan — the equity.csv drawdown peak seeded with initial capital (#1818)
- @Emad211 — per-channel configuration, custom providers and the Persian locale (#1264)
- @Frank-zhu2000 — Futu profiles no longer pinning the HK trade market (#1812)
- @goatyyc — Binance balances that survive clock skew, with unpriced assets marking the snapshot incomplete (#1505)
- @hunters1011-ctrl — symlink tests skipped where symlinks are unavailable (#1803)
- @incorpore — Brazil (B3) market data and an opt-in ZimaOS template (#1783, landed as a port)
- @mdb1230 — five example options strategies and a candidate study of which to paper-trade (#1774)
- @mminkus — the interactive message cap raised to match the scheduled-run path (#1701)
- @passionbull — KIS reads that see SOR fills and recover from a server-invalidated token (#1726)
- @rwxyx518-prog — the Portfolio page's holdings table and history chart following the display currency (#1810)
- @ThreeTima — currency identity checked in financial figure grounding (#1905)
- @tomaszkubiak-courses — strategy provenance model fields set on the loop, so writing a strategy file no longer raises `AttributeError` (#1673)
- @xaritoku — dotenv loaded in the `alpha bench` / `alpha compare` CLI handlers (#1806)

</details>

<details>
<summary>Kontributor v0.1.16</summary>

- @Shizoqua — a 55-PR correctness sweep (one landed as a port) across nearly every layer: quant-library fixes and input guards (Patell z degrees of freedom #1449, copula ties #1453, Kyle's lambda intercept #1477, HRP labels #1555, non-finite impact and yield-curve inputs #1557/#1558), Alpha Zoo NaN propagation and formula fixes (gtja191_038 #1523, alpha101_074 #1534, qlib158 WVMA #1594, GTJA HIGHDAY/LOWDAY #1604), backtest sizing for negative futures prices and shorts (#1547/#1548), venue bars per year in Monte Carlo validation (#1546), options annual return over elapsed bars (#1458), memory, swarm-store and session robustness (#1450/#1525/#1545/#1536/#1579), DingTalk, Signal, Slack and Discord channel fixes (#1506/#1478/#1524/#1537), Argentina listing identity in grounding (#1575), and a mandate narrowed to zero exposure stored as zero (#1593)
- @zeus229 — grounding that reads locale decimals and grouped numbers with precision-aware rounding (#1517/#1588), resolves explicit symbols and exact field refs from observed evidence (#1584/#1586), preserves `latest_date` timestamps (#1590) and keeps corrections text-only (#1600); Argentina (`.BA`) market data through Yahoo (#1543), ISO-4217 portfolio currencies with isolated FX failures (#1510), explicit header names compared case-insensitively (#1568), technical-indicator volume statistics and their replay after compaction (#1571/#1601), and bounded read-only replay after compaction (#1488)
- @cgycorey — a read-only extraETF export reader (#1406) and the read-only Scalable Capital MCP connector (#1417), run cards that keep non-scalar metrics (#1424), the backtest tool naming the directory it looked in (#1429), a tool-declared swarm `run_dir` confined to the workspace and worker message logs persisted on every terminal path (#1430/#1439), qlib158 CNTP/CNTN/CNTD NaN propagation (#1459), custom zoo roots that no longer replace the bundled module (#1468), `get_shareholder_count` answering again (#1490), Tencent's A-share and HK calibers stamped correctly (#1497)
- @shadowinlife — IM channels configured from the Web UI, with QQ, Email and WebSocket guided setups (#1520/#1529/#1544), stdlib logging placeholders across 12 channel adapters (#1533), Tencent history paginated backward from the end of the window (#1411), `state.json` written by the backtest tool so tool-driven runs are ingestible (#1413), per-worker swarm skill allowlists (#1414), the `1M` interval no longer folding to one minute (#1487), and welcome quick actions with a real selected state (#1500)
- @he-yufeng — tail-risk measure and confidence kept through the grounding gate (#1444), full history in the risk x-ray instead of sampled rows (#1462), shareholder-count history from the per-period report (#1518), backtests attaching to a running MT5 terminal without credentials (#1598), a per-read BaoStock socket deadline (#1615), the weekly live-source health canary (#1627), the broker capability matrix generated into the README (#1629), and the channel `stop_all` and WebSocket logger fixes carried over from #1521
- @lorenzozanee — dragon-tiger seat reports and lockup expiry data restored (#1512/#1513), malformed Robinhood buying power rejected (#1526), broker-only MT5 symbols resolved in `search_symbol` (#1597), hash-only traces and citations on run cards (#1612), expired Copilot CLI tokens refreshed (#1619), and Telegram polling ownership documented (#1583)
- @chiww — the Stooq warning naming the override variable the config layer reads (#1402), A-shares routed by market for sources without a dedicated branch (#1431), the declared interval checked against the served bars before annualising (#1432), and `_NO_NETWORK_FALLBACK_SOURCES` honoured for per-symbol gaps (#1441)
- @as950118 — three Korean broker connectors: KIS with separate paper and live hosts (#1407), Upbit capped at paper plus read-only (#1408), and read-only Toss Securities (#1409)
- @0xouzm — SDM decay metrics that treat NaN and infinite bench results as missing (#1447)
- @alanwilhelm — synchronized cold loader-registry initialization, so concurrent first lookups no longer see an empty registry (#1405)
- @modelpath-dev — the description-driven strategy-store adaptation substrate (#1391)
- @sambazhu — the Gildata A-share OHLCV loader over its raw-api MCP endpoint (#1474)
- @tingkk — broker-neutral SDK diagnostics across all locales (#1436)
- @tonydo — OpenCode as a built-in provider, sending the `x-opencode-session` header OpenCode Go requires (#1416)
- @woshi77777stars — the `Trigger.market` default restored on non-market triggers (#1599)
- @Yoruxyv — the Bahasa Indonesia UI locale and `README_id.md` (#1482)

</details>

<details>
<summary>Kontributor v0.1.15</summary>

- @Shizoqua — 28 PRs: NaN propagated through 16 GTJA and Alpha101 alphas instead of fabricated values (#1371/#1372/#1373/#1374/#1379/#1380/#1381/#1382/#1383) and Alpha Zoo returns no longer forward-filling gaps (#1172), missing-price gaps preserved in the SDM template and cross-market volatility weights (#1397/#1398), multi-factor and social-media factor evaluation fixes (#1399/#1400), walk-forward ML training without future-label leakage (#1392), China futures product codes parsed for digit-prefixed, month-code-colliding and lower-case symbols (#1369/#1389), composite sub-engines synced before every dispatch (#1370), per-regime position sizing in strategy discovery (#1368), MCP goal sessions isolated per connection with current-goal defaults (#1173/#1331), Codex token usage and model metadata (#1334/#1348), and swarm cancellation reaching the in-flight worker (#1175)
- @he-yufeng — 26 PRs, mostly fail-closed live trading and backtest semantics: broker API errors and error envelopes fail closed in position reads and the halt sweep (#1212/#1232), the flatten latch persists across restarts (#1233), market-triggered ticks skip closed markets (#1253) and buy-limit orders are sized at the worse of quote and limit (#1312); the price-adjustment caliber stamped on served frames (#1317) with adjusted Yahoo prices (#1287), unresolved symbols retried down the fallback chain (#1288) and the stooq anti-bot challenge flagged (#1342); short option legs holding margin (#1306), perpetual funding settled by bar span (#1307), A-share and India rules enforced through composite state (#1309) and halted positions marked at the last traded close (#1332); Shadow Account PnL, attribution, FIFO short lots and cache keys (#1217/#1310/#1311/#1314); and each monitor's latest verdict rendered on the list (#1156)
- @cgycorey — 23 PRs: UK (LSE `.L`) equity support (#1206), swarm replay/resume of failed runs keeping completed artifacts (#1158), market-data validation of codes, dates and sources with aligned FX/index search and fetch (#1185/#1316), dotted US class shares routed as US equity (#1351), backtest execution fixes — requested targets separated from executed fills, 1x shorts liquidated, option signals filled on the next bar, default IV for HV warm-up and over-committed baskets scaled (#1281/#1298/#1299/#1305/#1344); live halt-sweep envelopes, per-episode latches and MCP buy-limit sizing (#1244/#1254/#1361); grounding clause and metric-table gates (#1326/#1338/#1375/#1378); the registry NaN contract on declared dependencies (#1377); compaction sized by tool-call arguments (#1352); and report audits that fail closed when nothing was verified (#1362)
- @santhreal — 16 PRs extending the quant library: factor risk decomposition, event-study rank and sign tests, OU calibration, drawdown analytics, barrier options, single-name CDS, key-rate duration, IC time series, Vasicek credit loss and group-purged CV (#1159–#1168), Heston pricing, HRP allocation, copulas and market microstructure (#1195–#1198), finite-difference barrier Greeks (#1203), and multi-segment test sets in cross-validation (#1204)
- @AirHua-byte — multi-file drag-and-drop and paste uploads (#1179), interrupted replies recovered after a service restart (#1180), shared HTTP clients preserved during cleanup (#1182), agent-confirmed scheduled research tasks (#1187), persisted Feishu QR login credentials (#1188), explicit market context kept in grounding (#1269), and the offline harness artifact verifier (#1271)
- @lorenzozanee — silent order-plan rejections surfaced through an `_on_plan_rejected` hook (#1245), the temperature self-heal on the OpenAI-compatible path (#1246), escalating stream retry delays that honour Retry-After (#1247), USD-M tolerance calibration (#1248), FMP's Stable endpoint with no silent fallback for an explicit source (#1276), adjusted prices on the FMP and Tiingo paths (#1320), and EPERM handled in desktop updater shutdown checks (#1284)
- @goatyyc — the read-only multi-broker portfolio dashboard and connection framework (#1072) with connector onboarding contracts (#1250), IBKR official MCP OAuth with verified read tools (#1190), and an isolated portfolio OAuth reconnect lifecycle with classified failures (#1211/#1251)
- @saju01 — the agent loop keeping tool results the model still needs (#1341), compacted results reconciled by exact call identity (#1358), and grounding that no longer reads percentage-point deltas as quoted prices (#1346/#1357)
- @aminak58 — symbol identity for bare joined crypto pairs (#1265), FX, metals and futures (#1280), and spot-gold aliases (#1282)
- @averatec0773 — the Anthropic static prefix cached with cache usage recorded (#1366), relocated `extra_body.temperature` stripped in the Anthropic self-heal (#1330), and an attempt start persisted so the elapsed clock survives navigation and reload (#1340)
- @Elfsa-Miranda — Alpaca submissions owned before broker writes, then recovered by exact client id and exact fills across restarts (#1213/#1221/#1222)
- @ethanstoner — skill-relative reference links resolved in `read_file` and on GitHub (#1252/#1328), and strategy-store history that is really newest first (#1347)
- @iagop03 — Web UI fixes: a stale `streamingSessionId` cleared on reopen, a scrollable main region with collapsed long prompts, and non-backtest runs pointed to Studio (#1257/#1258/#1259)
- @Robin1987China — non-finite inputs refused across valuation and credit-risk functions (#1184/#1215), and Archimedean copula CDFs stabilized under large parameters (#1386)
- @Emad211 — cross-platform locks and path handling for Windows (#1261), and read-only Nobitex and Wallex market-data sources (#1263)
- @honginp — read-only Binance USD-M account snapshots (#1229) and USD-M drift evidence artifacts (#1230)
- @pengpengyi92 — bounded backoff on swarm worker retries (#1210), and crypto pairs resolved through an active Binance connector (#1242)
- @ashutoshsinghpr7 — the Zerodha Kite Connect broker for Indian equities (#1193)
- @be-student — the no-progress stop for repeated discovery without new evidence (#1363)
- @BigFishEmily — paginated Tencent finance history requests (#1154)
- @birdxs — Docker CI actions upgraded to Node.js 24 compatible versions (#1359)
- @bonyohana — the survivorship-bias disclosure rendered in the HTML bench report (#1289)
- @c020627 — the IBKR official read-only MCP seed pointed at `/mcp-public` (#1178)
- @guestccc — `/api` routes proxied in the Vite dev server (#1319)
- @Jackzigen — mandate adjustments that enforce narrowing for non-numeric and list fields (#1285)
- @JaxonHu1024 — Futu HKD valuations preserved in the portfolio (#1228)
- @laiyierjiangsu — HK-prefixed symbols (`HK.06693` → `06693.HK`) locked in grounding (#1384)
- @nandofmike — the Brazilian Portuguese (pt-BR) locale (#1327)
- @P1Piyush — metals treated as metals in the forex backtest: pip size, lot size and spreads (#1226)
- @sambazhu — per-market data-source priority in Settings and `MARKET_DATA_ORDER_*` (#1231)
- @SiMinus — `vibe-trading swarm retry` with a resume option (#1194)
- @sykuang — the IBKR public MCP OAuth flow (#1186)
- @thisisjun786 — calendar-triggered partial rebalancing (#1277)
- @wiliao — a run-stall watchdog, a bash tree-kill timeout and a compaction verification ledger (#1169)
- @youngjincho02-arch — the historical VaR quantile formula fixed in the risk-analysis skill (#1189)

</details>

<details>
<summary>Kontributor v0.1.14</summary>

- @Shizoqua — a 13-PR correctness sweep across nearly every subsystem: grounding auto-recovers identity and price evidence within a bounded budget (#1092), swarm isolates worker artifacts between retries (#1053), rejects raw `ok`/`success` tool-result envelopes (#1052) and truncates oversized results with the shared notice (#1110), MCP gains offset paging for SEC filings and statements (#1138), routes `load_skill` through the registry so oversized skills page (#1137) and carries market-data provenance on `get_market_data` (#1131), plus `excess_return` consistency (#1058), Wilder-EWM RSI (#1056), the FTS5 tokenizer floor (#1071), non-finite prediction-market fields (#1136), in-flight delivery protection (#1140) and preserved backtest validation evidence (#1139)
- @shadowinlife — the run-analysis surface, four pages in one cycle: Options Lab (#1096), the Factor Research panel with its new IC correlation matrix (#1099), positions structure visualization (#1097) and the tearsheet tab (#1091); plus evidence-gated Strategy Discovery Phase 1 (#978) and Phase 2 decay monitoring (#1007), per-market volume units in market-data provenance (#1065) and baostock volume normalized to board lots (#1067)
- @pengpengyi92 — five quantlib numerics fixes: `xirr` and money-weighted return survive long-horizon discount underflow (#1119), zero-volatility options discount their forward value (#1066), the fixed-income curve keeps decay inside the requested bounds (#1076), event studies anchor to the prior session (#1078) and cross-validation aligns label ends to the prior observation (#1079)
- @cgycorey — reasoning effort honoured in chat completions (#1025), the per-task swarm `ChatLLM` closed to stop a pooled-connection leak (#1145) and the same for one-shot clients (#1153), `gross_profit` derived from revenue minus COGS when the SEC tag is absent (#1111), and `vibe-trading show <run_id>` dispatching its run id instead of the flag (#1147)
- @lorenzozanee — the test suite stopped escaping into the real config root and its live audit ledger (#1118, closes #1116), recovery steering delivered as user messages with inline system tags (#1112), and unsupported ticker-plus-name symbol queries marked skipped rather than failed (#1114)
- @AndyLongest — the interactive backtest research dashboard (#1084), the engine reporting actual post-fill positions (#1082), and grounding ignoring identity constants in rate formulas (#1083)
- @ofeksh-tr — eToro runtime UI parity for SDK connector status (#1051) and its crypto browse and flat market-data quotes (#1070), plus an empty `Response` for the `scheduled-runs` DELETE 204 (#1068)
- @wiliao — the agent-run reliability pass: grounding false-rejections, the final-answer gate and LLM timeouts (#1105), with prompt wording and support/resistance masking (#1060)
- @jay79-boop — a selectable IBKR market-data tier with starved quotes reported as `no_data` (#1075), and strict alpha t-stats surfaced in the bench JSON and HTML report (#1085)
- @Robin1987China — DCF refusing non-finite inputs instead of a silent negative share price (#1121), and grounding masking ISO dates that run into CJK text (#1132)
- @zzz607 — grounding masking line-leading ordered-list markers before number extraction (#1063), and the East Money research-report endpoint given the time parameters it now requires (#1077)
- @Echoandelementwebsites — worker prompts ordered for prompt-cache-friendly prefixes (#1057), and tool-less agents no longer instructed to call `write_file` (#1144)
- @549236606-oss — seven extended read-only Futu connector endpoints, each fail-closed through the existing gateway envelope (#1135)
- @QCYTSN — the desktop update safety boundary: PID-scoped shutdown, dormant candidate verification, interrupted-attempt recovery, and a tested tampered/unsigned/wrong-publisher/downgrade rejection matrix (#1101)
- @honginp — offline USD-M account reconciliation with immutable snapshot contracts and deterministic drift reporting (#1106)
- @he-yufeng — each monitor's latest verdict parsed server-side and persisted on the job for the Market Watch list (#1152)
- @sykuang — GitHub Copilot as a provider through the official SDK, with no borrowed client ID and no editor-impersonation headers (#990)
- @miguelangelo78 — the hosted TickerAll MetaTrader 5 data source, so forex and metals backtests need no local MT5 terminal (#968)
- @ngoanpv — Vietnam equity (HOSE) support: `.VN` no longer executes under China A-share rules (#1033)
- @jax-novita — Novita AI registered as a built-in OpenAI-compatible provider (#1059)
- @daviddaco1 — the Spanish locale and `README_es.md`, the sixth README (#1087)
- @1psconstructor — German (Deutsch) UI support (#1117)
- @x-lambda — the tencent loader building its SSL context from the certifi CA bundle, unblocking HK quotes (#1113)
- @er-s-an — `build_registry()` reporting partial construction instead of silently returning a short tool list (#1129)
- @straun-repo — reasoning effort passed through to the Anthropic adapter (#1115)
- @nstavros — `connector orders` rendering broker_sdk rows, with SDK enum reprs stripped and class-B tickers left intact (#1150)
- @lukiod — `.env.partial` created with owner-only permissions (#1086)
- @fixXxerTech — inferred strategy labels marked as inferred in the run dashboard (#1134)
- @birdxs — Docker images carrying the Feishu and Telegram channel dependencies, with a GHCR/Docker Hub build workflow (#1088)
- @zhiwuyazhe-fjr — a Docker Codex OAuth EOF that explains itself (#1054)

</details>

<details>
<summary>Kontributor v0.1.13</summary>

- @santhreal — a 21-PR correctness sweep: trade-journal date and format parsing for Excel serials, UTF-16 BOM CSVs and BTCUSDT-style symbols (#778/#794/#811/#862/#868), loader interval mapping (#812/#838), skill frontmatter closed at EOF (#861), exact memory anchors and result bounds (#956/#957), negative-equity drawdown, insolvent empty cross accounts and `inf` from zero equity (#958/#959/#1041), NaN/inf in the grounding block (#1043), null and non-finite tool arguments (#911/#913), and resource-leak and robustness fixes in the rate limiter, HTTP throttle, event bus, store and Shoonya connector (#1039/#1047/#1046/#1045/#1038)
- @Robin1987China — read-only `technical_indicators` and `sentiment` tools (#921/#939), the final report aggregator stage for `quant_strategy_desk` (#1048), annualisation entries for 15 more data sources (#891), `factor_analysis` realigned on MCP to the registered tool's contract (#715), blank symbol rows skipped in the Futu and generic journal parsers (#749), loader payloads handled without sampling indicator inputs (#1005), and a real account label in CLI balances (#843)
- @he-yufeng — the options payoff and scenario explorer (#883, rebuilt by the maintainer as #946), the strict alpha bench gate via `alpha bench --strict` (#796), composable optimizer weight constraints (#818), rebalance notes and risk x-ray artifacts for portfolio runs (#795/#900), yfinance crypto routed to the crypto engine (#970), and memory entries written with their `.md` suffix (#984)
- @shadowinlife — memory Phase 1 lifecycle management and Tier 2 structural organization (#733/#815), JSON-string list/dict arguments accepted from MCP clients (#993), HK fallback routing repaired with a Tencent HK source (#1000), and MT5 `trading_history` numpy scalars made JSON-safe (#776)
- @honginp — USD-M perpetual realism: margin state contracts, isolated and cross liquidation risk, the funding and liquidation lifecycle and persisted fidelity evidence (#798/#889/#903/#936), plus opt-in atomic rebalancing integrated with strict USD-M positions (#951/#1019)
- @Shizoqua — swarm detection of `ok:false` / `success:false` tool failures (#1028), importance decay in FTS5 memory ranking (#1032), remote server identity in the MCP specs cache key (#1049), and lowercase `4h` requests resampled in the yfinance loader (#1013)
- @tyj147454413-cmd — three fixes split from #543 that landed with their authorship: one run per session with honest terminal states (#676), redaction of free-text tool results (#675), and durable trace records and sidecars (#662)
- @cgycorey — Alpha Zoo tools exposed on MCP with a bounded `alpha_bench` (#979), and mapping-shaped Responses stream events accepted (#1034)
- @darkknight4563 — opt-in non-positive prices in the daily-bar validator (#816, closes #571), and `bar_returns` keeping the real move across a long trading halt (#895)
- @MuggleJinx — sessions, runs and uploads stored under the user runtime root instead of the code tree (#925), and the `connector` CLI loading `~/.vibe-trading/.env` (#902)
- @00EVA — a model dropdown that resizes so full provider/model slugs are readable (#1006)
- @AmirF194 — universe metadata forwarded into the `alpha bench` JSON and HTML output (#841)
- @CRui5in — Web UI LLM settings saved on Windows without an HTTP 500 (#561)
- @ddy4633 — the correlation matrix no longer forward-filling missing closes (#873)
- @Echoandelementwebsites — dataclass tool results serialized without a false circular-reference crash (#849)
- @g0rdonL — historical USD-M funding consumed, with settlement jitter rounded (#819)
- @JungHoonGhae — Korea equity (KRX: KOSPI/KOSDAQ) as a backtest engine (#693, landed as a port)
- @klmtseng — restated PIT fundamentals deduplicated without regressing to an older fiscal period (#772)
- @ngoanpv — timezone-aware local schedules for scheduled research (#954)
- @QCYTSN — live model discovery and runtime identity in Settings (#924)
- @sambazhu — `temperature=1` forced for the whole Kimi K-series (#701)
- @shugaoye — the OpenBB Workspace bridge (#817, landed as a port)
- @TSENGCHIENFENG — the read-only Taiwan stock snapshot tool (#848, landed as a port)
- @wiliao — TSX/TSXV symbols end to end, with bash-written run-dir OHLC CSVs counted as observed evidence (#1037)
- @x-lambda — a config option to disable the agent proxy (#995)
- @xkam7ar — partial market-data results completed through the fallback chain instead of shrinking the universe (#689, landed as a port)
- @y85998607 — the vn.py export skill updated for the vn.py 4.x layout (#869)
- @yagnikpipaliya — the Anthropic adapter self-healing models that deprecate `temperature` (#890)
- @yrk111222 — ModelScope as an OpenAI-compatible provider (#1011)

</details>

<details>
<summary>Kontributor v0.1.12</summary>

- @santhreal — a 30-PR correctness sweep: strict-JSON / finite-number hardening across metrics, factors, pattern, and options (#764/#765/#766/#767/#739/#740/#744), loader correctness (#761 yahoo 1m bars), and session / journal robustness (#762/#763/#768/#769/#770)
- @xkam7ar — broad reliability across packaging, web, scheduler, swarm, and CLI (#584), cancellation before the first AgentLoop iteration (#641, closes #638), CI / OOS gates (#630/#632), and journal month-filter / side-parse fixes (#626/#628)
- @shadowinlife — the Strategy Development Manager skill (#457, closes #455), pluggable OCR + LLM-vision extraction (#548), centralized provider credentials (#563), the 80× signal-alignment vectorization (#698), and swarm MCP-discovery caching (#704)
- @ebujinovch — the correlation regime timeline endpoint + UI (#756, closes #719) and its `correlation-regime` skill (#557), plus the `academic_corr_rewire` factor (#705)
- @honginp — Binance USD-M routing with execution/mark separation (#470/#716) and the maintenance-bracket decouple that keeps `-PERP` backtests zero-credential (#757)
- @StaniellG — the MetaTrader 5 (Exness) broker connector + `mt5` data source (#481)
- @tyj147454413-cmd — the Binance fallback loader (#643), bounded OKX history with rate-limit handling (#644), and codex stream-failure classification (#663)
- @Marnie0415 — composite sub-engine fallback for unknown symbols (#734) and the frontend `insertBefore` streaming DOM-race fix (#717)
- @YZY0108 — the look-ahead-bias fix across all five portfolio optimizers (#487)
- @UNHNQ — the SiliconFlow CN + Global providers (#565)
- @FenjuFu — the iFlytek Spark provider (#537)
- @jelech — the native Anthropic Messages API adapter (#695)
- @octo-patch — MiniMax regional API endpoints (#731)
- @Thibaultjaigu — the Requesty OpenAI-compatible gateway provider (#474)
- @Robin1987China — realized portfolio turnover metrics for every optimizer (#478)
- @YogeshModi24 — the Frazzini-Pedersen betting-against-beta academic factor (#480)
- @0xZKnw — opt-in TAP mode for Alpaca (#377)
- @sambazhu — the fundamental zoo `_VALID_ZOOS` whitelist (#707)
- @nareshkps — Robinhood connector `account_number` wiring (#726)
- @darkknight4563 — user swarm-presets directory discovery (#570)
- @MikeCer — IBKR thread-local connection pool + snapshot quotes (#636)
- @Shizoqua — `local` loader interval resampling (#467)
- @roberttidball — FastMCP transport import compatibility (#469)
- @yxhuang — bare-ticker resolution in the correlation matrix (#472, closes #471)
- @Bortlesboat — stale `OPENAI_BASE_URL` provider-switch fix (#484, closes #482)
- @ananaymital — preflight `EnvConfig` stale-cache fix (#479, closes #477)
- @GabbaTauchi — reported the native zai streaming / base-URL bug (#758)
- @warren618 / Haozhe Wu — the correlation regime backend integration, the zai provider streaming + base-URL resolution fix (#758), release integration, and open-PR/issue triage

</details>

<details>
<summary>Kontributor v0.1.11</summary>

- @shadowinlife — the `api_server` modularization capstone (1,103 → 371 lines, #424 closing #331), centralized env config with the AST CI gate (#440), loader `fetch()` protocol conformance (#437), and the Strategy Development Manager RFC in review (#455/#457) — 12 merged PRs this cycle
- @Robin1987China — Research Autopilot Phase 3 loop closure (#267), 4 canonical academic alphas (#277), Shadow Account PIT-safe entry conditions (#302/#314/#316), the turnover-aware portfolio optimizer (#466), scheduled-research route tests (#452), and test-coverage batches for trade-journal / pattern / loader layers (#268/#269/#276)
- @muku314115 — first-class Indian equity (NSE/BSE) support: the `IndiaEquityEngine`, cost stack, `.NS`/`.BO` routing, and the `india_broker` bridge (#305)
- @mvanhorn — the end-to-end scheduled-research executor (#278), the Trading 212 read-only connector (#321), OpenAI default-model resolution (#319), and Robinhood config validation (#320)
- @fei-moss — the `analyze_image` vision tool (#464), NapCat DM pairing (#463), and the IM-media allowed-roots report (#465)
- @sambazhu — the value-investing toolkit: financial-rigor + report-audit tools, 4 skills, and the `value_investing_committee` preset (#407/#408)
- @Elfsa-Miranda — the evidence-bound alpha research pipeline exploration (#405/#416, since re-scoped into #442)
- @Hinotoi-agent — loopback CSRF rejection (#293) and authenticated remote same-origin UI requests (#304)
- @dpersek — configurable IM reply timeout (#413) and the provider-preflight redirect fix (#404)
- @digger-yu — cross-platform `setup`/`dev` commands (#292) and dev-dependency pre-checks (#349)
- @skloxo — tilde expansion + file-roots safety fallback (#299) and reactive zh-CN localization (#301)
- @kadaliao — the beginner tutorial (#393) and Alpha Library social cards (#396)
- @morluto — CLI resume first-message preservation (#448) and the Codex OAuth default model (#446)
- @yxhuang — the Kimi for Coding provider (#435) and the precise #433 diagnosis behind the governance-stack revert
- @isaveall — the `validation.json` artifacts-dir fix (#429) and clearer `--swarm-run` errors (#428)
- @mustafakamal88 — timezone-aware UTC timestamps (#397)
- @irfanallana-oss — the zero-size order guard in `trading_place_order` (#417)
- @Shizoqua — the central OHLC-invariant loader guard (#274)
- @hobostay — SSRF-guard hardening for CGNAT/mesh ranges + the QQ media redirect fix (#389)
- @aeonframework — Pillow / langchain CVE floor bumps (#390)
- @hannibal-lee — the pandas version-constraint fix (#329)
- @MarkfuGod — dynamic data-source counts + token-gated microcompaction (#296)
- @gyx09212214-prog — strict JSON validation outputs (#306)
- @LemonCANDY42 — the backtest report library (#224)
- @fanfpy — Longbridge Decimal→float serialization (#459)
- @asahikiko — packaged SKILL.md capability-count sync + the manifest guard test (#461)
- @wison1717-maker — the mandate second-confirmation dialog + unified error toasts (#453)
- @imsankz — opencode provider mappings (#444)
- @flash1234pku — the tushare reference code-fence fix (#449)
- @Penn-Live — the Docker startup route-iteration crash report (#450)
- @warren618 / Haozhe Wu — the fundamental factor layer (PIT-safe SEC panels), the IM channel runtime, India-equity integration review, CN search fallbacks, and release integration

</details>

<details>
<summary>Kontributor v0.1.10</summary>

- @Hinotoi-agent — a security-hardening wave: local-shutdown auth (#241), loopback-host rebinding rejection (#242), agent shell-tool opt-in (#243), settings-write auth (#245), mandate proposal-id containment (#256), persistent-memory type validation (#257), and MCP swarm run-id containment (#258)
- @mvanhorn — the opt-in local data cache (#177), Gemini thoughtSignature round-trip over OpenAI-compat tool calls (#176), the custom data loader guide (#194), and the glm/zhipu provider alias + model-name inference (#247)
- @gyx09212214-prog — loader robustness for malformed crypto/RSSHub timeout env vars (#227, #240), requested yfinance end-date inclusion (#226), strict run-card JSON for non-finite metrics (#238), and ddgs retry-fallback coverage (#239)
- @BillDin — swarm agent status in the chat UI (#188), explicit preset-name handling (#189), the loader-backed market-data tool for swarm workers (#199), and preset-context continuations (#200)
- @Robin1987China — the Research Autopilot goal-hypothesis bridge (#260), the local CSV/Parquet/DuckDB data loader (#252), and an assistant-prefill fix + configurable Kimi User-Agent (#248)
- @LemonCANDY42 — the read-only runtime status dashboard (#210), persisted AgentLoop usage artifacts (#223), and opt-in Run Detail chart payloads (#225)
- @zwrong — the trace.jsonl overhaul with zero truncation + offload (#206) and session-id on exit + `resume <session-id>` (#218)
- @forge-builder — the AI contributor guide (#173) and the OpenClaw MCP research-only smoke-test docs (#165)
- @skloxo — Chinese (zh-CN) frontend localization (adopted from #217)
- @LeeCQiang — Chinese docstrings across all 452 Alpha Zoo factors (#180)
- @KaiLuettmann — GHCR pre-built image publishing on release (#187)
- @ngoanpv — Gemini thought_signature preservation through the AgentLoop dict path (#184)
- @ShahNewazKhan — Docker host-Ollama reachability via host.docker.internal (#196)
- @sambazhu — frontend sync of completed chat attempts (#236)
- @bhlt — baostock-native code format support (#230)
- @octo-patch — MiniMax M3 default model upgrade (#162)
- @warren618 / Haozhe Wu — the global data layer (8 sources + 18 read-only data tools), the 10 broker SDK connectors, the alpha-compare full stack, the provider-reliability overhaul, multi-engine web_search fallback, responsive Stop + SSE reconnect, and release integration

</details>

<a href="https://github.com/HKUDS/Vibe-Trading/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/Vibe-Trading" />
</a>

## Penafian

Vibe-Trading adalah software riset dan trading. Ini bukan saran investasi, tidak menyimpan dana, dan tidak menjalankan execution venue. Trading melalui channel broker yang Anda otorisasi secara eksplisit (mis. Robinhood Agentic Trading) hanya terjadi dalam batas yang Anda tetapkan dan dapat dihentikan kapan saja. Kapabilitas broker-trading ini masih eksperimental dan belum kami verifikasi terhadap akun broker nyata — gunakan dengan risiko Anda sendiri. Kinerja masa lalu tidak menjamin hasil di masa depan.

## Lisensi

Lisensi MIT — lihat [LICENSE](LICENSE)
