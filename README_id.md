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
  <a href="https://trendshift.io/repositories/25527" target="_blank"><img src="https://trendshift.io/api/badge/repositories/25527" alt="HKUDS%2FVibe-Trading | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
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
  <a href="https://vibetrading.wiki/">Situs Web</a> &nbsp;&middot;&nbsp;
  <a href="https://vibetrading.wiki/docs/">Dokumentasi</a> &nbsp;&middot;&nbsp;
  <a href="#-news">Berita</a> &nbsp;&middot;&nbsp;
  <a href="#-key-features">Fitur</a> &nbsp;&middot;&nbsp;
  <a href="#-shadow-account">Shadow Account</a> &nbsp;&middot;&nbsp;
  <a href="#-demo">Demo</a> &nbsp;&middot;&nbsp;
  <a href="#-quick-start">Mulai Cepat</a> &nbsp;&middot;&nbsp;
  <a href="#-examples">Contoh</a> &nbsp;&middot;&nbsp;
  <a href="#-api-server">API / MCP</a> &nbsp;&middot;&nbsp;
  <a href="#-roadmap">Roadmap</a> &nbsp;&middot;&nbsp;
  <a href="#contributing">Kontribusi</a>
</p>

<p align="center">
  <a href="#-quick-start"><img src="assets/pip-install.svg" height="45" alt="pip install vibe-trading-ai"></a>
</p>

---

<a id="-news"></a>
## 📰 Berita

> ⚠️ **Peringatan keamanan:** Akun X `VibeTrading_HKU`, proyek Virtuals `101845`, dan kontrak token `0x640BDBF77b6447E8b7DB7894cED84BD1c40571f4` bukan aset resmi Vibe-Trading. Kami tidak pernah meluncurkan atau mendukung token maupun memecoin apa pun. Jangan membeli, menghubungkan wallet, atau menandatangani apa pun. [Detail](SECURITY.md#official-channels--impersonation).

- **2026-09-22** 📅 **Bar mingguan dan bulanan, serta replay setelah kompaksi yang bisa kehilangan bukti**: `get_market_data` dan backtest menerima `1W` dan `1M` (ditolak sejak 09-20 agar `1M` tidak mengambil bar satu menit). Setiap sumber tetap menyajikan bar harian dan bar periode dibangun darinya, bertanggal hari perdagangan terakhir dalam minggu atau bulan itu, sehingga tinjauan bulanan 21 bulan cukup satu panggilan berisi 21 bar ([#1479](https://github.com/HKUDS/Vibe-Trading/issues/1479)). Indeks harga kini ditandai tanpa penyesuaian, bukan menurut perlakuan sumbernya terhadap saham ([#1541](https://github.com/HKUDS/Vibe-Trading/issues/1541)). Hasil tool baca-saja yang dihapus oleh kompaksi konteks dipulihkan dari memori run itu sendiri alih-alih diambil ulang, dengan batas per run, dan setiap penulisan mengosongkan memori itu sehingga file yang dibuat ulang dibaca kembali ([#1488](https://github.com/HKUDS/Vibe-Trading/pull/1488)). Angka risiko ekor yang dideklarasikan dengan ref field dicocokkan dengan field itu, sehingga VaR 99% yang memakai nilai 95% tertangkap ([#1444](https://github.com/HKUDS/Vibe-Trading/pull/1444)). QVeris menolak bar saham dan ETF, yang penyesuaiannya tidak bisa dinyatakan oleh sumber pilihan peringkat pencariannya, serta kuotasi per hasil ([#1494](https://github.com/HKUDS/Vibe-Trading/issues/1494)). Terima kasih [@sambazhu](https://github.com/sambazhu), [@zeus229](https://github.com/zeus229), [@he-yufeng](https://github.com/he-yufeng), [@jw232](https://github.com/jw232) and [@cgycorey](https://github.com/cgycorey)!

- **2026-09-22** 💸 **Backtest yang berhenti saat funding membuat kas negatif, dan tiga tool lain yang membaca query yang ditolak sebagai tidak ada data**: potongan funding kripto dapat membuat kas tersedia di bawah nol, lalu posisi berikutnya yang diinginkan strategi tidak muat di ukuran apa pun — bahkan nol — sehingga run berhenti dengan "planned order … exceeds available capital" (atau "insufficient capital for position rebalance"). Kini pembukaan itu dilewati dan dilaporkan sekali sebagai `insufficient_capital`, pengurangan pada bar yang sama tetap dijalankan, dan penutupan yang kerugiannya melebihi margin tetap membatalkan bar seperti sebelumnya ([#1542](https://github.com/HKUDS/Vibe-Trading/issues/1542)). Block trade, margin trading, dan laporan keuangan kini membedakan penolakan Eastmoney atas query usang dari jawaban yang memang kosong, dengan pemeriksaan yang sama seperti jumlah pemegang saham, dragon-tiger, dan lockup expiry. Jawaban dalam bahasa Spanyol, Jerman, dan bahasa lain yang memakai koma desimal kini mencocokkan `17,93 %` atau `1.410,00 CNY` dengan hasil tool, sementara dua angka tanpa spasi seperti `1400,1777` tetap dua angka, dan sebuah angka harus cocok dengan buktinya pada presisi yang ditulis ([#1517](https://github.com/HKUDS/Vibe-Trading/pull/1517)). Terima kasih [@turtle696966969696](https://github.com/turtle696966969696) atas trace yang cocok hingga sen, dan [@zeus229](https://github.com/zeus229)!

- **2026-09-21** 🔌 **Channel IM dikonfigurasi dari Web UI, dan 24 alpha yang mengeluarkan nilai dari bar yang hilang**: Settings kini mengedit setiap channel IM dengan secret yang disamarkan, uji koneksi pada formulir yang belum disimpan, dan hot apply per channel tanpa restart; DingTalk dan QQ mendapat setup terpandu ([#1520](https://github.com/HKUDS/Vibe-Trading/pull/1520), [#1529](https://github.com/HKUDS/Vibe-Trading/pull/1529)), dan semua adapter kembali memakai logging stdlib sehingga diagnostik yang dulu hilang karena placeholder `{}` masuk ke log ([#1533](https://github.com/HKUDS/Vibe-Trading/pull/1533)). Di Alpha Zoo, perbandingan dengan operand yang NaN karena jendelanya memuat bar yang hilang bernilai False dan mengeluarkan konstanta; sweep #1463, yang menggeser bar satu tick, tidak dapat melihatnya. Perbandingan deret ber-gap dengan deret lengkap menemukan 24 alpha lagi, yang kini di-mask berdasarkan jangkauan input-nya, sementara korelasi yang tidak terdefinisi pada data lengkap mempertahankan putusan lamanya ([#1523](https://github.com/HKUDS/Vibe-Trading/pull/1523), [#1534](https://github.com/HKUDS/Vibe-Trading/pull/1534), [#1463](https://github.com/HKUDS/Vibe-Trading/issues/1463)). **Data:** `free_shares` pada lockup kini adalah jumlah saham yang dibuka, bukan saham beredar ([#1513](https://github.com/HKUDS/Vibe-Trading/pull/1513)); kursi dragon-tiger diurutkan per alasan listing ([#1512](https://github.com/HKUDS/Vibe-Trading/pull/1512)); jumlah pemegang saham mengembalikan periode historis yang nyata ([#1518](https://github.com/HKUDS/Vibe-Trading/pull/1518)); harga A-share dari Tencent, Eastmoney, dan AKShare diberi label penyesuaian dividen aditif ([#1497](https://github.com/HKUDS/Vibe-Trading/pull/1497)); Gildata bergabung sebagai sumber A-share berbasis token ([#1474](https://github.com/HKUDS/Vibe-Trading/pull/1474)); portofolio menilai mata uang ISO-4217 apa pun dan hanya sumber terkait yang gagal jika kurs tidak tersedia ([#1510](https://github.com/HKUDS/Vibe-Trading/pull/1510)); `connector account` menampilkan saldo Binance, Futu, dan Trading 212 ([#1539](https://github.com/HKUDS/Vibe-Trading/issues/1539)). **Baru:** UI dan README berbahasa Indonesia ([#1482](https://github.com/HKUDS/Vibe-Trading/pull/1482)). **Dihapus:** provider Requesty — arahkan `openrouter` ke base URL-nya. Terima kasih [@shadowinlife](https://github.com/shadowinlife), [@he-yufeng](https://github.com/he-yufeng), [@Shizoqua](https://github.com/Shizoqua), [@lorenzozanee](https://github.com/lorenzozanee), [@cgycorey](https://github.com/cgycorey), [@zeus229](https://github.com/zeus229), [@sambazhu](https://github.com/sambazhu), [@Yoruxyv](https://github.com/Yoruxyv) and [@jastincheis](https://github.com/jastincheis)!

<details>
<summary>Berita sebelumnya</summary>

- **2026-09-20** 🛠️ **Request data yang lebih jelas dan perbaikan sehari-hari**: request bulanan `1M` sekarang ditolak secara eksplisit alih-alih diam-diam mengambil bar satu menit ([#1487](https://github.com/HKUDS/Vibe-Trading/pull/1487)); dukungan interval weekly/monthly tetap dilacak di [#1479](https://github.com/HKUDS/Vibe-Trading/issues/1479). Welcome quick actions sekarang menyorot chip yang dipilih ([#1500](https://github.com/HKUDS/Vibe-Trading/pull/1500)), DingTalk menyanitasi nama file yang diunduh ([#1506](https://github.com/HKUDS/Vibe-Trading/pull/1506)), Signal mempertahankan teks di sekitar mention setelah emoji ([#1478](https://github.com/HKUDS/Vibe-Trading/pull/1478)), dan tabel credit spread menggabungkan kolom tenor `5` / `5.0` yang ekuivalen ([#1507](https://github.com/HKUDS/Vibe-Trading/pull/1507)).

- **2026-09-19** 🛠️ **Error data yang terlihat seperti disclosure hilang atau provider yang salah**: data jumlah pemegang saham A-share kembali berfungsi setelah perubahan nama kolom dari upstream; query yang ditolak sekarang menampilkan error dari provider alih-alih menyatakan bahwa saham tersebut tidak memiliki disclosure ([#1490](https://github.com/HKUDS/Vibe-Trading/pull/1490)). Provenance market data sekarang mencatat loader yang benar-benar menyediakan data untuk setiap simbol, beserta fallback flag dan adjustment label yang sesuai, bahkan ketika SDK yang diminta tidak tersedia ([#1491](https://github.com/HKUDS/Vibe-Trading/issues/1491)). QVeris tidak lagi menimpa `indicators` dengan end date ([#1496](https://github.com/HKUDS/Vibe-Trading/pull/1496)); pemilihan adjustment, parsing respons adjusted, dan billing masih dilacak di [#1494](https://github.com/HKUDS/Vibe-Trading/issues/1494). Terima kasih [@cgycorey](https://github.com/cgycorey) dan [@lorenzozanee](https://github.com/lorenzozanee)!

- **2026-09-18** ✂️ **Jawaban yang disunting kehilangan nomor barisnya, dan satu order kekurangan dana dihitung sebagai dua puluh enam kegagalan**: ketika grounding gate merilis jawaban setelah angka yang belum terverifikasi dipotong, tabel peringkat kembali dengan `(omitted※)` menggantikan 1, 2, 3, `12m` pada header, dan "3 names" di prose. Setiap bilangan bulat di sel tabel sebelumnya dihitung sebagai pengukuran, lalu digit dari setiap angka yang dipotong ikut disapu dari halaman lain. Sekarang kolom nomor baris diperlakukan sebagai struktur, bilangan bulat biasa di samping kata dalam sel dibaca seperti dalam kalimat, dan proses pembersihan tidak lagi memakai satu digit sebagai kunci; return dan multiple yang dibuat-buat tetap dipotong ([#1471](https://github.com/HKUDS/Vibe-Trading/issues/1471)). Dalam mode `hold`, pencarian yang mengecilkan basket agar sesuai dengan kas tersedia sebelumnya mencatat penolakan `zero_size` di setiap langkah, sehingga satu kontrak yang tidak dapat dibeli terbaca sebagai 26 kegagalan pembulatan lot; sekarang menjadi satu `insufficient_capital` ([#1470](https://github.com/HKUDS/Vibe-Trading/issues/1470)). **Diperbaiki:** kode `local:` pada backtest hanya dilayani dari dataset Anda sendiri atau ditolak, tidak pernah diisi dari sumber jaringan ([#1467](https://github.com/HKUDS/Vibe-Trading/issues/1467)); standard error CAR event-study kini memasukkan kovarians antar-forecast harian yang berbagi parameter estimasi — dengan estimation window 30 hari, varians CAR terstandarisasi pada null event turun dari 1.41–1.46 menjadi 1.07–1.08 ([#1466](https://github.com/HKUDS/Vibe-Trading/issues/1466)); hasil nyata `historical_var` / `parametric_var` kini menjadi dasar VaR yang dikembalikan ([#1464](https://github.com/HKUDS/Vibe-Trading/issues/1464)); dan dua puluh alpha tidak lagi mengisi bar yang hilang dengan konstanta, sementara recursive smoother melewati gap dan melanjutkan berdasarkan aturan yang kini terdokumentasi dan diuji ([#1463](https://github.com/HKUDS/Vibe-Trading/issues/1463)). **Kemudian pada hari yang sama:** konfigurasi biasa `LANGCHAIN_PROVIDER=openai` dengan `gpt-5.6-terra` gagal pada tool call pertama karena Chat Completions menolak function tools untuk model `gpt-5.6` kecuali reasoning effort diatur ke `none`. Adapter sekarang mencoba ulang request tersebut sekali melalui `/v1/responses`, tetap mempertahankan reasoning, lalu mengingat route itu untuk model tersebut ([#1473](https://github.com/HKUDS/Vibe-Trading/issues/1473)). **Baru:** OpenCode Go / Zen tersedia sebagai provider bawaan `opencode` dan mengirim `x-opencode-session` yang dibutuhkan relay, termasuk pada thread compaction ([#1416](https://github.com/HKUDS/Vibe-Trading/pull/1416), menutup [#1415](https://github.com/HKUDS/Vibe-Trading/issues/1415)). **Digabungkan:** entry yang sudah diarsipkan memory GC tidak lagi ikut dikirim ke compression ([#1450](https://github.com/HKUDS/Vibe-Trading/pull/1450)); Patell z kini menggunakan degrees of freedom masing-masing normal-return model ([#1449](https://github.com/HKUDS/Vibe-Trading/pull/1449)); estimator microstructure menolak input NaN dan infinite alih-alih mengembalikan spread nol ([#1451](https://github.com/HKUDS/Vibe-Trading/pull/1451)); source yang tidak boleh fallback ke network kini mempertahankan aturan tersebut juga saat mengisi gap per simbol ([#1441](https://github.com/HKUDS/Vibe-Trading/pull/1441)); dan backtest membandingkan interval yang dideklarasikan dengan jarak bar yang benar-benar diterima sebelum melakukan annualization, sehingga file daily yang dideklarasikan `1H` tidak lagi diannualisasi menggunakan frekuensi hourly dan file weekly diannualisasi dengan faktor 52 ([#1432](https://github.com/HKUDS/Vibe-Trading/pull/1432)). Terima kasih [@5gaLbt](https://github.com/5gaLbt) dan [@turtle696966969696](https://github.com/turtle696966969696) atas laporannya, serta [@tonydo](https://github.com/tonydo), [@Shizoqua](https://github.com/Shizoqua), dan [@chiww](https://github.com/chiww) atas perbaikannya!

- **2026-09-17** 🔐 **Satu login Robinhood dapat mengakses beberapa akun, sementara live gate menolak setiap order nyata walau test lulus**: Robinhood kini dapat menjadi sumber portofolio read-only yang membaca tepat satu akun yang dipilih dari daftar akun Robinhood sendiri tanpa pilihan awal ([#1428](https://github.com/HKUDS/Vibe-Trading/issues/1428)), dan live trading mengikat setiap mandat ke satu akun dengan cara yang sama ([#1442](https://github.com/HKUDS/Vibe-Trading/issues/1442)). Runner dan pre-trade gate sebelumnya memanggil Robinhood tanpa akun dan membaca respons satu level terlalu dangkal, sehingga setiap rekonsiliasi dibatalkan dan setiap order ditolak, sementara test tetap hijau karena fixture memakai bentuk respons yang tidak pernah dikirim Robinhood. Posisi ditampilkan tanpa harga sampai respons quote dipetakan. **Diperbaiki:** swarm worker menyimpan log pesan pada setiap jalur keluar yang menulis ringkasan ([#1439](https://github.com/HKUDS/Vibe-Trading/pull/1439)); hitungan hari naik/turun qlib158 tidak lagi menganggap close yang hilang sebagai hari flat ([#1459](https://github.com/HKUDS/Vibe-Trading/pull/1459)); pemeriksaan decay strategi tidak lagi menganggap Sharpe tak terhingga sebagai kondisi sehat ([#1447](https://github.com/HKUDS/Vibe-Trading/pull/1447)); dan root alpha-zoo kustom tidak lagi menggantikan alpha bawaan dengan nama yang sama untuk seluruh proses ([#1468](https://github.com/HKUDS/Vibe-Trading/pull/1468)). Terima kasih [@balu1866](https://github.com/balu1866), [@cgycorey](https://github.com/cgycorey), dan [@0xouzm](https://github.com/0xouzm)!

- **2026-09-16** 🧪 **Empat kesalahan numerik yang masing-masing menghasilkan angka yang tampak masuk akal**: kata "low" berada di lexicon sentimen sebagai kata bullish sekaligus bearish sehingga saling membatalkan ([#1448](https://github.com/HKUDS/Vibe-Trading/pull/1448)); deteksi head-and-shoulders membagi dengan rata-rata shoulder bertanda, sehingga shoulder yang timpang pada series bernilai negatif lolos pemeriksaan simetri ([#1456](https://github.com/HKUDS/Vibe-Trading/pull/1456)); options engine melakukan annualization dengan satu bar lebih sedikit dibanding metrik bersama sehingga membesar-besarkan run pendek ([#1458](https://github.com/HKUDS/Vibe-Trading/pull/1458)); dan pseudo-observation copula memberi peringkat nilai yang hilang sebagai nilai terbesar serta memberi rank berbeda secara arbitrer pada nilai yang tie ([#1453](https://github.com/HKUDS/Vibe-Trading/pull/1453)). Terima kasih @Shizoqua.

- **2026-09-15** 🧮 **Grounding gate yang menentukan arti suatu angka dari kata-kata di sekitarnya**: sebelumnya, pemeriksaan yang harus dilewati setiap jawaban market sebelum dirilis menebak apakah sebuah angka merupakan harga, target, atau metrik berdasarkan katalog frasa — 65 regular expression yang terus bertambah satu fix commit untuk setiap variasi wording dan bahkan dapat memberi verdict berbeda pada sebuah kalimat dan terjemahannya. Sekarang model mendeklarasikan peran setiap angka dalam blok `figures` yang tidak terlihat oleh pembaca (`observed`, `derived`, `proposed`, `cited`, `count`); gate hanya membaca bentuk angkanya dan memeriksa setiap deklarasi terhadap hasil tool pada sesi tersebut. Jawaban yang ditolak mendapat satu kesempatan koreksi yang menyebut setiap angka yang gagal beserta observed print terdekat; jika masih gagal, jawaban dirilis dengan hanya angka-angka tersebut yang dipotong (`（略※）` / `(omitted※)`) alih-alih seluruh jawaban diganti dengan refusal bawaan, yang kini hanya dipakai untuk masalah identitas instrumen atau run yang sama sekali tidak mengobservasi harga. Selama menunggu, chat menampilkan "Memeriksa angka dalam jawaban ini" dalam delapan bahasa. Sebelum dirilis, mekanisme ini melewati tiga putaran adversarial review dan run model nyata, yang menambahkan penanganan untuk koma desimal, harga yang bentuknya seperti tahun, code fence tanpa language tag, harga integer untuk instrumen bernilai ribuan, harga yang dideklarasikan sebagai count, dan angka yang belum diperiksa tetapi sempat masuk ke stream. Count metadata dan token nama metrik tidak lagi cukup untuk menjadi grounding suatu metrik, dan satu kalimat dengan beberapa metrik tidak lagi ditolak ([#1418](https://github.com/HKUDS/Vibe-Trading/issues/1418), [#1420](https://github.com/HKUDS/Vibe-Trading/issues/1420), [#1421](https://github.com/HKUDS/Vibe-Trading/issues/1421), [#1426](https://github.com/HKUDS/Vibe-Trading/issues/1426), [#1433](https://github.com/HKUDS/Vibe-Trading/issues/1433)). Terima kasih [@zeus229](https://github.com/zeus229), [@he-yufeng](https://github.com/he-yufeng), dan [@5gaLbt](https://github.com/5gaLbt)!

- **2026-09-14** 🇰🇷 **A-share yang dibacktest sebagai perpetual futures, dan argumen swarm yang dapat diatur model tetapi tidak pernah benar-benar berubah**: setiap data source tanpa branch khusus yang melayani A-share — `local`, `tencent`, `eastmoney`, `baostock`, `mootdx`, `sina` — merutekan basket A-share murni ke crypto engine, yang tidak menerapkan aturan A-share apa pun (stamp tax, T+1, price limit, lot 100 saham) tetapi tetap mengenakan perpetual funding fee setiap 8 jam pada posisi. Run tetap sukses dan metriknya konsisten secara internal, justru itulah yang membuatnya berbahaya; sekarang basket A-share murni selalu masuk ke `ChinaAEngine` dari source mana pun ([#1431](https://github.com/HKUDS/Vibe-Trading/pull/1431)). Secara terpisah, swarm worker menimpa `run_dir` setiap tool call dengan workspace agent, sehingga untuk tool yang mendeklarasikannya — terutama `backtest` — model dapat mengirim directory apa pun tetapi tidak pernah membacanya, sementara error tidak menyebut path. `run_dir` yang dideklarasikan sekarang dihormati jika berada di dalam workspace dan ditolak jika di luar dengan boundary yang disebutkan; tool backtest juga menyebut directory yang diperiksanya ([#1430](https://github.com/HKUDS/Vibe-Trading/pull/1430), [#1429](https://github.com/HKUDS/Vibe-Trading/pull/1429)). **Baru:** empat connector masuk sekaligus sehingga totalnya menjadi 18 — **KIS** (한국투자증권; paper sandbox 모의투자 sungguhan pada host tersendiri, plus live read-only), **Upbit** (crypto KRW; paper + live read-only, dibatasi karena exchange tidak menyediakan discriminator paper/live), **Toss Securities** (live read-only; history closed-order dipaginasi sampai selesai dan ditolak alih-alih dipotong jika melewati cap; read path divalidasi terhadap akun nyata), serta Agentic MCP milik **Scalable Capital** sebagai profile sepenuhnya read-only dengan tool allowlist eksplisit dan tanpa kemampuan order ([#1407](https://github.com/HKUDS/Vibe-Trading/pull/1407), [#1408](https://github.com/HKUDS/Vibe-Trading/pull/1408), [#1409](https://github.com/HKUDS/Vibe-Trading/pull/1409), [#1417](https://github.com/HKUDS/Vibe-Trading/pull/1417)). **Diperbaiki:** diagnostics SDK bersama sebelumnya menyuruh pengguna setiap broker memeriksa Longbridge; sekarang dalam semua delapan bahasa pesan tersebut menyebut SDK atau gateway milik broker yang benar-benar terdampak ([#1436](https://github.com/HKUDS/Vibe-Trading/pull/1436)). Terima kasih [@chiww](https://github.com/chiww), [@cgycorey](https://github.com/cgycorey), [@as950118](https://github.com/as950118), [@dudco](https://github.com/dudco), dan [@tingkk](https://github.com/tingkk)!

- **2026-09-13** 🗂️ **Respons broker dengan bentuk yang salah dihitung sebagai akun kosong, dan diagnostics run card yang tidak pernah sampai ke card**: layer portfolio sebelumnya membaca positions dengan list kosong sebagai default, sehingga respons yang sama sekali tidak membawa list positions — misalnya respons MCP yang mapping-nya belum tersedia atau MCP resmi IBKR yang menjawab tanpa structured positions — berubah menjadi source tanpa holdings dan snapshot disimpan sebagai lengkap. Padahal agregasi justru dibuat untuk mencegah portfolio yang diam-diam menjadi lebih kecil seperti ini, jadi sekarang read tanpa list positions ditolak: source tampil sebagai error dan snapshot ditandai incomplete, sedangkan akun yang benar-benar kosong (`"positions": []`) tetap dibaca sebagai kosong. Masalah ini muncul saat mereview connector MCP baru yang holdings-nya belum dimapping. Secara terpisah, run card sebelumnya hanya menyimpan metrik scalar, sehingga setiap diagnostic berbentuk dict atau list yang ditulis engine untuk pembaca card hilang — pengguna dapat melihat berapa banyak plan yang ditolak, tetapi tidak untuk simbol mana atau alasannya. Sekarang metrik tersebut dibawa dalam blok `structured_metrics`, dibatasi 4 KiB JSON UTF-8 per metrik dengan data yang lebih besar disebut di `_omitted`, dan dirender pada tab Run Card dalam delapan bahasa ([#1424](https://github.com/HKUDS/Vibe-Trading/pull/1424)). Terima kasih [@cgycorey](https://github.com/cgycorey)!

- **2026-09-12** 📥 **Baris dividen yang terlihat seperti holding, dan format angka di mana satu separator yang salah menghasilkan error seribu kali lipat**: export CSV extraETF sekarang dapat dibaca ke bentuk position milik layer portfolio — read-only, hanya memakai standard library, dan fail-closed untuk apa pun yang tidak dapat dibaca tanpa menebak ([#1406](https://github.com/HKUDS/Vibe-Trading/pull/1406), menuju [#1170](https://github.com/HKUDS/Vibe-Trading/issues/1170)). Export Investments menjadi positions dan export Transaktionen menjadi typed movements, sehingga baris `Dividende`, yang memiliki quantity dan price sendiri, tidak pernah dibaca sebagai position, dan file transaksi tidak dapat menyamar sebagai portfolio kosong. Angka mengikuti grammar Jerman dari export tersebut secara persis: `1.386,608` berarti 1386.608, format urutan AS `1,234.56` ditolak alih-alih dibaca dengan nilai seribu kali meleset, dan nilai yang tidak muat dalam wire format delapan desimal ditolak alih-alih dibulatkan — `0,000000004` saham sebaliknya akan menjadi nol. Header yang tidak dikenal (error menyebut kedua set kolom yang diketahui), label transaksi yang tidak dikenal, movement tanpa instrumen, dan satu instrumen yang muncul dua kali di bawah satu portfolio ID semuanya ditolak, sedangkan ISIN yang sama di bawah dua portfolio ID — kasus normal untuk export multi-portfolio — tetap menjadi dua position. Export tidak membawa tanggal snapshot, jadi modification time file dilaporkan sebagai `source_mtime` dan tidak ada position yang mengklaim observation time. Reader ini belum dipanggil oleh apa pun; langkah berikutnya adalah menghubungkannya ke portfolio container. Terima kasih [@cgycorey](https://github.com/cgycorey) dan [@KaiLuettmann](https://github.com/KaiLuettmann)!

- **2026-09-11** 📉 **Delapan tahun history Tencent yang kembali sebagai dua tahun terakhir, dan evidence gate yang menolak setiap backtest yang dijalankan agent sendiri**: endpoint `fqkline` Tencent menyediakan **500 bar terakhir** dari sebuah window, bukan 500 pertama — request CSI 300 untuk `2018-01-01..2026-06-30` mengembalikan `2024-06-06..2026-06-30` — sementara loader melakukan pagination maju, melewati akhir window setelah satu page, lalu mengembalikan series yang hanya berisi bagian akhir dengan exit code 0 dan tanpa warning. Sekarang loader berjalan mundur dari end date, meminta ulang page kosong satu kali sebelum mempercayainya, menganggap respons berbentuk error sebagai failure, dan menaikkan versi cache loader agar series yang dicache oleh traversal lama tidak pernah disajikan lagi ([#1411](https://github.com/HKUDS/Vibe-Trading/pull/1411), menutup [#1410](https://github.com/HKUDS/Vibe-Trading/issues/1410)). `refresh_strategy_evidence` sebelumnya menolak setiap run yang dibuat tool `backtest`, karena hanya agent runtime yang menulis `state.json` yang dibaca ingestion gate; sekarang tool tersebut sendiri mencatat success, failure, dan timeout, sementara gate tetap fail-closed untuk run yang tidak memiliki pihak yang menjaminnya ([#1413](https://github.com/HKUDS/Vibe-Trading/pull/1413), menutup [#1412](https://github.com/HKUDS/Vibe-Trading/issues/1412)). Request data cold-start yang berjalan bersamaan juga dapat kembali sebagai `_unresolved` untuk simbol yang sebenarnya tersedia: loader registry menandai dirinya initialized sebelum import selesai, sehingga caller pertama yang datang bersamaan melihat registry kosong — tujuh dari delapan pada run pelapor ([#1405](https://github.com/HKUDS/Vibe-Trading/pull/1405), menutup [#1403](https://github.com/HKUDS/Vibe-Trading/issues/1403)). List `skills:` milik swarm worker, yang didokumentasikan sebagai allowlist, sekarang benar-benar ditegakkan oleh `load_skill` bukan hanya oleh prompt ([#1414](https://github.com/HKUDS/Vibe-Trading/pull/1414)), dan contoh Engle-Granger pada correlation skill, yang crash pada series tanpa nama, sekarang memanggil fungsi quantlib yang sudah diuji alih-alih melakukan fit OLS sendiri ([#1404](https://github.com/HKUDS/Vibe-Trading/pull/1404)). Satu lagi berasal dari kami sendiri: tiga belas file config broker yang menyimpan API key — `alpaca.json`, `zerodha.json`, dan lainnya — tidak tercantum di `.gitignore` walau komentarnya mengklaim demikian, sehingga siapa pun yang `VIBE_TRADING_HOME`-nya menunjuk ke checkout hanya berjarak satu `git add -A` dari tidak sengaja mengcommit credentials; sekarang test menurunkan daftar tersebut langsung dari code. Hal serupa terjadi pada paper cancel yang mengaku membatalkan order yang tidak pernah dibuatnya: connector paper Zerodha, Dhan, dan Shoonya mensimulasikan order secara lokal tetapi membaca akun nyata, dan sebelumnya menerima cancel untuk order ID apa pun — termasuk live order yang sebenarnya akan tetap aktif; sekarang hanya ID yang dikeluarkan simulator mereka sendiri yang diterima. Terima kasih [@shadowinlife](https://github.com/shadowinlife), [@alanwilhelm](https://github.com/alanwilhelm), dan [@Shizoqua](https://github.com/Shizoqua)!

- **2026-09-10** 🧾 **Pesan remediation yang menyebut variabel yang tidak pernah dibaca, dan adapted strategy yang membawa sign-off milik parent-nya**: ketika stooq menjawab dengan halaman anti-bot challenge, loader memberi tahu operator cara menghindarinya — tetapi kedua bagian instruksi itu tidak dapat digunakan seperti yang tertulis. `VIBE_TRADING_MARKET_DATA_ORDER_*` tidak dibaca di mana pun: registry membangun `MARKET_DATA_ORDER_<MARKET>` dan config layer meneruskannya ke `os.getenv` tanpa prefix tambahan, sehingga mengekspor nama yang tercetak hanya menjadi no-op tanpa suara dan stooq tetap berada di posisi 2 chain US-equity. Bagian lain, "hapus stooq dari sana", ditolak mentah-mentah — override harus berupa **permutasi** dari chain default, jadi source dapat diurutkan ulang tetapi tidak dapat dihapus. Pesan sekarang menyebut variabel yang benar-benar dibaca registry dan menjelaskan constraint tersebut, diikat ke registry alih-alih literal agar tidak drift lagi ([#1402](https://github.com/HKUDS/Vibe-Trading/pull/1402)). Secara terpisah, paruh pertama adaptation strategy berbasis description telah masuk: adapted strategy adalah artifact **baru** yang menunjuk parent melalui `derived_from`; description boleh mengubah universe, nama, dan position sizing sementara signal disalin persis, dan child dimulai dengan evidence kosong agar angkanya berasal dari backtest-nya sendiri, bukan mewarisi angka parent ([#1391](https://github.com/HKUDS/Vibe-Trading/pull/1391), refs [#1149](https://github.com/HKUDS/Vibe-Trading/issues/1149)). Dua celah ditutup selama proses tersebut, keduanya hanya terpaut satu field dari rule yang hendak ditegakkan PR itu. `dataclasses.replace` menyalin setiap field yang tidak disebut dalam call, sehingga child keluar sebagai `UNVALIDATED` tetapi masih membawa `validator` dan `approver` milik parent — sign-off independen yang dipakai oleh sesuatu yang belum pernah mendapatkannya — bersama `artifact_version` dan `model_version` untuk code yang bahkan belum dibuat oleh model. Selain itu, parent-evidence gate hanya dapat dicapai dari test: `register_adaptation` tidak pernah berkonsultasi dengannya, sehingga parent yang stale atau insufficient tetap ditulis, bertentangan dengan contract substrate. Sekarang input-nya keyword-only dan wajib, sehingga check tidak dapat dilewati hanya karena terlupa. Terima kasih [@chiww](https://github.com/chiww) dan [@modelpath-dev](https://github.com/modelpath-dev)!

- **2026-09-09** 🚀 **v0.1.15 dirilis** ([Catatan rilis](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.15), `pip install -U vibe-trading-ai`): 551 commit dan 162 pull request digabungkan sejak 0.1.14, dari 35 contributor. **Tema cycle ini adalah data yang menyatakan apa dirinya sebenarnya** — dan tiga fix terbesar ternyata merupakan bug yang sama dalam bentuk berbeda: default yang diam-diam mengganti nilai hilang dengan angka yang tampak masuk akal, sehingga downstream tidak dapat membedakannya dari observation nyata. Contract NaN milik Alpha Zoo dipindahkan dari alpha individual ke registry: alpha yang bercabang pada perbandingan `np.where` tidak pernah melihat NaN — hasil perbandingannya `False` — sehingga ketika semua input yang dideklarasikan dikosongkan pada satu bar, **84 dari 462 alpha tetap mengembalikan angka**, dan semuanya dikonsumsi sebagai signal nyata karena `dropna()` yang menjaga gap keluar dari IC. Registry sekarang memask output menjadi NaN di mana pun dependency yang dideklarasikan hilang pada bar tersebut, dan sweep yang sama setelahnya tidak menemukan satu pun ([#1377](https://github.com/HKUDS/Vibe-Trading/pull/1377), menutup [#1376](https://github.com/HKUDS/Vibe-Trading/issues/1376)). Separuh contract mengenai warmup tetap dibuka dan dinyatakan apa adanya alih-alih diam-diam ditutupi: **52 alpha masih menghasilkan nilai di dalam `min_warmup_bars` yang mereka deklarasikan sendiri**, dan warmup mask pada level registry juga akan mengosongkan baris bagi alpha yang hanya terlalu konservatif dalam deklarasinya, jadi bagian itu membutuhkan keputusan arah desain, bukan 52 PR terpisah. Kelas bug yang sama, kasus kedua: pandas masih menggunakan forward-fill sebagai default `pct_change()`, sehingga close yang hilang berubah menjadi **return 0.0% yang tidak pernah terjadi**; empat PR memperbaiki masing-masing satu call site, lalu exhaustive sweep menemukan **24 site di 10 file** — dua di antaranya berada di file yang sedang diedit PR tersebut. Kasus ketiga: chain loader `futures` menyebut `tushare` dan `akshare`, tetapi **keduanya sama sekali tidak mengimplementasikan endpoint futures**, sehingga setiap kontrak jatuh ke endpoint equity A-share. AKShare sekarang melayani kontrak China dari endpoint daily Sina tanpa key — baik dated maupun main-continuous, diverifikasi live pada SHFE, CFFEX, GFEX, dan ZCE — sementara kontrak global mengembalikan empty dan mencapai `local` alih-alih dihargai sebagai equity ([#1395](https://github.com/HKUDS/Vibe-Trading/issues/1395)). Harga sekarang juga membawa adjustment caliber yang digunakan saat disajikan, dan source yang caliber-nya belum pernah diukur terhadap payload live melaporkan `unknown` alih-alih menebaknya ([#1317](https://github.com/HKUDS/Vibe-Trading/pull/1317)). **Live trading kini fail-closed** di lima tempat tambahan: read posisi broker yang mengembalikan API error, error envelope yang datang di tengah halt-sweep, flatten latch saat runner restart, submission Alpaca unresolved yang dipulihkan lewat exact client ID setelah restart, dan buy-limit order yang disizing berdasarkan harga terburuk antara quote dan limit pada kedua transport. **Di backtest**: signal options fill pada bar berikutnya, bukan tanggal saat signal dihitung; short option leg menahan margin dan gate dibuka berdasarkan buying power; perpetual funding settle berdasarkan span bar untuk interval 8h+; basket rebalance yang over-committed diskalakan alih-alih abort; dan halted position dimark pada last traded close, bukan entry cost. **Di agent loop**: sebuah sesi yang sudah mengambil fundamentals, fund flow, margin, dan research data sebelumnya membersihkan hasil tersebut untuk membebaskan context, tetapi de-duplication ledger tetap menolak fetch ulang — **44 retry diblokir dalam satu run**, berakhir dengan "fundamental data not retrieved" untuk data yang sebenarnya sudah pernah diterima model; sekarang result direkonsiliasi berdasarkan exact call identity dan no-progress budget menghitung observation, bukan activity. Batch terakhir sebelum tag membawa tiga tema yang sama dalam bentuk lebih kecil. `CL2412.NYMEX` tidak cocok dengan pattern simbol mana pun — bentuk dated tanpa venue (`CL2412`) cocok, bentuk venue (`ES.CME`) juga cocok, tetapi bentuk kontrak yang benar-benar dipakai tidak cocok dengan keduanya — sehingga kontrak crude oil AS berjalan di bawah aturan T+1, tanpa shorting, dan settlement CNY; spelling exchange milik Tushare memiliki masalah cermin di sisi China, dan kini kedua bentuk diklasifikasikan dengan benar ([#1396](https://github.com/HKUDS/Vibe-Trading/pull/1396), menutup [#1394](https://github.com/HKUDS/Vibe-Trading/issues/1394)). Call site `pct_change()` sedang diperbaiki satu per satu ([#1397](https://github.com/HKUDS/Vibe-Trading/pull/1397), [#1398](https://github.com/HKUDS/Vibe-Trading/pull/1398)) sebelum exhaustive sweep menemukan sisanya; default yang sama juga berada di balik TopN selection yang meranking asset tanpa factor observation ([#1399](https://github.com/HKUDS/Vibe-Trading/pull/1399)) dan sentiment orthogonalization yang melakukan regresi terhadap nol yang diisinya sendiri ([#1400](https://github.com/HKUDS/Vibe-Trading/pull/1400)). Run China-futures sekarang menyatakan produk mana yang dihargai menggunakan generic default alih-alih entry table — margin rate nyata `rb` adalah 0.10, sama dengan nilai default, tetapi "looked up" tidak boleh terbaca seolah "assumed" (menutup [#1393](https://github.com/HKUDS/Vibe-Trading/issues/1393)). Contoh ML walk-forward juga sekarang melakukan purge future labels ([#1392](https://github.com/HKUDS/Vibe-Trading/pull/1392)). **Baru pada cycle ini:** equity UK (LSE `.L`/`.IL`, dengan SDRT dimodelkan hanya sebagai duty pada sisi pembelian karena mengenakan biaya pada kedua sisi melebihkan setiap round trip sebesar setengahnya), **Zerodha Kite Connect** sebagai broker ke-14 (dibatasi pada paper plus read-only karena Kite tidak menyediakan runtime discriminator live), **portfolio multi-broker read-only** di Web, REST, CLI, dan agent tool di mana source yang gagal refresh menjadi error yang dikeluarkan dari total, bukan stale cache, **lima belas penambahan Quant Library** (Heston, Hierarchical Risk Parity, copula, microstructure VPIN/Roll/Amihud/Kyle, barrier options dengan finite-difference Greeks, ISDA CDS, Key Rate Duration, Vasicek, factor IC, Ornstein-Uhlenbeck, Ulcer/Pain, event-study tests, group-purged CV), **Português Brasileiro** sebagai locale kedelapan, **Nobitex dan Wallex** read-only, partial rebalancing berbasis calendar trigger, swarm replay dan retry, serta **offline evals harness** yang menghasilkan `NOT_EVALUABLE` alih-alih pass ketika instrumentation yang dibutuhkannya tidak tersedia. Terima kasih kepada seluruh 35 contributor pada cycle ini!

- **2026-09-08** 🧪 **Alpha yang mencetak angka untuk bar dengan input kosong, dan pencarian spot gold yang menjawab dengan ETP Bitcoin Swedia**: contract Alpha Zoo mempertahankan NaN selama warmup dan missing data, tetapi alpha yang bercabang pada perbandingan `np.where` tidak pernah melihat NaN — perbandingannya menghasilkan `False`, sehingga ternary jatuh ke konstanta. Ketika setiap input yang dideklarasikan dikosongkan pada satu bar dalam sweep 462 alpha, **84 alpha tetap mengembalikan angka**, dan karena `dropna()` yang menjaga gap keluar dari IC, setiap konstanta tersebut dikonsumsi sebagai signal nyata. Guard sekarang berada di registry alih-alih di masing-masing alpha — output dimask menjadi NaN di mana pun dependency yang dideklarasikan hilang pada bar itu — dan sweep yang sama setelahnya tidak menemukan satu pun ([#1377](https://github.com/HKUDS/Vibe-Trading/pull/1377), menutup [#1376](https://github.com/HKUDS/Vibe-Trading/issues/1376)). Sebelas alpha diperbaiki untuk separuh contract lainnya, yaitu warmup window ([#1379](https://github.com/HKUDS/Vibe-Trading/pull/1379), [#1380](https://github.com/HKUDS/Vibe-Trading/pull/1380), [#1381](https://github.com/HKUDS/Vibe-Trading/pull/1381), [#1382](https://github.com/HKUDS/Vibe-Trading/pull/1382), [#1383](https://github.com/HKUDS/Vibe-Trading/pull/1383)) — dan pengukuran yang sama pada bagian itu masih menyisakan **52 alpha yang menghasilkan nilai di dalam `min_warmup_bars` mereka sendiri**. Warmup mask pada level registry juga akan mengosongkan baris bagi alpha yang sekadar over-declare, jadi bagian tersebut tetap dibuka dan dinyatakan apa adanya alih-alih ditutupi diam-diam. Secara terpisah, `search_symbol("XAUUSD")` mengembalikan tepat satu candidate — `VALOUR-BTC-0-SEK.ST`, ETP Bitcoin Swedia — yang kemudian mengunci instrument identity run; sekarang query pasangan metal atau FX dianggap sebagai exact instrument assertion dan hanya mempertahankan candidate yang menyebut dua leg yang sama dalam spelling apa pun ([#1282](https://github.com/HKUDS/Vibe-Trading/pull/1282)). **Diperbaiki:** tanggal announcement tidak membawa time-of-day, sehingga pada frame intraday sebuah filing sebelumnya terlihat sejak bar pertama pada hari announcement itu sendiri — lookahead sepanjang satu sesi. Frame sub-daily sekarang ditolak, dengan `fundamental_subdaily="next_day"` sebagai opt-in eksplisit (menutup [#1387](https://github.com/HKUDS/Vibe-Trading/issues/1387)). Klaim metrik yang diformat sebagai tabel generic `| Metric | Value |` lolos dari analysis gate yang menolak klaim sama dalam prose ([#1375](https://github.com/HKUDS/Vibe-Trading/pull/1375)), sedangkan error kebalikannya menolak kata harga yang dipakai sebagai variable formula — `close/SMA50 > 1` dibaca sebagai asserted price ([#1378](https://github.com/HKUDS/Vibe-Trading/pull/1378), menutup [#1354](https://github.com/HKUDS/Vibe-Trading/issues/1354)). Broker code yang dipaste (`HK.00700`, `US.AAPL`, `SH.600519`) sebelumnya discan seolah tidak ada simbol sama sekali, sehingga setiap market tool menjawab `identity_required` ([#1384](https://github.com/HKUDS/Vibe-Trading/pull/1384)). Tiga CDF Archimedean copula mengembalikan extreme value yang salah saat dependence kuat — Clayton `0.0`, Gumbel `1.0`, Frank `inf` — dan sekarang dihitung dalam log space, diverifikasi terhadap referensi 2500 digit pada θ ∈ [-5000, 5000] ([#1386](https://github.com/HKUDS/Vibe-Trading/pull/1386), menutup [#1385](https://github.com/HKUDS/Vibe-Trading/issues/1385)). Order MT5 di atas volume cap simbol sebelumnya diclamp dan dikirim diam-diam, eToro limit order tanpa limit price dibiarkan resting tanpa pernah terpicu tetapi terbaca accepted, K-line Futu mewarisi adjustment caliber yang tidak dideklarasikan, dan `BTCUSDT` dirutekan melalui aturan A-share — T+1 dan tanpa shorting, pada perpetual ([#1388](https://github.com/HKUDS/Vibe-Trading/pull/1388)). Terima kasih [@cgycorey](https://github.com/cgycorey), [@Shizoqua](https://github.com/Shizoqua), [@he-yufeng](https://github.com/he-yufeng), [@Robin1987China](https://github.com/Robin1987China), [@laiyierjiangsu](https://github.com/laiyierjiangsu), [@aminak58](https://github.com/aminak58), dan [@nandofmike](https://github.com/nandofmike)!

- **2026-09-07** 🪙 **Order emas 50 ounce yang dibulatkan menjadi nol, dan currency future yang dihargai hanya 1/2500 dari contract size-nya**: dalam cross-market backtest, composite engine merutekan setiap simbol melalui satu shared sub-engine per market, tetapi hanya `apply_slippage` yang merefresh active symbol milik sub-engine tersebut — akibatnya `round_size` dan `calc_commission` memakai simbol mana pun yang terakhir tersinkron. Position emas 50 oz yang disizing menggunakan micro lot FX 1.000 unit dibulatkan menjadi **0**, gold futures dikenai fee berbasis rate milik index future (6.90) alih-alih flat fee-nya sendiri (20.00), dan swap memakai standard lot 100.000 unit alih-alih metal lot 100 oz ([#1370](https://github.com/HKUDS/Vibe-Trading/pull/1370)). Secara terpisah, `_extract_product` tidak dapat membaca simbol yang product code-nya mengandung digit atau berakhir dengan huruf yang juga merupakan month code: `6EZ4`, `6JH25`, `M2K`, `MYM2503`, dan `FESX2503` semuanya jatuh ke default multiplier 50 — padahal untuk `6E` nilai sebenarnya adalah 125.000 ([#1369](https://github.com/HKUDS/Vibe-Trading/pull/1369)). Sekarang simbol diresolve langsung terhadap multiplier table, longest match terlebih dahulu, yang juga mencakup bentuk dated (`M2KZ4`) dan prefix collision (`SILZ4` vs `SI`). **Diperbaiki:** empat factor Alpha Zoo sebelumnya mencetak nilai tetap ±1 atau 0 selama trading halt dan di dalam warmup yang mereka deklarasikan sendiri, karena perbandingan terhadap NaN menghasilkan `False`, bukan NaN, sehingga ternary jatuh ke konstanta. `min_warmup_bars` hanyalah metadata yang tidak memangkas apa pun, dan `dropna()` yang menjaga gap keluar dari IC — sehingga konstanta tersebut dikonsumsi sebagai signal nyata ([#1371](https://github.com/HKUDS/Vibe-Trading/pull/1371), [#1372](https://github.com/HKUDS/Vibe-Trading/pull/1372), [#1373](https://github.com/HKUDS/Vibe-Trading/pull/1373), [#1374](https://github.com/HKUDS/Vibe-Trading/pull/1374)). Mengukur seluruh zoo dengan cara yang sama menemukan **82 alpha lain dalam kondisi serupa**; alih-alih satu PR per alpha, hal ini sekarang dilacak sebagai registry-level guard di [#1376](https://github.com/HKUDS/Vibe-Trading/issues/1376). Evidence strategy-discovery juga sebelumnya meresolve position size sekali untuk seluruh run, bukan per regime, dan satu benchmark cell yang tidak dapat diparse dapat menghapus semua evidence row yang dihasilkan run tersebut ([#1368](https://github.com/HKUDS/Vibe-Trading/pull/1368)). **Baru:** run yang terus mengeluarkan tool call tanpa memperoleh informasi baru sekarang berhenti setelah delapan iterasi dengan recovery request yang terlihat, alih-alih menghabiskan seluruh budget untuk path discovery — kasus yang dilaporkan membakar sekitar 35 iterasi untuk menebak ulang path yang sama dan terus ditolak. Call identik sekarang ditolak mulai dari **failure kedua**, bukan yang pertama, sehingga satu retry yang wajar setelah rate limit atau timeout tetap dijalankan ([#1363](https://github.com/HKUDS/Vibe-Trading/pull/1363), menutup [#1353](https://github.com/HKUDS/Vibe-Trading/issues/1353)). Terima kasih [@Shizoqua](https://github.com/Shizoqua), [@be-student](https://github.com/be-student), dan [@nandofmike](https://github.com/nandofmike)!

- **2026-09-06** 🛡️ **Buy limit yang disizing pada harga yang tidak akan pernah menjadi fill-nya, dan audit yang mengembalikan PASS tanpa memverifikasi apa pun**: MCP order gate sebelumnya menghitung quantity order hanya dari live quote, sehingga limit di dua kali harga market dapat lolos cap yang disizing untuk quote tersebut dan kemudian fill pada dua kali authorized notional. Sekarang sizing memakai harga yang lebih buruk antara quote dan limit — rule yang sudah dipakai direct-SDK path — dan limit price yang tidak dapat diparse ditolak alih-alih diloloskan ([#1361](https://github.com/HKUDS/Vibe-Trading/pull/1361)). Report auditor sebelumnya melewati setiap point tanpa fetched value lalu melaporkan **PASS** karena tidak ada yang gagal, sehingga mengesahkan report yang sama sekali tidak didukung evidence; sekarang kasus itu fail-closed ([#1362](https://github.com/HKUDS/Vibe-Trading/pull/1362)). **Diperbaiki:** metrik tetap bertahan setelah analysis tool gagal, dan exemption baru untuk attributed figures — tepat untuk Sharpe dari sebuah paper, tetapi salah untuk harga yang seharusnya diobservasi run ini — akan meloloskan `Analysts say TSLA.US last traded at 412.35 USD.` tanpa tool call pendukung ([#1338](https://github.com/HKUDS/Vibe-Trading/pull/1338), menutup [#1336](https://github.com/HKUDS/Vibe-Trading/issues/1336)); baris cash-dividend membuat seluruh trade-journal parse gagal ([#1356](https://github.com/HKUDS/Vibe-Trading/pull/1356)); compaction membuka kembali de-duplication ledger berdasarkan nama tool, sehingga membersihkan satu variant argumen tetap meninggalkan variant lain dalam keadaan gated ([#1358](https://github.com/HKUDS/Vibe-Trading/pull/1358)); compliance ledger menolak append pertama di Windows ([#1261](https://github.com/HKUDS/Vibe-Trading/pull/1261)). **Baru:** Zerodha Kite Connect membuat total broker menjadi 14 — hanya read dan paper, karena Kite tidak menyediakan runtime discriminator paper/live ([#1193](https://github.com/HKUDS/Vibe-Trading/pull/1193)); Nobitex dan Wallex menambahkan pair Iranian Toman untuk 27 data source, dan keduanya tidak dapat diam-diam degrade ke venue berquote USD ([#1263](https://github.com/HKUDS/Vibe-Trading/pull/1263)); native Anthropic call sekarang mengcache prefix tools-and-system statis alih-alih mengirim ulang seluruhnya dengan biaya penuh pada setiap turn ([#1366](https://github.com/HKUDS/Vibe-Trading/pull/1366)). Terima kasih [@cgycorey](https://github.com/cgycorey), [@ashutoshsinghpr7](https://github.com/ashutoshsinghpr7), [@saju01](https://github.com/saju01), [@he-yufeng](https://github.com/he-yufeng), [@Emad211](https://github.com/Emad211), [@averatec0773](https://github.com/averatec0773), [@birdxs](https://github.com/birdxs), dan [@AirHua-byte](https://github.com/AirHua-byte)!

- **2026-09-05** 🔓 **Harga yang dibuat-buat model lolos pemeriksaan dalam bahasa Inggris tetapi tertangkap dalam bahasa Mandarin, dan agent tidak dapat membaca ulang data yang sebelumnya sudah diambil**: grounding gate sebelumnya mencocokkan `close` tetapi tidak **`closed`**, sehingga `The stock closed at 412.35.` tanpa tool call pendukung langsung lolos, sementara klaim palsu identik dalam bahasa Mandarin (`该股收盘 412.35。`) ditolak. `last traded at` dan `quoted at` sama sekali belum memiliki rule, sedangkan bahasa Mandarin memiliki celah kebalikannya — `成交价` / `最新价` / `股价` / `收报` semuanya terlewat. Sekarang kedua vocabulary sudah lengkap, bentuk bahasa Inggris mengharuskan kata "at" setelahnya agar frasa volume dan deal tidak ikut terjaring, dan suite baru memastikan kedua bahasa menghasilkan **verdict yang sama** untuk setiap kasus alih-alih diuji secara terpisah. Secara terpisah, sebuah sesi yang berhasil mengambil fundamentals, fund flow, margin, dan research data kemudian membersihkan hasil tersebut untuk membebaskan context — tetapi de-duplication ledger tetap menolak mengambilnya kembali, menghasilkan 44 retry yang diblokir dalam satu run dan berakhir dengan "fundamental data not retrieved" untuk data yang sebenarnya sudah diterima model. Membersihkan sebuah result sekarang membuka kembali tool tersebut, ledger menggunakan arguments sebagai key alih-alih nama tool, dan token budget menghitung arguments tool-call alih-alih menilai payload 100 KB sebagai sepuluh token ([#1349](https://github.com/HKUDS/Vibe-Trading/pull/1349), [#1341](https://github.com/HKUDS/Vibe-Trading/pull/1341), [#1352](https://github.com/HKUDS/Vibe-Trading/pull/1352), menutup [#1343](https://github.com/HKUDS/Vibe-Trading/issues/1343)). **Diperbaiki:** setiap backtest yang diluncurkan dari Web UI mengalami segfault pada aarch64 — sandbox rlimits menjalankan Python di forked child dari server multi-threaded, undefined behaviour menurut POSIX; sekarang diterapkan setelah exec (menutup [#1355](https://github.com/HKUDS/Vibe-Trading/issues/1355)). `GC=F` dan `XAUUSD` sebelumnya diklasifikasikan sebagai China A-share ([#1280](https://github.com/HKUDS/Vibe-Trading/pull/1280)); `BRK.B.US` dan class share bertitik lainnya mengambil chart kosong ([#1351](https://github.com/HKUDS/Vibe-Trading/pull/1351)); basket rebalance yang fully invested abort karena commission overdraft alih-alih diskalakan agar muat ([#1344](https://github.com/HKUDS/Vibe-Trading/pull/1344), menutup [#1274](https://github.com/HKUDS/Vibe-Trading/issues/1274)); delta percentage-point — `3.6pp`, `3.6 个百分点`, `250 基点` — dibaca sebagai quoted price ([#1346](https://github.com/HKUDS/Vibe-Trading/pull/1346)); joined crypto pair seperti `BTCUSDT` tidak dikenali sementara spot platinum malah diresolve ke crypto pair yang tidak ada ([#1265](https://github.com/HKUDS/Vibe-Trading/pull/1265)); history strategy-store kembali oldest-first ketika timestamp sama ([#1347](https://github.com/HKUDS/Vibe-Trading/pull/1347)); adapter Codex membuang model yang dilaporkan provider ([#1348](https://github.com/HKUDS/Vibe-Trading/pull/1348)). **Baru:** market context yang dinyatakan sebelumnya dalam conversation dapat mempersempit symbol resolution di balik `VIBE_CONTEXTUAL_IDENTITY_CONSTRAINTS` ([#1269](https://github.com/HKUDS/Vibe-Trading/pull/1269)); worker investment-committee sekarang mendapat fundamental data panel yang sebelumnya sudah diasumsikan oleh prompt mereka ([#1345](https://github.com/HKUDS/Vibe-Trading/pull/1345)); serta deterministic USD-M tolerance calibration dari recorded comparisons ([#1248](https://github.com/HKUDS/Vibe-Trading/pull/1248)). Terima kasih [@nandofmike](https://github.com/nandofmike), [@atomfive](https://github.com/atomfive), [@thisisjun786](https://github.com/thisisjun786), [@cgycorey](https://github.com/cgycorey), [@saju01](https://github.com/saju01), [@he-yufeng](https://github.com/he-yufeng), [@aminak58](https://github.com/aminak58), [@AirHua-byte](https://github.com/AirHua-byte), [@lorenzozanee](https://github.com/lorenzozanee), [@ethanstoner](https://github.com/ethanstoner), dan [@Shizoqua](https://github.com/Shizoqua)!

- **2026-09-04** 🩺 **Setiap run Claude 5 gagal pada request pertama, dan halted position dimark kembali ke harga belinya**: `langchain-anthropic` memindahkan `temperature` ke `extra_body` untuk Anthropic SDK saat ini, sementara self-heal kami hanya menghapus key di top level — akibatnya retry mengirim ulang field yang baru saja ditolak API, dan setiap run pada `claude-sonnet-5` / `claude-opus-5` mati pada call pertama ([#1330](https://github.com/HKUDS/Vibe-Trading/pull/1330), menutup [#1329](https://github.com/HKUDS/Vibe-Trading/issues/1329)). Dalam backtest, position yang ditahan melewati batas forward-fill sebelumnya dimark ulang pada entry price: equity menampilkan drawdown tanpa market event yang mendasarinya, dan rebalance sizing berjalan terhadap phantom mark tersebut. Sekarang halt sepanjang apa pun dimark pada last traded close, sementara order fill tetap menolak stale price ([#1332](https://github.com/HKUDS/Vibe-Trading/pull/1332), menutup [#1318](https://github.com/HKUDS/Vibe-Trading/issues/1318)). **Diperbaiki:** tiga cara commit-time adjustment dapat memperlebar mandate yang sudah Anda setujui — angka berbentuk string melewati numeric check, `True` lolos sebagai angka, dan instrument whitelist sama sekali tidak memiliki comparison; cash-only tetap menjadi titik paling bawah pada axis leverage alih-alih dianggap invalid type, sehingga mandate paling aman tetap dapat dicommit ([#1285](https://github.com/HKUDS/Vibe-Trading/pull/1285)). Elapsed clock sekarang bertahan saat berpindah page, reload, dan membuka kembali session dari history ([#1340](https://github.com/HKUDS/Vibe-Trading/pull/1340), menutup [#1339](https://github.com/HKUDS/Vibe-Trading/issues/1339)), dan tujuh npm advisory yang masih terbuka pada lock file frontend dan desktop sudah dipatch. Terima kasih [@averatec0773](https://github.com/averatec0773), [@he-yufeng](https://github.com/he-yufeng), dan [@Jackzigen](https://github.com/Jackzigen)!

- **2026-09-03** 📡 **Data source yang tidak pernah menjawab, dan angka bertanggal yang tidak dapat dibuktikan**: stooq mengirim halaman JavaScript proof-of-work kepada client non-browser — HTTP 200 dengan body HTML — yang sebelumnya dibaca loader sebagai "tidak ada data", sehingga posisi 2 pada chain US-equity menjadi dead weight pada setiap fetch tanpa jejak apa pun di run log. Sekarang kondisi ini dikenali sebagai unavailable, dengan one-time warning yang menjelaskan cara mengurutkan ulang atau menghapus source tersebut ([#1342](https://github.com/HKUDS/Vibe-Trading/pull/1342), menutup [#1315](https://github.com/HKUDS/Vibe-Trading/issues/1315)). Secara terpisah, generic tool result yang membawa price sekaligus date kehilangan tanggalnya saat masuk ke grounding ledger, sehingga klaim bertanggal tidak memiliki evidence yang dapat dicocokkan dan jawaban yang benar ditolak; sekarang timestamp ikut dibawa, dan tanggal milik row mengoverride tanggal yang diwarisi dari payload ([#1333](https://github.com/HKUDS/Vibe-Trading/pull/1333)). **Diperbaiki:** wrapper MCP untuk goal evidence dan status sebelumnya mewajibkan goal id yang oleh tool terdaftar justru didokumentasikan sebagai optional, sehingga client yang bermaksud "goal saat ini" mendapat validation error ([#1331](https://github.com/HKUDS/Vibe-Trading/pull/1331)); adapter Codex membuang token count yang dilaporkan provider sehingga usage accounting hanya berdasarkan estimasi character count ([#1334](https://github.com/HKUDS/Vibe-Trading/pull/1334)). **Baru:** path MCP stdio milik swarm sekarang memiliki coverage subprocess nyata menggantikan catatan bahwa path tersebut belum diuji ([#1335](https://github.com/HKUDS/Vibe-Trading/pull/1335)). Terima kasih [@he-yufeng](https://github.com/he-yufeng) dan [@Shizoqua](https://github.com/Shizoqua)!

- **2026-09-02** 💵 **Dua loader terakhir yang membukukan dividen sebagai kerugian, dan explicit source yang menjawab sebagai source lain**: FMP dan Tiingo masih menyajikan raw OHLC sementara sisa chain menyajikan adjusted prices — gap ex-dividend yang sama dibaca sebagai penurunan nyata; masalah ini ditutup untuk Yahoo pada 08-31 dan sekarang ditutup untuk keduanya ([#1320](https://github.com/HKUDS/Vibe-Trading/pull/1320), menutup [#1296](https://github.com/HKUDS/Vibe-Trading/issues/1296)). Row mereka pada price-caliber table diperbaiki dalam perubahan yang sama: frame yang adjusted tidak boleh diberi label `raw`, atau mixed-caliber warning yang ditambahkan pada [#1317](https://github.com/HKUDS/Vibe-Trading/pull/1317) hanya memeriksa label, bukan datanya. FMP juga pindah ke Stable endpoint, dan `source="fmp"` eksplisit sekarang gagal dengan jelas alih-alih mengembalikan angka milik source lain atas nama FMP ([#1276](https://github.com/HKUDS/Vibe-Trading/pull/1276), menutup [#1270](https://github.com/HKUDS/Vibe-Trading/issues/1270)). **Diperbaiki:** ticker di dalam full-width parentheses — `公司名（代码）价格` — terpisah dari angkanya sendiri sehingga unsourced-symbol gate tidak pernah melihat keduanya bersamaan ([#1326](https://github.com/HKUDS/Vibe-Trading/pull/1326), menutup [#1260](https://github.com/HKUDS/Vibe-Trading/issues/1260)); setiap link `references/` dalam bundled skills sekarang resolve baik untuk agent maupun manusia yang mengkliknya di GitHub ([#1328](https://github.com/HKUDS/Vibe-Trading/pull/1328)). **Baru:** Português Brasileiro bergabung ke interface sebagai bahasa kedelapan ([#1327](https://github.com/HKUDS/Vibe-Trading/pull/1327)). Terima kasih [@lorenzozanee](https://github.com/lorenzozanee), [@thisisjun786](https://github.com/thisisjun786), [@cgycorey](https://github.com/cgycorey), [@jw232](https://github.com/jw232), [@ethanstoner](https://github.com/ethanstoner), dan [@nandofmike](https://github.com/nandofmike)!

- **2026-09-01** 🎯 **Backtest options yang fill pada harga tempat signal dihitung, dan naked short yang dapat menjual premium yang tidak mungkin ditanggungnya**: signal bertanggal T sebelumnya dihargai dari close dan IV milik T sendiri — phantom edge di setiap options backtest, bukan hanya kasus adversarial. Sekarang signal fill pada bar berikutnya, dan short leg menahan margin bergaya CBOE yang diperiksa terhadap buying power ([#1299](https://github.com/HKUDS/Vibe-Trading/pull/1299), [#1306](https://github.com/HKUDS/Vibe-Trading/pull/1306)). **Diperbaiki:** perpetual funding sebelumnya settle sekali sehari padahal model engine sendiri 3x/hari ([#1307](https://github.com/HKUDS/Vibe-Trading/pull/1307)); short 1x sepenuhnya exempt dari liquidation ([#1298](https://github.com/HKUDS/Vibe-Trading/pull/1298)); composite run kehilangan aturan T+1 India dan fail-open pada setiap price-limit band ([#1309](https://github.com/HKUDS/Vibe-Trading/pull/1309)). **Baru:** setiap frame yang disajikan menyatakan price caliber-nya — adjusted, raw, atau dengan jujur unknown — dan run dengan mixed caliber menyatakannya ([#1317](https://github.com/HKUDS/Vibe-Trading/pull/1317), menutup [#1301](https://github.com/HKUDS/Vibe-Trading/issues/1301)). Terima kasih [@he-yufeng](https://github.com/he-yufeng), [@cgycorey](https://github.com/cgycorey), [@lorenzozanee](https://github.com/lorenzozanee), dan [@guestccc](https://github.com/guestccc)!

- **2026-08-31** 🧮 **Yahoo membukukan setiap dividen sebagai kerugian, dan rebalance count yang ditampilkan tidak berkaitan dengan fill sebenarnya**: kedua path Yahoo menyajikan OHLC yang tidak disesuaikan dividen sementara sisa chain menggunakan adjusted prices, sehingga setiap gap ex-dividend dibaca sebagai penurunan nyata pada US-equity backtest yang dilayani Yahoo. Sekarang OHLC diskalakan ke `adjclose` milik Yahoo dan path yfinance meminta adjusted series; volume tetap raw pada keduanya ([#1287](https://github.com/HKUDS/Vibe-Trading/pull/1287)). Pengukuran chain untuk memverifikasi hal itu menemukan fakta yang perlu dinyatakan jelas: **sina dan longbridge masih menyajikan harga yang sepenuhnya unadjusted**, sehingga source yang akhirnya dipakai masih mengubah price caliber — gap tersebut sekarang dilacak di [#1301](https://github.com/HKUDS/Vibe-Trading/issues/1301). Secara terpisah, `rebalance_count` sebelumnya menghitung *perubahan* target weight, bukan execution: strategi SPY/BND dengan target konstan melaporkan satu rebalance untuk 1.269 trade. Sekarang requested dan executed menjadi metrik terpisah, dengan executed diturunkan dari immutable fill records ([#1281](https://github.com/HKUDS/Vibe-Trading/pull/1281), menutup [#1275](https://github.com/HKUDS/Vibe-Trading/issues/1275)). **Baru:** `rebalance_mask` menjalankan partial rebalancing berdasarkan calendar atau tanggal eksplisit alih-alih setiap bar ([#1277](https://github.com/HKUDS/Vibe-Trading/pull/1277), menutup [#1273](https://github.com/HKUDS/Vibe-Trading/issues/1273)); report HTML alpha-bench sekarang membawa survivorship-bias disclosure yang sebelumnya sudah ada di JSON, menyebut constituent source beserta as-of date-nya ([#1289](https://github.com/HKUDS/Vibe-Trading/pull/1289)). **Diperbaiki:** satu simbol unresolved tidak lagi menahan seluruh batch — chain hanya retry simbol yang hilang dan provenance menyebut source yang benar-benar melayani setiap simbol ([#1288](https://github.com/HKUDS/Vibe-Trading/pull/1288)); halt sweep dapat melatch episode yang sebenarnya tidak pernah disweep, dan dua completion concurrent dapat saling kehilangan record ([#1254](https://github.com/HKUDS/Vibe-Trading/pull/1254)); koneksi Futu OpenD yang berfungsi dirender unavailable karena health report-nya tidak menyertakan `connection_state`; desktop updater membaca process probe dengan permission denied sebagai "backend exited" ([#1284](https://github.com/HKUDS/Vibe-Trading/pull/1284)); dan session yang dibackground di tengah turn mempertahankan sidebar spinner sepanjang umur tab ([#1257](https://github.com/HKUDS/Vibe-Trading/pull/1257), menutup [#1256](https://github.com/HKUDS/Vibe-Trading/issues/1256)). Terima kasih [@he-yufeng](https://github.com/he-yufeng), [@cgycorey](https://github.com/cgycorey), [@thisisjun786](https://github.com/thisisjun786), [@bonyohana](https://github.com/bonyohana), [@lorenzozanee](https://github.com/lorenzozanee), dan [@iagop03](https://github.com/iagop03)!

- **2026-08-30** 🇬🇧 **Equity LSE hadir tanpa mengubah pence menjadi pounds, dan market yang tutup berhenti memicu live trigger**: simbol `.L` sekarang bekerja end-to-end melalui Yahoo → yfinance → local market-data fallback, stock profile dan financial statement, consumer trade-journal dan Shadow, serta backtest dengan settlement GBP. Loader memperlakukan `.L` hanya sebagai venue marker: harga yang dideklarasikan GBp/p dibagi 100, GBP diteruskan tanpa perubahan, sedangkan USD, currency lain, atau unknown ditolak sebelum accounting layer yang secara statis menggunakan GBP. Provenance conversion per simbol bertahan melewati cache round-trip, dan versi cache dinaikkan agar entry lama yang unsafe tidak dapat kembali; execution UK juga menggunakan whole shares dan `slippage_uk` ([#1206](https://github.com/HKUDS/Vibe-Trading/pull/1206), menutup [#1205](https://github.com/HKUDS/Vibe-Trading/issues/1205)). **Diperbaiki:** live tick yang dipicu market berhenti sebelum broker read ketika semua market terkait sedang tutup, sementara channel interval-only dan event-driven tetap tidak digate ([#1253](https://github.com/HKUDS/Vibe-Trading/pull/1253)); Run Detail sekarang scroll dan clamp prompt panjang lalu collapse kembali saat berpindah run ([#1258](https://github.com/HKUDS/Vibe-Trading/pull/1258)); run non-backtest dirutekan ke Studio alih-alih dashboard kosong, dan array trade-artifact kosong tidak lagi menyembunyikan `trade_log` yang sebenarnya berisi data ([#1259](https://github.com/HKUDS/Vibe-Trading/pull/1259)). Terima kasih [@cgycorey](https://github.com/cgycorey), [@he-yufeng](https://github.com/he-yufeng), dan [@iagop03](https://github.com/iagop03)!

- **2026-08-29** 🛑 **Kill switch yang melewati aksinya sendiri, dan crypto pair yang diresolve ke coin berbeda**: ketika broker read pada channel yang halted gagal — adapter mengembalikan error envelope alih-alih raise, lalu sweep mengiterasinya seolah list order — sweep tetap menandai dirinya fired. Cancel-and-flatten yang menjadi tujuan kill switch diam-diam dilewati untuk episode tersebut dan tidak ada yang retry. Sekarang latch hanya aktif setelah broker write benar-benar dicoba, setiap halt episode diklaim secara eksklusif agar dua runner tidak menduplikasi close, dan broker rejection yang dibungkus transport-level success tidak lagi dibaca sebagai accepted ([#1244](https://github.com/HKUDS/Vibe-Trading/pull/1244)). Secara terpisah, request `ETH-USDT` mengembalikan `AETHUSDT-USD` — Aave Ethereum USDT, asset berbeda — karena symbol search belum mencakup exchange pair dan nearest string milik Yahoo menang. Sekarang exact pair diresolve terhadap venue catalog yang bersifat publik dan tidak memerlukan akun broker ([#1242](https://github.com/HKUDS/Vibe-Trading/pull/1242), menutup [#1234](https://github.com/HKUDS/Vibe-Trading/issues/1234)). **Baru:** built-in connector mempublikasikan onboarding contract yang machine-readable, sehingga `vibe-trading connector setup` dan Portfolio connection center menggunakan satu generic flow, dengan secret per connection disimpan di OS keyring ([#1250](https://github.com/HKUDS/Vibe-Trading/pull/1250)). **Diperbaiki:** retry stream sekarang meningkat secara bertahap dan menghormati `Retry-After` ([#1208](https://github.com/HKUDS/Vibe-Trading/issues/1208)); sleeve yang target-nya dibulatkan di bawah satu lot dilaporkan alih-alih diam-diam melakukan nol trade ([#1235](https://github.com/HKUDS/Vibe-Trading/issues/1235)); dan benchmark eksplisit diukur pada evaluation window, bukan fetched window, sehingga warm-up boundary kemarin tidak lagi membandingkan dua periode berbeda. Terima kasih [@cgycorey](https://github.com/cgycorey), [@pengpengyi92](https://github.com/pengpengyi92), [@lorenzozanee](https://github.com/lorenzozanee), [@goatyyc](https://github.com/goatyyc), [@ethanstoner](https://github.com/ethanstoner), [@QG8000](https://github.com/QG8000), dan [@turtle696966969696](https://github.com/turtle696966969696)!

- **2026-08-28** 📏 **Backtest yang crash, dan backtest yang diam-diam menilai satu tahun yang tidak pernah Anda minta**: setiap cross-market backtest mati pada v0.1.14 — runner memang sengaja meneruskan `bars_per_year=None` untuk basket lintas market, lalu risk x-ray baru memanggil `math.sqrt` terhadap nilai itu. Dua consumer lain memiliki gap yang sama; sekarang keempatnya meresolve `None` melalui satu shared span-derived factor ([#1239](https://github.com/HKUDS/Vibe-Trading/pull/1239), menutup [#1237](https://github.com/HKUDS/Vibe-Trading/issues/1237)). Masalah yang lebih senyap: strategi dengan long lookback memerlukan bar dari *sebelum* periode yang diminta, sehingga agent menggeser `start_date` mundur setahun untuk memberi data ke MA200 — lalu ikut menilai tahun tambahan tersebut. Run yang diklaim sepuluh tahun melaporkan sebelas, dengan trade, CAGR, dan benchmark dari tahun ekstra ikut dihitung, tanpa error dan dengan metrik yang tetap terlihat konsisten. `warmup_bars` (atau `evaluation_start_date`) sekarang memisahkan data window dari evaluation window: warm-up bar hanya mempersiapkan indicator dan tidak memengaruhi apa pun selain itu ([#1240](https://github.com/HKUDS/Vibe-Trading/issues/1240)). **Baru:** `quantlib` mendapat pricing stochastic-volatility Heston (1993), Hierarchical Risk Parity, Gaussian dan Archimedean copula, estimator microstructure (VPIN, Roll, Amihud, Kyle), serta finite-difference barrier Greeks — 306 fungsi teruji dalam 23 module ([#1195](https://github.com/HKUDS/Vibe-Trading/pull/1195)–[#1198](https://github.com/HKUDS/Vibe-Trading/pull/1198), [#1203](https://github.com/HKUDS/Vibe-Trading/pull/1203)). **Diperbaiki:** delapan link referensi skill menunjuk ke path yang tidak dapat dibuka `read_file`, sehingga document tersebut diam-diam gagal diload. Terima kasih [@cgycorey](https://github.com/cgycorey), [@santhreal](https://github.com/santhreal), [@turtle696966969696](https://github.com/turtle696966969696), dan [@wanderkiller](https://github.com/wanderkiller)!

- **2026-08-27** 🛑 **Sweep kill switch sekarang bertahan melewati restart dan berhenti mempercayai broker yang tidak stabil**: selama halt, cancel-and-flatten sweep sebelumnya menganggap respons broker apa pun sebagai success — tetapi adapter MCP mengubah call gagal menjadi envelope `{"status": "error"}`, sehingga koneksi yang drop menghasilkan audit trail yang tampak compliant sementara resting order tetap live; sekarang error envelope fail-closed pada kedua pass ([#1232](https://github.com/HKUDS/Vibe-Trading/pull/1232)). Latch fired-once milik sweep juga sebelumnya hanya hidup di memory: restart ketika flatten order masih working memutar ulang seluruh sweep — satu market order baru per position, cukup untuk membalik long book menjadi net short; sekarang latch dipersist di sebelah sentinel HALT dan diikat ke halt episode-nya, sehingga clearing lalu retrigger tetap merearm dengan benar ([#1233](https://github.com/HKUDS/Vibe-Trading/pull/1233)). **Baru:** urutan fallback data source setiap market sekarang terlihat dan dapat diubah di *Settings → Data Source Priority* — diterapkan langsung, dipersist per market (`MARKET_DATA_ORDER_*`), dan benar-benar hanya reordering: menambah atau menghapus source ditolak, dan tanpa override default tidak disentuh ([#1231](https://github.com/HKUDS/Vibe-Trading/pull/1231)); hasil reconciliation Binance USD-M sekarang disimpan sebagai tamper-evident drift evidence artifact — strict JSON, fail-closed pada snapshot incomplete atau unsupported, tanpa order surface ([#1230](https://github.com/HKUDS/Vibe-Trading/pull/1230), menuju [#1030](https://github.com/HKUDS/Vibe-Trading/issues/1030)). Terima kasih [@he-yufeng](https://github.com/he-yufeng), [@sambazhu](https://github.com/sambazhu), dan [@honginp](https://github.com/honginp)!

- **2026-08-26** ♻️ **Live order Alpaca yang kehilangan respons broker tidak lagi menjadi misteri, dan backtest emas berhenti menjadi tanpa friksi**: order gate sekarang secara durable memiliki setiap submission Alpaca sebelum broker write, memulihkan outcome hanya dengan exact `client_order_id`, mengatribusikan fill terhadap signed position delta, dan melakukan HALT pada kontradiksi apa pun — recovery tidak pernah melakukan resubmit ([#1213](https://github.com/HKUDS/Vibe-Trading/pull/1213), [#1221](https://github.com/HKUDS/Vibe-Trading/pull/1221), [#1222](https://github.com/HKUDS/Vibe-Trading/pull/1222)). **Diperbaiki:** metals sebelumnya memakai convention pip/lot FX, membuat spread emas sekitar 1.460× terlalu murah dan membulatkan position di bawah 1.000 oz menjadi nol ([#1226](https://github.com/HKUDS/Vibe-Trading/pull/1226)); holding Futu dalam HKD dinilai sebagai USD sehingga terlalu tinggi kira-kira sebesar kurs USD/HKD ([#1228](https://github.com/HKUDS/Vibe-Trading/pull/1228)); Shadow Account membaca key PnL yang tidak pernah dikeluarkan runner, sehingga setiap backtest sukses melaporkan PnL = 0.00 ([#1217](https://github.com/HKUDS/Vibe-Trading/pull/1217)); streamed LLM call tidak pernah meminta usage sehingga output token swarm terlapor sekitar 18–36× terlalu rendah ([#1225](https://github.com/HKUDS/Vibe-Trading/pull/1225)). **Baru:** snapshot akun Binance USD-M read-only yang opt-in — dua signed read dalam allowlist, tanpa order surface ([#1229](https://github.com/HKUDS/Vibe-Trading/pull/1229), menuju [#1030](https://github.com/HKUDS/Vibe-Trading/issues/1030)); reconnect OAuth portfolio berjalan di bounded subprocess yang tidak dapat membuat web process atau callback port tersangkut ([#1211](https://github.com/HKUDS/Vibe-Trading/pull/1211)). Terima kasih [@Elfsa-Miranda](https://github.com/Elfsa-Miranda), [@P1Piyush](https://github.com/P1Piyush), [@JaxonHu1024](https://github.com/JaxonHu1024), [@he-yufeng](https://github.com/he-yufeng), [@honginp](https://github.com/honginp), dan [@goatyyc](https://github.com/goatyyc)!

- **2026-08-25** 🛡️ **Dua live-gate fail-open ditutup, dan purged CV berhenti menghapus training set di antara test block**: short Alpaca sebelumnya dibukukan sebagai exposure *positif* (`qty` adalah magnitude, direction berada di `side`), sehingga menjual lebih banyak justru melonggarkan `max_total_exposure_usd` alih-alih memperketatnya — quantity sekarang signed pada path TAP JSON maupun direct-SDK ([#1209](https://github.com/HKUDS/Vibe-Trading/pull/1209)); read OKX/Futu sebelumnya meratakan API call yang ditolak menjadi "empty book, `status: ok`", sehingga mandate gate mengevaluasi limit terhadap ketiadaan data — sekarang keduanya mengembalikan error envelope yang membuat gate fail-closed ([#1212](https://github.com/HKUDS/Vibe-Trading/pull/1212)). Keduanya merupakan Phase 0 dari audit roadmap di [#1207](https://github.com/HKUDS/Vibe-Trading/issues/1207). **Diperbaiki:** combinatorial purged CV memperlakukan test block yang tidak contiguous sebagai satu span, sehingga seluruh training observation di antara block ikut dipurge; sekarang segment dipurge secara individual dan fold yang menjadi kosong akan raise ([#1204](https://github.com/HKUDS/Vibe-Trading/pull/1204)); fungsi credit-risk menolak input NaN/inf alih-alih mengembalikan NaN score atau verdict "grey" ([#1215](https://github.com/HKUDS/Vibe-Trading/pull/1215), menutup [#1214](https://github.com/HKUDS/Vibe-Trading/issues/1214)). **Baru:** swarm worker melakukan retry dengan capped equal-jitter backoff ([#1210](https://github.com/HKUDS/Vibe-Trading/pull/1210), menuju [#1208](https://github.com/HKUDS/Vibe-Trading/issues/1208)), dan `vibe-trading --swarm-retry <run_id>` / `/swarm retry` menjalankan ulang run gagal sambil mempertahankan task yang sudah selesai dengan `--resume` ([#1194](https://github.com/HKUDS/Vibe-Trading/pull/1194)). Terima kasih [@he-yufeng](https://github.com/he-yufeng), [@santhreal](https://github.com/santhreal), [@Robin1987China](https://github.com/Robin1987China), [@pengpengyi92](https://github.com/pengpengyi92), dan [@SiMinus](https://github.com/SiMinus)!

- **2026-08-24** 🔗 **MCP resmi IBKR naik dari sekadar "menampilkan tools" menjadi source portfolio read-only yang bekerja, dan scheduling mendapat agent tool yang tidak dapat bertindak sendirian**: [#1178](https://github.com/HKUDS/Vibe-Trading/pull/1178) memperbaiki URL, tetapi gateway IBKR masih menolak stock OAuth client registration milik FastMCP sebelum login. OAuth provider khusus IBKR — browser-profile headers, `token_endpoint_auth_method: none`, callback port stabil, dan recovery untuk stale registration, diterapkan hanya ketika host MCP adalah `api.ibkr.com` — sekarang menyelesaikan authorization ([#1186](https://github.com/HKUDS/Vibe-Trading/pull/1186)), dan tool `get_account_summary` / `get_account_positions` yang sudah diverifikasi dengan live account sekarang menjadi backend generic account/position read, membuat `ibkr-live-official-mcp-readonly` eligible sebagai source `/portfolio` ([#1190](https://github.com/HKUDS/Vibe-Trading/pull/1190), menutup [#1126](https://github.com/HKUDS/Vibe-Trading/issues/1126)). **Baru:** agent melihat tepat satu scheduling tool, `scheduled_research` — `propose_create`/`propose_cancel` miliknya tidak pernah menyentuh job store sampai Anda mengonfirmasi pada surface yang sedang digunakan (Web card, CLI `y/N`, atau reply exact `confirm`/`确认` di IM), delivery target adalah opaque ref yang dikonfigurasi operator dan tidak pernah mengekspos raw chat/user id, serta job yang sudah melewati `end_at` expired alih-alih fire lagi ([#1187](https://github.com/HKUDS/Vibe-Trading/pull/1187)). **Diperbaiki:** engine comps dan three-statement sekarang menolak non-finite input di setiap titik masuk arithmetic — peer metric NaN sebelumnya *ikut dimasukkan* ke multiple distribution dan menyeret median menjadi NaN, sedangkan `abs(nan) > tolerance` bernilai `False`, sehingga balance sheet NaN lolos hard balance check ([#1184](https://github.com/HKUDS/Vibe-Trading/pull/1184), menutup [#1183](https://github.com/HKUDS/Vibe-Trading/issues/1183)); `get_market_data` memvalidasi code, date, source, dan interval sebelum menghabiskan loader fallback chain untuk call malformed, dan source enum-nya berhenti diam-diam menolak enam loader yang sebenarnya terdaftar ([#1185](https://github.com/HKUDS/Vibe-Trading/pull/1185)); Feishu QR login sekarang mempersist app credential yang diterima tepat sekali — secara atomic dan owner-only — alih-alih melaporkan success yang hilang setelah process berakhir ([#1188](https://github.com/HKUDS/Vibe-Trading/pull/1188)); historical-VaR order statistic pada document risk-analysis skill sekarang sesuai dengan code ([#1189](https://github.com/HKUDS/Vibe-Trading/pull/1189)). Terima kasih [@sykuang](https://github.com/sykuang), [@goatyyc](https://github.com/goatyyc), [@AirHua-byte](https://github.com/AirHua-byte), [@Robin1987China](https://github.com/Robin1987China), [@cgycorey](https://github.com/cgycorey), dan [@youngjincho02-arch](https://github.com/youngjincho02-arch)!

- **2026-08-23** 🔌 **Seed MCP IBKR memakai URL yang salah, dan menutup satu LLM adapter menutup semuanya**: profile MCP resmi IBKR read-only yang diseed, README, dan `SKILL.md` semuanya menunjuk ke `https://api.ibkr.com/v1/api/mcp`; halaman AI integration resmi IBKR mempublikasikan `https://api.ibkr.com/v1/api/mcp-public`, dan sekarang seed, keenam README, serta `SKILL.md` memakai URL tersebut — jalankan ulang `vibe-trading connector configure ibkr-live-official-mcp-readonly --yes` jika `agent.json` Anda masih berisi URL lama. Langkah OAuth client-registration yang ditolak gateway IBKR masih terbuka di [#1126](https://github.com/HKUDS/Vibe-Trading/issues/1126) ([#1178](https://github.com/HKUDS/Vibe-Trading/pull/1178)). **Diperbaiki:** `ChatLLM.close()` sebelumnya menutup cached HTTPX client process-wide milik LangChain, sehingga satu title-generation atau image-vision call yang selesai membuat semua request berikutnya gagal dengan "client has been closed" sampai restart — sekarang hanya transport yang dibuat sendiri oleh Vibe-Trading yang ditutup ([#1182](https://github.com/HKUDS/Vibe-Trading/pull/1182)); service restart di tengah reply membuang streamed text dan membiarkan attempt berstatus *running* selamanya — partial reply sekarang dicheckpoint dan pada start berikutnya direkonsiliasi sebagai transcript entry *interrupted* yang eksplisit ([#1180](https://github.com/HKUDS/Vibe-Trading/pull/1180)). **Baru:** Web chat dapat melampirkan hingga lima file per turn melalui file picker, drag-and-drop, atau clipboard paste ([#1179](https://github.com/HKUDS/Vibe-Trading/pull/1179)). Terima kasih [@c020627](https://github.com/c020627) dan [@AirHua-byte](https://github.com/AirHua-byte)!

- **2026-08-22** 💼 **Halaman Portfolio — holdings Anda dari berbagai broker, read-only**: pilih profile connector read-only mana pun (instance connection di atas `account.read` + `positions.read`; profile official-MCP IBKR belum eligible) dan halaman `/portfolio` baru akan mengagregasikannya menjadi immutable snapshot dengan provenance per source, valuasi USD/CNY, export CSV, dan history chart. Source yang gagal refresh dilaporkan sebagai **error dan dikeluarkan dari total** — tidak pernah dibawa maju — dan snapshot ditandai incomplete. Agent tool `portfolio_summary` mengembalikan `risk_xray_args` untuk memberi input ke `portfolio_risk_xray` yang sudah ada, dan `vibe-trading portfolio show|refresh|sources` mencetak snapshot yang sama di terminal. Plugin connector read-only buatan Anda sendiri ditempatkan di `~/.vibe-trading/connectors/` (manifest yang mendeklarasikan write capability apa pun ditolak; secret masuk ke OS keyring melalui extra `[keyring]`), dan tidak ada path ini yang dapat menempatkan order ([#1072](https://github.com/HKUDS/Vibe-Trading/pull/1072), menuju [#1171](https://github.com/HKUDS/Vibe-Trading/issues/1171)). **Diperbaiki:** tiga belas factor Alpha Zoo sebelumnya melakukan forward-fill pada close yang hilang sebelum menghitung return, mengubah data gap menjadi "return 0%" yang finite — sekarang gap tetap `NaN` ([#1172](https://github.com/HKUDS/Vibe-Trading/pull/1172)); MCP client independen pada satu server http/sse berbagi satu fallback research-goal session ([#1173](https://github.com/HKUDS/Vibe-Trading/pull/1173)); memory GC dan compression meninggalkan stale FTS row dan relation sidecar orphan ([#1174](https://github.com/HKUDS/Vibe-Trading/pull/1174)); `cancel_run()` tidak pernah mencapai swarm worker yang sudah streaming — sekarang stop menginterupsi stream, melewati tool call pada turn itu, dan task berakhir sebagai *cancelled* ([#1175](https://github.com/HKUDS/Vibe-Trading/pull/1175)); MCP `get_research_reports` membuang `beginTime`/`endTime` ([#1176](https://github.com/HKUDS/Vibe-Trading/pull/1176)); `get_options_chain` menjawab expiration dari cycle yang salah dengan `ok: true` dan contract dari tanggal lain ([#1177](https://github.com/HKUDS/Vibe-Trading/pull/1177)). Terima kasih [@goatyyc](https://github.com/goatyyc), [@Shizoqua](https://github.com/Shizoqua), dan [@cgycorey](https://github.com/cgycorey)!

- **2026-08-21** ⏱️ **Run yang hang selamanya**: timeout `bash` membunuh shell tetapi tidak grandchildren yang masih memegang pipe handle, sehingga run tetap "running" selama 20+ menit. Command sekarang spawn di process group sendiri, timeout membunuh seluruh process tree, stall watchdog mengakhiri run yang tidak membuat forward progress, dan compaction berhenti membuang verification record milik model sendiri ([#1169](https://github.com/HKUDS/Vibe-Trading/pull/1169)). **Diperbaiki:** multi-year history Tencent diam-diam terpotong pada 500 bar ([#1154](https://github.com/HKUDS/Vibe-Trading/pull/1154)). **Baru:** swarm run hanya mereplay failed subgraph ([#1158](https://github.com/HKUDS/Vibe-Trading/pull/1158), menutup [#1157](https://github.com/HKUDS/Vibe-Trading/issues/1157)); Market Watch menampilkan verdict terbaru setiap monitor secara inline ([#1156](https://github.com/HKUDS/Vibe-Trading/pull/1156), menutup [#943](https://github.com/HKUDS/Vibe-Trading/issues/943)); `quantlib` mencapai 286 fungsi teruji ([#1159](https://github.com/HKUDS/Vibe-Trading/pull/1159)–[#1168](https://github.com/HKUDS/Vibe-Trading/pull/1168)). Terima kasih [@wiliao](https://github.com/wiliao), [@cgycorey](https://github.com/cgycorey), [@he-yufeng](https://github.com/he-yufeng), [@BigFishEmily](https://github.com/BigFishEmily), [@santhreal](https://github.com/santhreal), [@SiMinus](https://github.com/SiMinus), dan [@alinv0](https://github.com/alinv0)!

- **2026-08-20** 🚀 **v0.1.14 dirilis** ([Catatan rilis](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.14), `pip install -U vibe-trading-ai`): 272 commit dan 74 pull request digabungkan sejak 0.1.13. **Headline-nya: backtest yang selesai sekarang menjadi sesuatu yang bisa Anda baca, bukan sekadar folder CSV.** Run Detail mendapat empat tab — **Factor Research** (series IC dengan mean line, statistik IC, equity quantile-group, dan pairwise IC correlation matrix yang sebelumnya tidak tersedia di mana pun), **Positions** (weight pie/treemap pada date slider, sector net-exposure bar, area evolusi weight — pie menunjukkan gross composition sedangkan bar menunjukkan net, sehingga pair long/short pada sector yang sama menjadi nol pada bar tetapi kedua leg tetap terlihat pada pie), **Tearsheet** (heatmap monthly return, annual bar, top-5 drawdown yang dianotasi pada equity curve), serta **research dashboard** interaktif dengan KPI, benchmark-relative equity, rolling Sharpe, dan full trade ledger. Keempatnya membaca artifact yang memang sudah ditulis oleh run — tanpa pipeline baru. Halaman **Options Lab** baru menambahkan expiry payoff diagram, matrix scenario spot×IV, portfolio Greeks, dan live options chain, semuanya dihitung melalui engine test-pinned yang sama dengan MCP tools. **Install:** Intel Mac sekarang dapat `pip install vibe-trading-ai` lagi — `smartmoneyconcepts` menarik `llvmlite`, yang sejak 0.46 tidak menyediakan wheel macOS x86_64, sehingga setiap install Intel berubah menjadi CMake source build; dependency itu sekarang menjadi extra `[smc]` opt-in dan cap `<3.14` yang stale dihapus ([#1035](https://github.com/HKUDS/Vibe-Trading/discussions/1035)). **Baru:** **Strategy Discovery** berbasis evidence gate di Alpha Zoo dan SDM store, dengan population path, freshness saat read (`fresh`/`aging`/`stale`), dan stale row fail-closed keluar dari recommendation; scheduled research yang **mengirimkan hasilnya sendiri** melalui leased outbox dan mempersist verdict setiap monitor untuk daftar Market Watch; tujuh endpoint **Futu** read-only; **Vietnam (HOSE)** sebagai market backtest; offline **USD-M account reconciliation**; provider **Novita AI** dan **GitHub Copilot**; hosted data source **MetaTrader 5**; locale **Spanyol** dan **Jerman**; serta MCP tumbuh menjadi 74 tool. **Correctness:** test suite berhenti keluar ke config root nyata Anda, tempat full run sebelumnya menambahkan record `order_rejected` sintetis ke live hash-chained audit ledger; `build_registry()` tidak lagi diam-diam mengembalikan tool list yang lebih pendek; `xirr` bertahan dari discount underflow pada horizon panjang dan DCF menolak non-finite input alih-alih mengembalikan negative share price; simbol `.VN` berhenti dieksekusi dengan aturan China A-share; archive backtest berhenti mencampur artifact dua run; dan broad grounding pass mengakhiri satu kelas false refusal pada tanggal, ordered list, identity constant dalam rate formula, serta order line yang dibaca sebagai quote. Terima kasih @Shizoqua, @shadowinlife, @pengpengyi92, @cgycorey, @ofeksh-tr, @lorenzozanee, @AndyLongest, @zzz607, @wiliao, @jay79-boop, @Robin1987China, @Echoandelementwebsites, @zhiwuyazhe-fjr, @x-lambda, @sykuang, @straun-repo, @nstavros, @ngoanpv, @miguelangelo78, @lukiod, @jax-novita, @honginp, @he-yufeng, @fixXxerTech, @er-s-an, @daviddaco1, @birdxs, @QCYTSN, @549236606-oss, dan @1psconstructor.

- **2026-08-19** 🔌 **Run yang stalled, connection leak per task, dan Intel Mac yang tidak dapat install**: provider yang diam sebelumnya dapat membuat run freeze — `VIBE_TRADING_LLM_TIMEOUT_SECONDS` (default 300s) sekarang membatasi call, dan markup tool-call tidak pernah dirilis sebagai final answer ([#1105](https://github.com/HKUDS/Vibe-Trading/pull/1105)). Setiap swarm task sebelumnya membocorkan satu pooled HTTP connection ([#1145](https://github.com/HKUDS/Vibe-Trading/pull/1145), menutup [#1141](https://github.com/HKUDS/Vibe-Trading/issues/1141)). Juga diperbaiki: `vibe-trading show <run_id>` yang crash ([#1147](https://github.com/HKUDS/Vibe-Trading/pull/1147), menutup [#1146](https://github.com/HKUDS/Vibe-Trading/issues/1146)), in-flight delivery yang tertimpa ([#1140](https://github.com/HKUDS/Vibe-Trading/pull/1140)), backtest validation evidence yang hilang ([#1139](https://github.com/HKUDS/Vibe-Trading/pull/1139)), paging MCP ([#1137](https://github.com/HKUDS/Vibe-Trading/pull/1137), [#1138](https://github.com/HKUDS/Vibe-Trading/pull/1138)), dan field prediction-market non-finite ([#1136](https://github.com/HKUDS/Vibe-Trading/pull/1136)). **Baru:** tujuh endpoint Futu read-only ([#1135](https://github.com/HKUDS/Vibe-Trading/pull/1135)) dan chip `Inferred` eksplisit pada judul strategy hasil tebakan ([#1134](https://github.com/HKUDS/Vibe-Trading/pull/1134)). **Install:** `smartmoneyconcepts` sekarang menjadi extra `[smc]` — `llvmlite` yang ditariknya tidak menyediakan wheel macOS x86_64, membuat setiap install Intel Mac berubah menjadi cmake source build ([#1035](https://github.com/HKUDS/Vibe-Trading/discussions/1035)); cap `<3.14` ikut dihapus. Terima kasih [@wiliao](https://github.com/wiliao), [@cgycorey](https://github.com/cgycorey), [@Shizoqua](https://github.com/Shizoqua), [@Echoandelementwebsites](https://github.com/Echoandelementwebsites), [@549236606-oss](https://github.com/549236606-oss), dan [@fixXxerTech](https://github.com/fixXxerTech)!

- **2026-08-18** 🈶 **Report yang benar berhenti ditolak, dan backtest berhenti trading noise**: `\b` bersifat Unicode-aware, sehingga `最` dihitung sebagai word character dan `(2026-07-14最低)` tidak memiliki boundary setelah tanggal — date lolos dari mask dan `2026`, `7`, serta `14` sampai ke OHLC check sebagai price yang tidak mungkin berada di observed range ([#1132](https://github.com/HKUDS/Vibe-Trading/pull/1132), menutup [#1122](https://github.com/HKUDS/Vibe-Trading/issues/1122)). Empat refusal dari keluarga yang sama ikut hilang: trading day berbentuk dash (`08-10(一)`), level yang dinyatakan sebagai range tetapi menyisakan `-20`, baris GTC (`100 @ $3.50`) yang dibaca sebagai dua observed quote, dan date cell bergaya report yang tidak cocok dengan evidence row mana pun. **Backtest:** `position_adjustment="hold"` sebelumnya diam-diam membuang request resize, sedangkan `"rebalance"` tidak memiliki drift band — saat diukur, pergerakan harian 0.01% merepin position pada 19 dari 30 bar, sehingga strategi dengan `rebalance_freq` sendiri tetap trade setiap bar. Request yang dibuang sekarang dilaporkan, dan `rebalance_tolerance` menjadi band yang dimaksud praktisi ketika berkata "rebalance jika weight bergerak lebih dari X", dengan default `0.0` agar tidak mengubah run yang sudah ada. Sembilan belas alpha101 yang dineutralisasi menurut industry sebelumnya selalu diskip pada setiap SP500 bench run karena sector tag dianggap tidak ada, padahal tag tersebut sudah tersedia di table asal constituent. **Baru:** monitor Market Watch dapat mengirim briefing ke IM channel setelah run selesai melalui persisted outbox yang tidak hilang karena restart dan tidak dapat double-send oleh concurrent sweep ([#942](https://github.com/HKUDS/Vibe-Trading/issues/942)); **Jerman menjadi bahasa UI ketujuh** ([#1117](https://github.com/HKUDS/Vibe-Trading/pull/1117)); `run_dcf` menolak non-finite input alih-alih mengembalikan negative share price yang tampak plausible ([#1121](https://github.com/HKUDS/Vibe-Trading/pull/1121), menutup [#1120](https://github.com/HKUDS/Vibe-Trading/issues/1120)); response MCP `get_market_data` membawa `_provenance` yang dijanjikan docstring-nya sendiri ([#1131](https://github.com/HKUDS/Vibe-Trading/pull/1131)); tool module yang gagal import sekarang disebut namanya alih-alih diam-diam mengecilkan registry ([#1129](https://github.com/HKUDS/Vibe-Trading/pull/1129), menutup [#1124](https://github.com/HKUDS/Vibe-Trading/issues/1124)); dan offline USD-M account reconciliation membandingkan local risk state dengan exchange observation tanpa membuka koneksi ([#1106](https://github.com/HKUDS/Vibe-Trading/pull/1106)). **Juga:** mengimport `backtest.runner` tidak lagi memuat `.env` ke process, yang sebelumnya membuat local full-suite run tidak dapat dipercaya pada mesin mana pun yang memiliki file tersebut ([#1123](https://github.com/HKUDS/Vibe-Trading/issues/1123)). Terima kasih [@Robin1987China](https://github.com/Robin1987China), [@newgo](https://github.com/newgo), [@er-s-an](https://github.com/er-s-an), [@Shizoqua](https://github.com/Shizoqua), [@1psconstructor](https://github.com/1psconstructor), [@honginp](https://github.com/honginp), [@cgycorey](https://github.com/cgycorey), [@alinv0](https://github.com/alinv0), dan [@jelech](https://github.com/jelech)!

- **2026-08-17** 🔒 **Test suite berhenti menulis ke config root nyata Anda — termasuk live audit ledger**: menjalankan suite milik project sendiri sebelumnya menambahkan record `order_rejected` palsu ke `~/.vibe-trading/live/audit.jsonl`, sebuah append-only hash-chained ledger yang nilai utamanya justru bahwa entry tidak dapat dibuat-buat, dan pada Windows meninggalkan chain file yang corrupt. `conftest.py` sama sekali tidak memiliki sandbox config-root, sehingga setiap module yang membakukan `Path.home() / ".vibe-trading"` pada import time resolve terhadap home nyata di **platform apa pun** — Windows hanya lebih buruk karena `Path.home()` membaca `%USERPROFILE%` dan mengabaikan `$HOME`, membuat isolation idiom yang dipakai suite tidak berfungsi. Sekarang home diredirect sebelum collection, sandbox memiliki satu knob sehingga per-test isolation tetap menang, dan pada session end byte dari ledger nyata diassert identik alih-alih hanya memeriksa bahwa redirect terpasang ([#1118](https://github.com/HKUDS/Vibe-Trading/pull/1118), menutup [#1116](https://github.com/HKUDS/Vibe-Trading/issues/1116)). Juga: `xirr` dan `money_weighted_return` sebelumnya raise `ZeroDivisionError` pada horizon lebih dari sekitar 51 tahun ketika discount factor underflow menjadi nol — justru long irregular stream yang menjadi alasan XIRR digunakan ([#1119](https://github.com/HKUDS/Vibe-Trading/pull/1119)); dan backtest yang diarchive ke active run bercampur dengan artifact run sebelumnya, sehingga satu report dapat mendeskripsikan dua backtest berbeda sementara `/runs/{id}` menampilkan leftover tersebut sebagai miliknya ([#1094](https://github.com/HKUDS/Vibe-Trading/issues/1094)). Terima kasih [@lorenzozanee](https://github.com/lorenzozanee), [@straun-repo](https://github.com/straun-repo), dan [@pengpengyi92](https://github.com/pengpengyi92)!

- **2026-08-16** 🔧 **Run Anthropic tidak lagi mati saat recovery, dan symbol search berhenti melaporkan hasil kosong sebagai sehat**: recovery path sebelumnya menyisipkan message `system` di tengah conversation yang ditolak Anthropic API, sehingga run mati — recovery steering sekarang dikirim sebagai user message dengan inline tag `<system>` ([#1112](https://github.com/HKUDS/Vibe-Trading/pull/1112), menutup [#1109](https://github.com/HKUDS/Vibe-Trading/issues/1109)). `search_symbol` mengembalikan nol candidate sementara kedua source melaporkan `ok` untuk query ticker+name, sehingga identity tidak pernah lock dan setiap data tool menolak; sekarang path Yahoo melaporkan query seperti itu sebagai `skipped`, bukan `ok` yang menyesatkan ([#1114](https://github.com/HKUDS/Vibe-Trading/pull/1114), menutup [#1108](https://github.com/HKUDS/Vibe-Trading/issues/1108)). Juga: `LANGCHAIN_REASONING_EFFORT` sekarang dihormati pada branch Anthropic melalui model allowlist ([#1115](https://github.com/HKUDS/Vibe-Trading/pull/1115)); loader Tencent recovery dari `CERTIFICATE_VERIFY_FAILED` melalui certifi CA bundle ([#1113](https://github.com/HKUDS/Vibe-Trading/pull/1113)); fallback gross-profit `revenue - cogs` tidak lagi menjadi dead code ([#1111](https://github.com/HKUDS/Vibe-Trading/pull/1111)); dan swarm worker memakai shared truncation helper sehingga sub-agent selalu melihat cut notice ([#1110](https://github.com/HKUDS/Vibe-Trading/pull/1110)). Terima kasih [@lorenzozanee](https://github.com/lorenzozanee), [@straun-repo](https://github.com/straun-repo), [@x-lambda](https://github.com/x-lambda), [@cgycorey](https://github.com/cgycorey), dan [@Shizoqua](https://github.com/Shizoqua)!

- **2026-08-15** 🛡️ **Update desktop yang lebih aman, packaging Windows yang andal, dan factor research di Run Detail**: boundary updater yang dormant sekarang mempertahankan owned-process evidence untuk retry cleanup, memprobe TCP listener alih-alih HTTP health, mereserve recovery journal secara atomic, mengikat Authenticode dan hash ke staged bytes yang sama, lalu memeriksa ulang tepat sebelum launch ([#1101](https://github.com/HKUDS/Vibe-Trading/pull/1101)). Packaging Windows sekarang memiliki bounded checksum-verified Electron download sendiri dan mengekstrak pinned GTK asset sebagai data melalui 7-Zip alih-alih mengeksekusi legacy installer yang flaky; native Windows CI mencakup exit code, timeout, runtime assembly, NSIS, dan packaged startup ([#1104](https://github.com/HKUDS/Vibe-Trading/pull/1104), menutup [#1093](https://github.com/HKUDS/Vibe-Trading/issues/1093)). Run Detail mendapat IC series dan statistics, quantile equity, serta IC correlation dengan bounded artifact traversal dan finite JSON payload ([#1099](https://github.com/HKUDS/Vibe-Trading/pull/1099), menutup [#1100](https://github.com/HKUDS/Vibe-Trading/issues/1100)); universal hash lock diverifikasi secara native di Linux, macOS ARM64, dan Windows ([#1102](https://github.com/HKUDS/Vibe-Trading/pull/1102), menutup [#1089](https://github.com/HKUDS/Vibe-Trading/issues/1089)). Terima kasih [@QCYTSN](https://github.com/QCYTSN) dan [@shadowinlife](https://github.com/shadowinlife)!

- **2026-08-14** ⚙️ **Setting reasoning yang tidak melakukan apa-apa, dan run yang berhenti padahal masih dapat recovery**: `LANGCHAIN_REASONING_EFFORT` sebelumnya diam-diam menjadi no-op untuk hampir semua provider — hanya direct OpenAI yang pernah menerimanya, sehingga setting `high` pada DeepSeek tidak mengubah apa pun dan tidak ada pemberitahuan. Sekarang effort mencapai kedua transport melalui field milik masing-masing adapter: Chat Completions secara default, atau Responses API ketika `LANGCHAIN_USE_RESPONSES_API=true`. Provider yang menerima top-level `reasoning_effort` memakai allowlist yang sudah diverifikasi, bukan setiap endpoint yang berbicara OpenAI wire format — endpoint yang strict dalam memvalidasi request body akan menolak unknown key dan menggagalkan call, sehingga biaya salah menebak adalah semua request gagal, bukan sekadar setting hilang ([#1025](https://github.com/HKUDS/Vibe-Trading/pull/1025)). Grounding gate juga berhenti mengembalikan "confirm and continue" selama deterministic read-only recovery masih tersedia: instrumen unresolved sekarang memicu `search_symbol` → `get_market_data` dengan bounded budget-nya sendiri alih-alih menghabiskan iteration run lalu fail-closed ([#1092](https://github.com/HKUDS/Vibe-Trading/pull/1092), menutup [#1081](https://github.com/HKUDS/Vibe-Trading/issues/1081)). **Baru:** halaman **Options Lab** — multi-leg payoff diagram, spot × IV scenario matrix, portfolio Greeks, dan live chain, dihitung oleh payoff tool dan `quantlib` yang sudah ada alih-alih implementasi matematika kedua ([#1096](https://github.com/HKUDS/Vibe-Trading/pull/1096)); tab **backtest tearsheet** dengan monthly-returns heatmap, annual return, dan top-N drawdown episode ([#1091](https://github.com/HKUDS/Vibe-Trading/pull/1091)); **tickerall** sebagai market-data source ke-25 — bar forex/metals MetaTrader 5 hosted tanpa terminal lokal di OS apa pun, explicit-only agar broker key tidak pernah menjadi silent fallback target, dan truncated history window menjadi error alih-alih series pendek tanpa warning ([#968](https://github.com/HKUDS/Vibe-Trading/pull/968), menutup [#897](https://github.com/HKUDS/Vibe-Trading/issues/897)); serta **Novita AI** dan **GitHub Copilot** sebagai built-in provider ([#1059](https://github.com/HKUDS/Vibe-Trading/pull/1059), [#990](https://github.com/HKUDS/Vibe-Trading/pull/990)). eToro mendapat browsing asset-class berdasarkan instrument type, dan copy trading sekarang menolak demo account dengan alasan yang dinyatakan jelas alih-alih gagal secara obscure ([#1070](https://github.com/HKUDS/Vibe-Trading/pull/1070)). Terima kasih [@cgycorey](https://github.com/cgycorey), [@Shizoqua](https://github.com/Shizoqua), [@shadowinlife](https://github.com/shadowinlife), [@miguelangelo78](https://github.com/miguelangelo78), [@jax-novita](https://github.com/jax-novita), [@sykuang](https://github.com/sykuang), dan [@ofeksh-tr](https://github.com/ofeksh-tr).

- **2026-08-13** 🎯 **Report backtest menampilkan book yang benar-benar fill**: `positions.csv` sebelumnya berisi *target* weight dari optimiser, sehingga report dapat mengklaim exposure 80% sementara lot rounding, fee, atau blocked order membuat portfolio sebenarnya mendekati 20% — target tersebut juga memberi input ke invested-weight metric dan risk x-ray. Sekarang fill masuk ke `positions.csv`, sedangkan request masuk ke `target_positions.csv` ([#1082](https://github.com/HKUDS/Vibe-Trading/pull/1082)). Run Detail mendapat **research dashboard** di `?view=dashboard` ([#1084](https://github.com/HKUDS/Vibe-Trading/pull/1084)), dan **Spanyol menjadi bahasa UI keenam** ([#1087](https://github.com/HKUDS/Vibe-Trading/pull/1087)). Juga: `get_research_reports` sebelumnya mengembalikan HTTP 400 untuk setiap simbol A-share ([#1077](https://github.com/HKUDS/Vibe-Trading/pull/1077)); quote IBKR memisahkan tier yang diminta dari tier yang benar-benar diterapkan ([#1075](https://github.com/HKUDS/Vibe-Trading/pull/1075)); `.env.partial` sekarang ditulis secara atomic ([#1086](https://github.com/HKUDS/Vibe-Trading/pull/1086)); workflow Docker mempin action ke commit dan hash-lock channel SDK ([#1088](https://github.com/HKUDS/Vibe-Trading/pull/1088)); serta grounding gate berhenti membaca ladder support/resistance dan all-time high sebagai observed price ([#1060](https://github.com/HKUDS/Vibe-Trading/pull/1060)). Terima kasih [@AndyLongest](https://github.com/AndyLongest), [@daviddaco1](https://github.com/daviddaco1), [@zzz607](https://github.com/zzz607), [@jay79-boop](https://github.com/jay79-boop), [@lukiod](https://github.com/lukiod), [@birdxs](https://github.com/birdxs), dan [@wiliao](https://github.com/wiliao).

- **2026-08-12** 📏 **Volume A-share tidak lagi melonjak 100× ketika fallback source berubah**: lima source dalam fallback chain A-share melaporkan board lot sedangkan BaoStock melaporkan shares, dan karena serving provenance tidak membawa unit, fallback dapat diam-diam mengubah skala setiap signal berbasis volume. Sekarang loader mendeklarasikan volume unit per market, provenance mengekspos unit milik source yang benar-benar melayani setiap simbol, BaoStock mengonversi shares menjadi board lot pada boundary loader, cache v4 mencegah entry pra-fix muncul lagi, dan live-data cross-source regression mengharuskan nilai pada settled day sepakat dalam 1% ([#1065](https://github.com/HKUDS/Vibe-Trading/pull/1065), [#1067](https://github.com/HKUDS/Vibe-Trading/pull/1067), menutup [#1062](https://github.com/HKUDS/Vibe-Trading/issues/1062)). Correctness pass sepuluh PR juga memberi eToro runtime status lengkap dan UI SDK-connected lima locale ([#1051](https://github.com/HKUDS/Vibe-Trading/pull/1051)); membuat DELETE scheduled-run mengembalikan 204 yang benar-benar kosong ([#1068](https://github.com/HKUDS/Vibe-Trading/pull/1068)); merender payload account direct-SDK Alpaca di CLI ([#1073](https://github.com/HKUDS/Vibe-Trading/pull/1073)); menormalisasi root Ollama ke `/v1` pada credential boundary yang dipakai model constructor nyata ([#1074](https://github.com/HKUDS/Vibe-Trading/pull/1074)); mengubah stdin EOF Docker Codex OAuth menjadi guidance TTY yang actionable ([#1054](https://github.com/HKUDS/Vibe-Trading/pull/1054), menutup [#1050](https://github.com/HKUDS/Vibe-Trading/issues/1050)); menghentikan ordered-list marker Markdown seperti `1.` agar tidak dibaca sebagai unsupported numeric claim ([#1063](https://github.com/HKUDS/Vibe-Trading/pull/1063)); membuat memory query dua karakter seperti `GE` berperilaku sama dengan atau tanpa FTS5 ([#1071](https://github.com/HKUDS/Vibe-Trading/pull/1071)); dan menghargai European option dengan zero volatility dari discounted forward intrinsic value, memulihkan exercise-side logic serta put-call parity ([#1066](https://github.com/HKUDS/Vibe-Trading/pull/1066)). Terima kasih [@shadowinlife](https://github.com/shadowinlife), [@ofeksh-tr](https://github.com/ofeksh-tr), [@zhiwuyazhe-fjr](https://github.com/zhiwuyazhe-fjr), [@zzz607](https://github.com/zzz607), [@pengpengyi92](https://github.com/pengpengyi92), dan [@Shizoqua](https://github.com/Shizoqua).

- **2026-08-11** 🧠 **Compaction berhenti membuang content conversation, dan swarm retry tidak lagi dapat menghapus run-nya sendiri**: auto-compaction sebelumnya memotong serialized history pada batas keras 80.000 karakter sebelum summarizing, sehingga apa pun setelah potongan itu tidak masuk ke summary call maupun preserved tail — hilang tanpa error, bertentangan dengan guarantee "zero info decay" milik fungsi itu sendiri, dan potongan dapat jatuh di tengah object sehingga summarizer menerima JSON invalid. Sekarang history dipack pada boundary message dan dilipat chunk demi chunk melalui iterative template yang sudah ada; satu message yang terlalu besar untuk satu chunk menjadi fragment berlabel alih-alih truncation, dan empty model reply tidak lagi menghapus summary yang sudah terkumpul (menutup [#1055](https://github.com/HKUDS/Vibe-Trading/issues/1055)). Artifact cleanup saat retry yang baru sebelumnya menjalankan `shutil.rmtree` pada `run_dir/artifacts/<agent_id>`, sementara `agent_id` datang tanpa validation dari preset dan user preset dimuat dari `~/.vibe-trading/swarm/presets/`, sehingga id `..` resolve ke directory run itu sendiri — sekarang path ditolak kecuali berupa satu safe segment yang resolve di dalam artifacts directory milik run tersebut. Ditambah `technical_indicators` RSI yang sekarang memakai convention Wilder-EWM sesuai klaim docstring-nya sendiri, karena plain rolling mean dapat menggeser reading melewati boundary 30/70 ([#1056](https://github.com/HKUDS/Vibe-Trading/pull/1056)); `excess_return` dihitung ulang dari benchmark total yang sudah dikoreksi agar kedua field tidak lagi saling bertentangan dalam satu metrics dict ([#1058](https://github.com/HKUDS/Vibe-Trading/pull/1058)); swarm deliverable validation menolak raw tool envelope berkey `ok`/`success` yang disamarkan sebagai analysis ([#1052](https://github.com/HKUDS/Vibe-Trading/pull/1052)); worker yang diretry tidak lagi mewarisi `report.md` dari attempt gagal ([#1053](https://github.com/HKUDS/Vibe-Trading/pull/1053)); dan worker prompt diurutkan agar block agent-invariant membentuk satu prefix yang eligible untuk cache ([#1057](https://github.com/HKUDS/Vibe-Trading/pull/1057)). Terima kasih [@Shizoqua](https://github.com/Shizoqua) dan [@Echoandelementwebsites](https://github.com/Echoandelementwebsites).

- **2026-08-10** 🚀 **v0.1.13 dirilis** ([Catatan rilis](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.13), `pip install -U vibe-trading-ai`): 408 commit dan 162 pull request digabungkan sejak 0.1.12 — release terbesar sejauh ini. **Headline-nya adalah fix, bukan fitur: identity gate berhenti menolak jawaban yang sebenarnya sudah memiliki evidence.** Pertanyaan yang well-formed sebelumnya dapat menghabiskan beberapa menit pada tool call nyata lalu tetap mengembalikan *"cannot safely confirm instrument identity or price evidence"*. Penyebabnya: `.SS` dan `.SH` diperlakukan sebagai instrumen berbeda sehingga **setiap ticker Shanghai selalu ambiguous**; side query yang gagal dapat mendemote identity yang sudah locked; HTTP 400 Yahoo untuk setiap query CJK dicatat sebagai source *failure* alih-alih "tidak listed di sini"; whitelist hardcoded per-tool memblokir 11 dari 17 spelling argumen yang didokumentasikan; jawaban Mandarin ditolak karena menulis `雅虎` atau `元` alih-alih nama loader ASCII; dan thousands separator memecah `¥1,309.22` sehingga `1` dibandingkan terhadap observed range. Pertanyaan konseptual dan comparison report juga tidak lagi dead-end. Quote di luar recorded OHLC evidence tetap ditolak. **Baru:** `src/quantlib` — 249 fungsi teruji di 17 module (options, bonds, credit, econometrics, VaR/CVaR/EVT, attribution, event studies, purged CV) yang dapat diakses dari CLI, Web UI, REST API, dan MCP melalui `quantlib_call` read-only, sehingga skill mengimport finance math alih-alih membawa formula dalam markdown; **valuation engine** (`run_dcf` / `run_comps` / three-statement) dengan satu rule utama: input yang hilang membuat model NOT RUNNABLE, bukan diam-diam diberi default; **entity + irregular cash-flow spine** (XIRR / MOIC / DPI / TVPI, TWR / Modified Dietz melalui `cashflow_performance`) yang sengaja dipertahankan paralel dengan bar engine; **governance pada setiap run** — hash manifest atas prompt, skill, tool registry, dan package version, plus hash-chained fsynced audit ledger di mana bahkan edit yang direhash sendiri tertangkap satu record kemudian; empat data tool read-only dari source publik gratis (SEC **13F** dengan quarter-over-quarter diff, **ETF look-through** di mana tracker CSI-300 diresolve menjadi 342 position yang mencakup 98.66% net asset alih-alih hanya top ten kuartalan, **prediction markets** sebagai labelled implied probability, dan **arXiv/OpenAlex** dengan claim beranchor source); enam institutional command (`/comps` `/dcf` `/attrib` `/memo` `/earnings` `/screen`); investor lenses sebagai standalone skill; lima playbook scheduled-research; **desktop Electron shell** dengan packaging Windows checksum-pinned dan `safeStorage`; **eToro** sebagai connector broker ke-13; **Korea (KRX)** sebagai backtest engine ke-9; **OpenBB Workspace bridge**; equity Kanada end-to-end; serta `sentiment`, `technical_indicators`, `options_payoff`, `orderbook_depth`, ModelScope, dan `vibe-trading update`. **Correctness:** period SEC sekarang dikelompokkan berdasarkan span `(start, end)` — angka annual sebelumnya dapat mengembalikan hanya satu quarter, understatement 4.2×; harga A-share Tushare sekarang corporate-action adjusted, sedangkan raw return melintasi ex-date dapat meleset hingga 47 percentage point; `bar_returns` tidak lagi mencatat trading halt sebagai move 0%; annualization mencakup seluruh 24 data source; sandbox gap ditutup sehingga generated code tidak dapat mengimport broker layer atau mencapai `socket`/`subprocess` melalui renamed binding; dan mixed-currency composite backtest ditolak alih-alih dijumlahkan menjadi satu equity curve. Terima kasih @santhreal, @shadowinlife, @Robin1987China, @he-yufeng, @QCYTSN, @Shizoqua, @honginp, @cgycorey, @wiliao, @ngoanpv, @x-lambda, @ofeksh-tr, @00EVA, @zwrong, @yrk111222, @su322, @hhj123123, @dineeshd, @sambazhu, @ddy4633, @tyj147454413-cmd, @y85998607, @JungHoonGhae, @shugaoye, @TSENGCHIENFENG, @darkknight4563, @MuggleJinx, @klmtseng, @ebujinovch, @g0rdonL, @AmirF194, @Echoandelementwebsites, @yagnikpipaliya, @dvirarad, dan @1anter.

- **2026-08-09** 🪟 **Packaging Windows aman, market Kanada, ModelScope, dan Alpha Zoo melalui MCP**: packaging desktop Windows sekarang merakit embedded Python 3.12 runtime yang checksum-pinned beserta path review/signing NSIS x64, ditambah Electron `safeStorage` untuk set credential dalam allowlist. Renderer dapat mengatur atau menghapus secret tetapi tidak pernah membacanya; plaintext config dimigrasikan sekali; decrypted value hanya mencapai backend yang dimiliki; dan baik unsigned review maupun signed build fail-closed pada signature state yang salah. Tidak ada installer artifact yang dipublish dari PR ini ([#1015](https://github.com/HKUDS/Vibe-Trading/pull/1015)). Equity Kanada sekarang bekerja end-to-end: simbol `.TO`/`.V` diklasifikasikan dalam CAD, route melalui Yahoo → yfinance → local fallback, dieksekusi dengan Canada-specific GlobalEquity rules, benchmark terhadap `XIC.TO`, dan mixed-currency aggregation ditolak. Strict historical backtest USD-M juga dapat opt-in ke `position_adjustment=rebalance` sambil mempertahankan collateral, funding, fee, realized P&L, liquidation behaviour, dan immutable fill evidence saat increase maupun reduction ([#1024](https://github.com/HKUDS/Vibe-Trading/pull/1024), [#1019](https://github.com/HKUDS/Vibe-Trading/pull/1019), menutup [#952](https://github.com/HKUDS/Vibe-Trading/issues/952)). ModelScope bergabung sebagai built-in provider melalui endpoint hosted-inference resmi yang kompatibel OpenAI, dengan `Qwen/Qwen3.5-27B` sebagai default ([#1011](https://github.com/HKUDS/Vibe-Trading/pull/1011)); `vibe-trading update` baru membedakan wheel install dari editable/source checkout, menginstall exact release yang diperiksanya, dan memverifikasi fresh metadata tanpa downgrade ([#1020](https://github.com/HKUDS/Vibe-Trading/pull/1020)); dan `alpha_zoo` plus bounded `alpha_bench` sekarang mencapai MCP (64 tool), dengan limit horizon/result/output-path dan safe report creation ([#979](https://github.com/HKUDS/Vibe-Trading/pull/979)). Refresh lock Python dan frontend yang sudah diverifikasi juga memperbarui grouped dependencies, `postcss`, dan `akshare` ([#1021](https://github.com/HKUDS/Vibe-Trading/pull/1021), [#1023](https://github.com/HKUDS/Vibe-Trading/pull/1023), [#1026](https://github.com/HKUDS/Vibe-Trading/pull/1026), [#1027](https://github.com/HKUDS/Vibe-Trading/pull/1027)). Terima kasih [@QCYTSN](https://github.com/QCYTSN), [@wiliao](https://github.com/wiliao), [@honginp](https://github.com/honginp), [@yrk111222](https://github.com/yrk111222), [@zwrong](https://github.com/zwrong), dan [@cgycorey](https://github.com/cgycorey).

- **2026-08-08** 🧱 **Desktop shell, eToro, atomic rebalancing, dan broad reliability pass**: host Electron source-first sekarang memiliki lifecycle backend yang sudah ada — random loopback port, secret per launch, startup recovery lima locale, dan cleanup owned-process — sementara eToro bergabung dengan profile demo/real yang dipisahkan path; live action yang meningkatkan risk tetap mandate-gated dan diaudit, dan API capability surface diautentikasi di bawah enforced CSP ([#923](https://github.com/HKUDS/Vibe-Trading/pull/923), [#989](https://github.com/HKUDS/Vibe-Trading/pull/989), [#961](https://github.com/HKUDS/Vibe-Trading/pull/961)). Backtest mendapat opt-in atomic same-direction rebalancing dengan immutable fill evidence; Shadow memisahkan mixed market berdasarkan settlement currency tanpa invented FX aggregation dan menghormati runtime root yang dikonfigurasi; indicator menggunakan consecutive unsampled history; negative-equity drawdown dan empty insolvent cross account ditangani dengan benar ([#951](https://github.com/HKUDS/Vibe-Trading/pull/951), [#997](https://github.com/HKUDS/Vibe-Trading/pull/997), [#1017](https://github.com/HKUDS/Vibe-Trading/pull/1017), [#1005](https://github.com/HKUDS/Vibe-Trading/pull/1005), [#958](https://github.com/HKUDS/Vibe-Trading/pull/958), [#959](https://github.com/HKUDS/Vibe-Trading/pull/959)). OpenAI Codex OAuth mendapat credential store terpisah yang tersinkron dan one-shot 401 recovery; proxy opt-out mencakup client sync dan async; sandboxed run mempertahankan canonical root; scheduled research mengisolasi record malformed dan memperbaiki interval-timezone validation; request lowercase `4h` mengembalikan bar empat jam yang benar ([#1014](https://github.com/HKUDS/Vibe-Trading/pull/1014), [#995](https://github.com/HKUDS/Vibe-Trading/pull/995), [#1012](https://github.com/HKUDS/Vibe-Trading/pull/1012), [#1003](https://github.com/HKUDS/Vibe-Trading/pull/1003), [#1004](https://github.com/HKUDS/Vibe-Trading/pull/1004), [#1013](https://github.com/HKUDS/Vibe-Trading/pull/1013)). Reply QQ mempertahankan source message ID, slug model panjang tetap readable, dan agent berhenti ketika evidence sudah cukup ([#1008](https://github.com/HKUDS/Vibe-Trading/pull/1008), [#1006](https://github.com/HKUDS/Vibe-Trading/pull/1006), [#1010](https://github.com/HKUDS/Vibe-Trading/pull/1010)). Terima kasih [@QCYTSN](https://github.com/QCYTSN), [@Shizoqua](https://github.com/Shizoqua), [@ngoanpv](https://github.com/ngoanpv), [@hhj123123](https://github.com/hhj123123), [@su322](https://github.com/su322), [@Robin1987China](https://github.com/Robin1987China), [@shadowinlife](https://github.com/shadowinlife), [@dineeshd](https://github.com/dineeshd), [@honginp](https://github.com/honginp), [@santhreal](https://github.com/santhreal), [@00EVA](https://github.com/00EVA), [@x-lambda](https://github.com/x-lambda), dan [@ofeksh-tr](https://github.com/ofeksh-tr).

- **2026-08-07** 🛡️ **Lebih sedikit false refusal, sandbox gap ditutup, QVeris di MCP**: grounding gate berhenti menolak jawaban well-formed karena angka yang sebenarnya bukan price — confidence score, indicator reading, moving-average window, date tanpa tahun seperti `8/5`, percentage range, dan trigger level milik trading plan sendiri (`close ≥ 6.45` adalah condition, bukan quote) — sementara quote di luar recorded OHLC evidence tetap ditolak, dan price table bertanggal `08-05` sekarang cocok dengan evidence-nya alih-alih setiap cell kembali unavailable ([#1001](https://github.com/HKUDS/Vibe-Trading/issues/1001), [#983](https://github.com/HKUDS/Vibe-Trading/issues/983)). **Sandbox:** generated strategy code tidak lagi dapat mengimport broker layer atau mencapai `socket`/`subprocess`/`os.system`/`ctypes` melalui renamed binding — keduanya sebelumnya diterima, sedangkan `src.quantlib` tetap dapat diimport. Discovery/inspect/execute **QVeris** bergabung ke MCP surface (62 tool), dengan cost quote dibaca dari marketplace alih-alih dipercaya dari caller ([#976](https://github.com/HKUDS/Vibe-Trading/pull/976), menutup [#964](https://github.com/HKUDS/Vibe-Trading/issues/964), terima kasih [@shadowinlife](https://github.com/HKUDS/Vibe-Trading/shadowinlife)). Ditambah fallback routing market-data HK diperbaiki dengan source Tencent HK baru, crypto yfinance dirutekan ke crypto engine, memory entry ditulis dan direcover bersama suffix `.md`, argument MCP list/dict mentoleransi client yang mengirim JSON-string, dan artifact Portfolio Studio ditampilkan di run detail ([#1000](https://github.com/HKUDS/Vibe-Trading/pull/1000), [#970](https://github.com/HKUDS/Vibe-Trading/pull/970), [#984](https://github.com/HKUDS/Vibe-Trading/pull/984), [#993](https://github.com/HKUDS/Vibe-Trading/pull/993), [#980](https://github.com/HKUDS/Vibe-Trading/pull/980), [#982](https://github.com/HKUDS/Vibe-Trading/pull/982), [#966](https://github.com/HKUDS/Vibe-Trading/pull/966), [#973](https://github.com/HKUDS/Vibe-Trading/pull/973), terima kasih [@he-yufeng](https://github.com/HKUDS/Vibe-Trading/he-yufeng), [@ngoanpv](https://github.com/HKUDS/Vibe-Trading/ngoanpv), [@sambazhu](https://github.com/HKUDS/Vibe-Trading/sambazhu)).

- **2026-08-06** 🧮 **Layer finance-math teruji + valuation engine + irregular cash flow + governance yang benar-benar terhubung**: `src/quantlib` menggantikan formula yang sebelumnya hidup sebagai markdown di dalam skill dengan satu implementasi teruji untuk masing-masing — options, bonds, credit, econometrics, VaR/CVaR/EVT, attribution, event studies, multiple-testing control, purged cross-validation — total 265 fungsi, dapat diakses dari CLI, Web UI, REST API, dan MCP melalui tool read-only `quantlib_call` baru. Valuation engine (`run_dcf` / `run_comps` / three-statement) menolak berjalan ketika input hilang alih-alih diam-diam memberi default, dan spine entity + cash-flow baru menerima NAV, capital call, dan coupon (XIRR/MOIC/DPI/TVPI serta TWR/Modified Dietz melalui `cashflow_performance`; crypto L2 impact cost melalui `orderbook_depth`). Setiap run sekarang menulis hash manifest, audit ledger menggunakan hash chain sehingga tampering dapat dideteksi, dan seluruh 30 swarm preset diaudit ulang — deliverable yang tidak dapat dihitung oleh tool yang diberikan sekarang dinyatakan demikian, bukan dibuat-buat.

- **2026-08-05** 🔭 **Institutional holdings, ETF look-through, prediction market, research paper**: empat data tool read-only, semuanya memakai source publik gratis — book SEC 13F dengan diff position quarter-over-quarter; constituent ETF lintas market (tracker CSI-300 diresolve menjadi 342 position yang mencakup 98.7% net asset, bukan hanya top ten kuartalan); event contract sebagai labelled implied probability; serta pencarian arXiv/OpenAlex yang menandai apa yang tidak dinyatakan source alih-alih menyimpulkannya sendiri. Ditambah lima template scheduled-research, enam institutional command (`/comps` `/dcf` `/attrib` `/memo` `/earnings` `/screen`), investor lenses sebagai standalone skill, dan agent core yang menelusuri setiap angka kembali ke tool yang menghasilkannya.

- **2026-08-04** 🔧 **Correctness pass: fundamentals, harga A-share, result oversized**: period laporan SEC sekarang dikelompokkan berdasarkan span `(start, end)` — sebuah 10-Q memfile quarter sebenarnya dan year-to-date frame dengan end date serta fiscal period yang sama, sehingga `period="annual"` sebelumnya mengembalikan hanya satu quarter untuk AAPL FY2018–2020 (understatement 4.2×) dan setiap slot fiscal-Q4 dalam quarterly series membawa angka setahun penuh; `get_fundamentals("AAPL.US")` tidak lagi menjawab `ok:true` dengan panel all-null. Harga A-share Tushare sekarang corporate-action adjusted baik di factor bench maupun backtest — raw close-to-close return melewati ex-date dapat meleset hingga 47 percentage point (300750.SZ, 2023-04-26) — dan bench CSI300 memask setiap tanggal berdasarkan point-in-time membership index. Cross-market composite backtest menolak set code mixed-currency alih-alih menjumlahkan CNY, USD, dan KRW menjadi satu equity curve; option leg dimark pada volatility saat dibuka, menghapus fabricated day-zero P&L hingga +93% dari premium; tool result oversized dipaginasi per whole record dengan total eksplisit alih-alih dipotong di tengah JSON; dan `calc_metrics` melaporkan tracking error serta benchmark beta.

- **2026-08-03** ⏰ **Scheduled research timezone-aware + stock screening tidak lagi dead-end**: scheduled job sekarang menerima optional IANA `timezone` dan mengevaluasi cron pada wall clock zona tersebut, sehingga cadence tetap benar melewati DST — spring-forward gap dilewati dan waktu ambigu saat fall-back hanya berjalan sekali — sementara field cron mendapat dukungan comma list dan range (`1,3-5`), job tanpa timezone mempertahankan semantic UTC, dan Web UI mendapat halaman **Scheduled** dalam kelima locale, yang sebelumnya sama sekali tidak memiliki scheduling surface ([#954](https://github.com/HKUDS/Vibe-Trading/pull/954), menutup [#953](https://github.com/HKUDS/Vibe-Trading/issues/953), terima kasih [@ngoanpv](https://github.com/ngoanpv)). Request screening tidak lagi berakhir buntu: shortlist dengan banyak candidate dihitung sebagai jawaban alih-alih stalled resolution dan berhenti setelah candidate dikunci, sedangkan price validation berhenti membaca digit ticker, localized date, share count, dan position cost sebagai quoted price — namun tetap menolak quote di luar recorded OHLC evidence (menutup [#955](https://github.com/HKUDS/Vibe-Trading/issues/955)). Agent memory juga mendapat exact index-anchor matching dan result bound yang benar-benar dihormati ([#956](https://github.com/HKUDS/Vibe-Trading/pull/956), [#957](https://github.com/HKUDS/Vibe-Trading/pull/957), terima kasih [@santhreal](https://github.com/santhreal)).

- **2026-08-02** 🧠 **Live model discovery, runtime identity yang jujur, dan refresh dependency yang terverifikasi**: Settings sekarang melakukan discovery model provider yang sudah dikonfigurasi on demand dengan warning code stabil dan control lima locale, sementara setiap reply mencatat dan memuat ulang immutable provider/model/reasoning identity yang benar-benar melayaninya — lalu membersihkannya dengan aman ketika session berubah ([#924](https://github.com/HKUDS/Vibe-Trading/pull/924), terima kasih [@QCYTSN](https://github.com/QCYTSN)). Sembilan update Python dengan hash lock plus `jsdom`/`postcss` juga masuk dengan exact-version import, 330 focused test, production build, 373 frontend test, full `main` CI, dan Dependency Graph hijau ([#949](https://github.com/HKUDS/Vibe-Trading/pull/949), [#948](https://github.com/HKUDS/Vibe-Trading/pull/948)); breaking bump MCP 2.0 tetap belum digabungkan sambil menunggu migrasi lock/runtime lengkap ([#950](https://github.com/HKUDS/Vibe-Trading/pull/950)).

- **2026-08-01** 🧮 **Analytics strategy options + market sentiment + research USD-M yang auditable**: workflow options payoff baru menghitung secara analitik extrema P&L saat expiry, exact breakeven — termasuk continuous zero-P&L interval — entry commission yang selaras engine, dan scenario spot × IV melalui Agent dan MCP ([#946](https://github.com/HKUDS/Vibe-Trading/pull/946), dibangun ulang dari [#883](https://github.com/HKUDS/Vibe-Trading/pull/883), terima kasih @he-yufeng). Tool read-only `sentiment` menilai arbitrary text secara lokal dan mengambil crypto Fear & Greed Index tanpa API key ([#939](https://github.com/HKUDS/Vibe-Trading/pull/939), terima kasih @Robin1987China). Strict USD-M backtest sekarang mempersist event fill, funding, risk, dan liquidation secara berurutan plus fidelity summary, sambil menolak interval 100× yang tidak didukung ([#936](https://github.com/HKUDS/Vibe-Trading/pull/936), terima kasih @honginp). Reliability improvement juga memastikan symbol dan venue resolution dilakukan sebelum market-data call, final quoted price diperiksa terhadap recorded OHLC evidence, scheduled research meretry transient failure, dan nested MCP result terserialize dengan bersih.

- **2026-07-31** 🔧 **Lifecycle liquidation USD-M + technical indicators + user-level state directory**: mode opt-in `perpetual_strict` melakukan settle historical funding sebelum fill dan mengeksekusi breach isolated/cross margin sebagai liquidation nyata ([#903](https://github.com/HKUDS/Vibe-Trading/pull/903), terima kasih @honginp). Tool read-only `technical_indicators` menghitung RSI/MACD/Bollinger/SMA/EMA melalui loader yang sudah ada ([#921](https://github.com/HKUDS/Vibe-Trading/pull/921), refs [#920](https://github.com/HKUDS/Vibe-Trading/issues/920), terima kasih @Robin1987China). Session, run, swarm run, dan upload sekarang berada di bawah `~/.vibe-trading` (dapat dipindahkan melalui `VIBE_TRADING_HOME`) dengan one-time automatic migration ([#925](https://github.com/HKUDS/Vibe-Trading/pull/925), menutup [#904](https://github.com/HKUDS/Vibe-Trading/issues/904), terima kasih @MuggleJinx). Ditambah sepuluh correctness fix — Yahoo `.SS` diklasifikasikan sebagai A-share, code A-share bare/prefix-style, crypto pair dengan slash, guard `nan`/`inf` ([#919](https://github.com/HKUDS/Vibe-Trading/pull/919), [#926](https://github.com/HKUDS/Vibe-Trading/pull/926)–[#935](https://github.com/HKUDS/Vibe-Trading/pull/935), terima kasih @santhreal).

- **2026-07-30** 🎨 **WebUI dibangun ulang + market Korea (KRX) + OpenBB Workspace bridge**: Web UI mendapat overhaul guided-minimalism — tanpa flash pada first frame, satu durable activity object per turn dengan live reasoning whisper dan tool trail yang aman terhadap reload, judul session yang ditulis LLM, serta parity penuh lima locale. **Equity Korea (KRX: KOSPI/KOSDAQ)** menjadi backtest engine ke-9 — band ±30% pada execution time, long-only, transaction tax 2026 sebesar 0.20%, optional loader `pykrx` ([#693](https://github.com/HKUDS/Vibe-Trading/pull/693), terima kasih @JungHoonGhae) — ditambah **OpenBB Workspace bridge** ([#817](https://github.com/HKUDS/Vibe-Trading/pull/817), terima kasih @shugaoye) dan tool read-only **Taiwan snapshot** ([#848](https://github.com/HKUDS/Vibe-Trading/pull/848), terima kasih @TSENGCHIENFENG). Correctness: daily price band dinilai **pada execution time**, bukan dari close decision bar; satu session menjalankan hanya satu attempt pada satu waktu (HTTP 409) dan user stop memiliki terminal state tersendiri ([#676](https://github.com/HKUDS/Vibe-Trading/pull/676), terima kasih @tyj147454413-cmd). Ditambah durable trace ([#662](https://github.com/HKUDS/Vibe-Trading/pull/662)), tool result yang secret-scrubbed ([#675](https://github.com/HKUDS/Vibe-Trading/pull/675)), fail-closed tool argument ([#913](https://github.com/HKUDS/Vibe-Trading/pull/913)/[#911](https://github.com/HKUDS/Vibe-Trading/pull/911), terima kasih @santhreal), direct-OpenAI `reasoning_effort` ([#755](https://github.com/HKUDS/Vibe-Trading/pull/755), terima kasih @1anter), dan numeric guard di risk x-ray / edge density / options engine ([#909](https://github.com/HKUDS/Vibe-Trading/pull/909)/[#908](https://github.com/HKUDS/Vibe-Trading/pull/908)/[#907](https://github.com/HKUDS/Vibe-Trading/pull/907)).

- **2026-07-29** 🔧 **Return yang aman terhadap gap + modeling liquidation risk + risk x-ray di setiap run**: `bar_returns` tidak lagi menghapus move nyata setelah trading halt yang lebih panjang dari forward-fill window — sebelumnya move saat resume diam-diam dicatat sebagai 0, menurunkan volatility dan menggelembungkan Sharpe — dan prior price `inf` tidak lagi dapat terbaca sebagai −100% yang bersih ([#895](https://github.com/HKUDS/Vibe-Trading/pull/895), terima kasih @darkknight4563). Annualization sekarang mencakup **seluruh 24 data source** pada setiap interval, dengan coverage test yang menggagalkan CI ketika loader baru masuk tanpa entry ([#891](https://github.com/HKUDS/Vibe-Trading/pull/891), menutup [#884](https://github.com/HKUDS/Vibe-Trading/issues/884), terima kasih @Robin1987China). Research USD-M perpetual mendapat evaluasi deterministic **isolated & cross margin liquidation** ([#889](https://github.com/HKUDS/Vibe-Trading/pull/889), terima kasih @honginp), dan setiap portfolio backtest sekarang menghasilkan **risk x-ray artifact** (`risk_xray.json`/`.md`) dengan headline metric concentration/vol/drawdown ([#900](https://github.com/HKUDS/Vibe-Trading/pull/900), terima kasih @he-yufeng). CLI `connector` sekarang memuat `~/.vibe-trading/.env`, sehingga credential broker dari environment resolve lagi ([#902](https://github.com/HKUDS/Vibe-Trading/pull/902), menutup [#901](https://github.com/HKUDS/Vibe-Trading/issues/901), terima kasih @MuggleJinx). Ditambah channel message split yang mempertahankan indent dan parsing skill-frontmatter di EOF ([#867](https://github.com/HKUDS/Vibe-Trading/pull/867)/[#861](https://github.com/HKUDS/Vibe-Trading/pull/861), terima kasih @santhreal).

- **2026-07-28** 🔧 **Model Claude generasi berikutnya tidak lagi terblokir + return aman terhadap sign**: model Claude yang mendeprecate field `temperature` (opus-4-7, opus-5, sonnet-5) sekarang bekerja — adapter menghapus field itu ketika API menolaknya, retry sekali, lalu mengingat model tersebut sehingga tidak perlu patch per release ([#890](https://github.com/HKUDS/Vibe-Trading/pull/890), menutup [#856](https://github.com/HKUDS/Vibe-Trading/issues/856), terima kasih @yagnikpipaliya). `vibe-trading run` non-interaktif sekarang menginject host session id: sebelumnya research-goal tool gagal di setiap call sementara run tetap melaporkan success ([#885](https://github.com/HKUDS/Vibe-Trading/issues/885)). Return buy-and-hold sekarang sign-safe — prior close yang mendekati nol tidak lagi meledakkan compounded benchmark, dan exact-zero close tidak lagi menghasilkan `inf`/`nan` ([#872](https://github.com/HKUDS/Vibe-Trading/issues/872), terima kasih @darkknight4563). Frontend berpindah ke **Node 22 + React Router 8**, menutup advisory high-severity.

- **2026-07-27** 🔧 **Integritas correlation + perbaikan export vn.py 4.0 + batch encoding**: rolling correlation matrix tidak lagi melakukan forward-fill pada close yang hilang — session yang halted sebelumnya dinilai sebagai fabricated return 0% terhadap move nyata peer, mendistorsi matrix ([#873](https://github.com/HKUDS/Vibe-Trading/pull/873), terima kasih @ddy4633). Skill **vn.py export** diperbaiki untuk layout vn.py 4.x, tempat `vnpy.app.cta_strategy` tidak lagi ada di upstream — template sekarang import dari `vnpy_ctastrategy` ([#869](https://github.com/HKUDS/Vibe-Trading/pull/869), terima kasih @y85998607). Ditambah batch enam fix: decoding UTF-16 BOM pada document reader dan CSV trade-journal, currency symbol dibuang sebelum numeric coercion, simbol bergaya `BTCUSDT` diinfer sebagai crypto, interval lowercase `1h`/`1d` diannualisasi dengan benar, serta karakter CJK dipertahankan dalam slug directory skill ([#862](https://github.com/HKUDS/Vibe-Trading/pull/862), [#863](https://github.com/HKUDS/Vibe-Trading/pull/863), [#864](https://github.com/HKUDS/Vibe-Trading/pull/864), [#865](https://github.com/HKUDS/Vibe-Trading/pull/865), [#866](https://github.com/HKUDS/Vibe-Trading/pull/866), [#868](https://github.com/HKUDS/Vibe-Trading/pull/868), terima kasih @santhreal).

- **2026-07-26** 🔒 **Dependency lock + transparansi universe**: install Docker dengan hash lock bekerja kembali, dengan CI lock check baru ([#858](https://github.com/HKUDS/Vibe-Trading/pull/858), menutup [#847](https://github.com/HKUDS/Vibe-Trading/issues/847)). `alpha bench` sekarang mengungkap source CSI300/SP500, count, degraded fallback, dan survivorship bias ([#859](https://github.com/HKUDS/Vibe-Trading/pull/859), menutup [#845](https://github.com/HKUDS/Vibe-Trading/issues/845)). Actions dan lima dependency frontend juga direfresh ([#850](https://github.com/HKUDS/Vibe-Trading/pull/850)–[#852](https://github.com/HKUDS/Vibe-Trading/pull/852)).

- **2026-07-25** 🔧 **Perpetual yang lebih realistis + fix crash MCP + batch correctness**: USD-M perpetual mendapat **margin state contract** ([#798](https://github.com/HKUDS/Vibe-Trading/pull/798), terima kasih @honginp) dan engine sekarang benar-benar memakai **historical funding rate** alih-alih fetch lalu mengabaikannya ([#819](https://github.com/HKUDS/Vibe-Trading/pull/819), terima kasih @g0rdonL). Result dataclass MCP tidak lagi crash karena false `Circular reference detected` ([#849](https://github.com/HKUDS/Vibe-Trading/pull/849), terima kasih @Echoandelementwebsites), dan CLI/HTML `alpha bench` meneruskan disclosure survivorship `_meta` ([#841](https://github.com/HKUDS/Vibe-Trading/pull/841), menutup [#797](https://github.com/HKUDS/Vibe-Trading/issues/797), terima kasih @AmirF194). Ditambah 12 correctness fix di journal, connector, dan channel ([#799](https://github.com/HKUDS/Vibe-Trading/pull/799)–[#810](https://github.com/HKUDS/Vibe-Trading/pull/810), terima kasih @santhreal), serta label akun nyata pada balance CLI ([#843](https://github.com/HKUDS/Vibe-Trading/pull/843), menutup [#846](https://github.com/HKUDS/Vibe-Trading/issues/846), terima kasih @Robin1987China).

- **2026-07-24** 🔀 **Memory Tier 2, composable optimizer constraint + sweep penanganan interval**: persistent memory mendapat **Tier 2 structural organization** ([#815](https://github.com/HKUDS/Vibe-Trading/pull/815), terima kasih @shadowinlife), dan backtest optimizer menerima **composable weight constraint** ([#818](https://github.com/HKUDS/Vibe-Trading/pull/818), terima kasih @he-yufeng). Correctness: daily-bar validator dapat opt-in ke **non-positive price** — membuka pada bar negatif tetapi tetap menolak nol ([#816](https://github.com/HKUDS/Vibe-Trading/pull/816), menutup [#571](https://github.com/HKUDS/Vibe-Trading/issues/571), terima kasih @darkknight4563). Ditambah **interval-normalization sweep** 19 PR untuk loader: alias lowercase `1h/4h/1d/1w` diterima di semua tempat, interval unsupported sekarang fail fast alih-alih diam-diam mengembalikan daily bar, Yahoo `4H` dipetakan ke `1h`, dan MT5 menerima `1W/1M` ([#812](https://github.com/HKUDS/Vibe-Trading/pull/812)–[#838](https://github.com/HKUDS/Vibe-Trading/pull/838), terima kasih @santhreal), fix trade-journal untuk Eastmoney Excel-serial date ([#811](https://github.com/HKUDS/Vibe-Trading/pull/811), terima kasih @santhreal), dan fix README nav-anchor ([#840](https://github.com/HKUDS/Vibe-Trading/pull/840), terima kasih @dvirarad).

- **2026-07-23** 🔧 **Reliability sweep + strict alpha-bench ditampilkan + memory lifecycle opt-in**: batch 22 PR contributor. **Reliability sweep** luas memperbaiki penanganan timeframe end-to-end — yfinance `1M`→monthly (bukan minute), CCXT `1W`/`1M`, akshare/india-broker menolak interval unsupported alih-alih diam-diam daily, serta connector Tiger/Alpaca/OKX/Shoonya/Longbridge mempertahankan `1H`/`4H` sebagai hour bar — plus normalisasi Excel-date trade-journal (eastmoney float `YYYYMMDD`, Futu/Tonghuashun serial date), `report_audit` dengan finite JSON, validation `holding_days` kosong, dan edge markdown table Feishu/CLI ([#778](https://github.com/HKUDS/Vibe-Trading/pull/778)–[#794](https://github.com/HKUDS/Vibe-Trading/pull/794), terima kasih @santhreal). **MT5** `trading_history` sekarang mengcoerce numpy scalar sehingga serialisasi JSON tidak lagi mati pada `int64` ([#776](https://github.com/HKUDS/Vibe-Trading/pull/776), menutup [#774](https://github.com/HKUDS/Vibe-Trading/issues/774), terima kasih @shadowinlife), dan **PIT fundamentals** mendedup row restated serta mencegah snapshot mundur ke fiscal period lebih lama ketika restatement datang terlambat ([#772](https://github.com/HKUDS/Vibe-Trading/pull/772), menutup [#771](https://github.com/HKUDS/Vibe-Trading/issues/771), terima kasih @klmtseng). Baru: **`alpha bench --strict`** akhirnya menghubungkan strict same-universe random-control + OOS gate yang sejak 0.1.9 sudah dikirim tetapi tidak dapat dijangkau ([#796](https://github.com/HKUDS/Vibe-Trading/pull/796), menutup [#773](https://github.com/HKUDS/Vibe-Trading/issues/773), terima kasih @he-yufeng), **memory lifecycle** opt-in (quality scoring, Ebbinghaus decay, archive-only GC — semuanya off secara default) ([#733](https://github.com/HKUDS/Vibe-Trading/pull/733), menutup [#732](https://github.com/HKUDS/Vibe-Trading/issues/732), terima kasih @shadowinlife), serta artifact **rebalance-notes** backtest + turnover metric ([#795](https://github.com/HKUDS/Vibe-Trading/pull/795), terima kasih @he-yufeng).

- **2026-07-22** 🚀 **v0.1.12 dirilis** ([Catatan rilis](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.12), `pip install -U vibe-trading-ai`): **correlation regime timeline** menambahkan endpoint `GET /correlation/regime` + strip opt-in pada tab Correlation — edge density dijalankan melalui causal hysteresis state machine yang menandai episode market FUSED, sebagai descriptive risk context bukan signal ([#756](https://github.com/HKUDS/Vibe-Trading/pull/756), menutup [#719](https://github.com/HKUDS/Vibe-Trading/issues/719), terima kasih @ebujinovch). Resolution endpoint provider sekarang fallback ke canonical base URL masing-masing provider dan menangani endpoint non-SSE dengan baik, memperbaiki native provider **zai** pada glm-5.1 ([#758](https://github.com/HKUDS/Vibe-Trading/issues/758)). Ditambah **reliability sweep** strict-JSON / finite-number pada metrics, factor, pattern, session, dan journal ([#761](https://github.com/HKUDS/Vibe-Trading/pull/761)–[#770](https://github.com/HKUDS/Vibe-Trading/pull/770), terima kasih @santhreal) dan decouple maintenance-bracket Binance yang menjaga backtest `-PERP` tetap zero-credential ([#757](https://github.com/HKUDS/Vibe-Trading/pull/757), terima kasih @honginp). Merangkum sekitar 90 fix sejak 0.1.11.

- **2026-07-21** 🔧 **Kelengkapan data-loader + sweep reliability fix**: result market-data partial sekarang melengkapi simbol yang hilang melalui fallback chain dan fail-closed alih-alih diam-diam mengecilkan universe backtest ([#689](https://github.com/HKUDS/Vibe-Trading/pull/689), menutup [#681](https://github.com/HKUDS/Vibe-Trading/issues/681), terima kasih @xkam7ar), dan bar OKX menggunakan endpoint `history-candles` dengan retry rate-limit untuk deep backfill ([#644](https://github.com/HKUDS/Vibe-Trading/pull/644), terima kasih @tyj147454413-cmd). Ditambah fix sweep: network guard MCP menerima host IPv6 / case-variant ([#750](https://github.com/HKUDS/Vibe-Trading/pull/750), terima kasih @Robin1987China), parser trade-journal melewati row simbol blank/NaN ([#749](https://github.com/HKUDS/Vibe-Trading/pull/749), terima kasih @Robin1987China), Shadow Account melewati mined entry-hour gate pada daily bar ([#748](https://github.com/HKUDS/Vibe-Trading/pull/748), terima kasih @Robin1987China), dan endpoint API regional MiniMax dapat dipilih ([#731](https://github.com/HKUDS/Vibe-Trading/pull/731), terima kasih @octo-patch).

- **2026-07-20** 🔀 **Provider, MetaTrader 5, dan reliability sweep**: native **Anthropic Messages API** (optional extra `[anthropic]`, [#695](https://github.com/HKUDS/Vibe-Trading/pull/695), terima kasih @jelech), **SiliconFlow** ([#565](https://github.com/HKUDS/Vibe-Trading/pull/565), terima kasih @UNHNQ), dan **iFlytek Spark** ([#537](https://github.com/HKUDS/Vibe-Trading/pull/537), terima kasih @FenjuFu) bergabung ke roster provider, dan connector broker **MetaTrader 5 (Exness)** + data source forex/metal `mt5` masuk (connector broker → **12**, [#481](https://github.com/HKUDS/Vibe-Trading/pull/481), terima kasih @StaniellG). Ditambah engine OCR **`llm-vision`** yang provider-agnostic ([#548](https://github.com/HKUDS/Vibe-Trading/pull/548), terima kasih @shadowinlife), vectorization signal-alignment **80×** ([#698](https://github.com/HKUDS/Vibe-Trading/pull/698), terima kasih @shadowinlife), data historical **Binance USD-M funding/bracket** ([#716](https://github.com/HKUDS/Vibe-Trading/pull/716), terima kasih @honginp), cache MCP-discovery untuk swarm ([#704](https://github.com/HKUDS/Vibe-Trading/pull/704)), dan reliability consolidation yang menutup **13** issue SSE/session/CLI/swarm/scheduler ([#584](https://github.com/HKUDS/Vibe-Trading/pull/584), terima kasih @xkam7ar). Correctness: **partial-close** options sekarang menghormati quantity yang diminta alih-alih flatten seluruh lot ([#577](https://github.com/HKUDS/Vibe-Trading/issues/577)), centralized provider credential resolution ([#563](https://github.com/HKUDS/Vibe-Trading/pull/563)), queued-cancel handling ([#641](https://github.com/HKUDS/Vibe-Trading/pull/641)), race streaming-DOM frontend ([#717](https://github.com/HKUDS/Vibe-Trading/pull/717), terima kasih @Marnie0415), dan renderer CLI connector ([#726](https://github.com/HKUDS/Vibe-Trading/pull/726), terima kasih @nareshkps).

- **2026-07-19** 🔧 **Artikel stock-news US/HK nyata + fix factor-analysis MCP + robustness pass**: tool stock-news sekarang mengembalikan artikel **Yahoo Finance** nyata (title/url/source/published/snippet) untuk ticker US dan HK alih-alih related-instrument match, tetap dirutekan melalui frozen IP-throttled client ([#730](https://github.com/HKUDS/Vibe-Trading/pull/730), terima kasih @yxhuang). Tool MCP `factor_analysis` diselaraskan kembali dengan contract CSV nyata milik registered tool, sehingga call tidak lagi mati pada `KeyError` sebelum berjalan ([#715](https://github.com/HKUDS/Vibe-Trading/pull/715), menutup [#635](https://github.com/HKUDS/Vibe-Trading/issues/635), terima kasih @Robin1987China). Ditambah robustness pass: seluruh **Kimi K-series** (k2/k3/…/`for-coding`) sekarang otomatis memaksa `temperature=1` sesuai requirement API ([#701](https://github.com/HKUDS/Vibe-Trading/pull/701), terima kasih @sambazhu), dan `split_message`, PDF page range, serta trade-journal date filter semuanya fail fast pada input degenerate atau terbalik alih-alih hang atau diam-diam mengembalikan kosong ([#727](https://github.com/HKUDS/Vibe-Trading/pull/727)–[#729](https://github.com/HKUDS/Vibe-Trading/pull/729), terima kasih @santhreal).

- **2026-07-18** 🔧 **Fallback crypto Binance + fix parallel-execution dan correctness**: loader **Binance** bergabung ke fallback chain historical-data crypto ([#643](https://github.com/HKUDS/Vibe-Trading/pull/643), terima kasih @tyj147454413-cmd), dan connector IBKR berpindah ke thread-local connection pool dengan snapshot quote, memperbaiki hang pada parallel agent run ([#636](https://github.com/HKUDS/Vibe-Trading/pull/636), terima kasih @MikeCer). Ditambah correctness pass: factor analysis menolak `n_groups` non-positive, period range terbalik dan detection window non-positive fail fast, `DatetimeIndex` tanpa nama di correlation matrix ditangani, alias column nav/value pada `equity.csv` diterima, dan code A-share kosong tidak lagi dicoerce menjadi `000000.SZ` ([#709](https://github.com/HKUDS/Vibe-Trading/pull/709)–[#714](https://github.com/HKUDS/Vibe-Trading/pull/714), terima kasih @santhreal). Factor stability correlation-rewiring bergabung ke academic zoo ([#705](https://github.com/HKUDS/Vibe-Trading/pull/705), terima kasih @ebujinovch), fundamental zoo diwhitelist untuk factor analysis ([#707](https://github.com/HKUDS/Vibe-Trading/pull/707), terima kasih @sambazhu), persisted run state sekarang fsync-durable ([#645](https://github.com/HKUDS/Vibe-Trading/pull/645), terima kasih @tyj147454413-cmd), dan dev extra menginstall toolchain Black/Ruff yang didokumentasikan ([#634](https://github.com/HKUDS/Vibe-Trading/pull/634), terima kasih @xkam7ar).

- **2026-07-17** 🧩 **Skill correlation-regime + correctness pass luas untuk backtest / data / live-safety**: skill deteksi **correlation-regime** baru (bundled skill → 88, [#557](https://github.com/HKUDS/Vibe-Trading/pull/557), terima kasih @ebujinovch), runtime connection card Longbridge ([#569](https://github.com/HKUDS/Vibe-Trading/pull/569), terima kasih @fanfpy), dan user-defined swarm preset yang dimuat dari `~/.vibe-trading` ([#570](https://github.com/HKUDS/Vibe-Trading/pull/570), terima kasih @darkknight4563). Ditambah hardening di seluruh stack: fix silent-data-corruption pada loader Futu / Tencent / CCXT / mootdx, guard look-ahead-bias dan strict-OOS di factor bench serta Shadow Account, live-trading safety (signed exposure cap, atomic daily order limit, consent-first mandate commit, live state fail-closed), serta peningkatan journal / QVeris-budget / swarm / CI-gate ([#552](https://github.com/HKUDS/Vibe-Trading/pull/552), terima kasih @xor-xe; sebagian besar correctness work oleh @xkam7ar).

- **2026-07-16** 🔧 **Dependency lock diperbaiki + fix penyimpanan Settings di Windows**: runtime lock yang hash-verified diregenerate sehingga `pip install --require-hashes` milik Docker kembali resolve dengan bersih, memperbaiki pin `caio`/`pydantic-core`/`websockets` yang tidak kompatibel ([#564](https://github.com/HKUDS/Vibe-Trading/pull/564), menutup [#558](https://github.com/HKUDS/Vibe-Trading/issues/558), terima kasih @tianrking). Menyimpan setting Agent LLM dari Web UI tidak lagi mengembalikan HTTP 500 di Windows — hardening `os.fchmod` yang POSIX-only sekarang diguard per platform, dengan regression test untuk platform tanpa `fchmod` ([#561](https://github.com/HKUDS/Vibe-Trading/pull/561), terima kasih @CRui5in).

- **2026-07-15** 🧮 **Correctness backtest + core Portfolio Studio**: convergence pass 10 PR membuat rebalance causal dan order-independent, mengenakan terminal close cost, melaporkan turnover dari fill, menegakkan exposure cap, serta menjaga validation output tetap finite dan strict ([#530](https://github.com/HKUDS/Vibe-Trading/pull/530)/[#531](https://github.com/HKUDS/Vibe-Trading/pull/531)/[#532](https://github.com/HKUDS/Vibe-Trading/pull/532)/[#540](https://github.com/HKUDS/Vibe-Trading/pull/540)). Chart sekarang menggunakan kembali data source nyata milik run, repeatable market query tidak lagi dibuang, dan load `.env` merefresh cached config ([#535](https://github.com/HKUDS/Vibe-Trading/pull/535)/[#544](https://github.com/HKUDS/Vibe-Trading/pull/544)/[#554](https://github.com/HKUDS/Vibe-Trading/pull/554)). Portfolio Studio [#456](https://github.com/HKUDS/Vibe-Trading/issues/456) dan config bug [#541](https://github.com/HKUDS/Vibe-Trading/issues/541) ditutup; provider fix [#528](https://github.com/HKUDS/Vibe-Trading/issues/528)/[#529](https://github.com/HKUDS/Vibe-Trading/issues/529) juga selesai. Terima kasih @YZY0108, @santhreal, @Robin1987China, @xkam7ar, @Marnie0415, dan @marichu99.

- **2026-07-14** 🌉 **Market data Longbridge + transport MCP modern + reliability provider**: Longbridge bergabung ke layer fallback historical-data dengan credential yang key-gated, pemisahan date-window, strict completeness check, dan dependency SDK opt-in; empat tool flow China-market mendapat fallback Tushare yang diverifikasi, dan negative final equity tidak lagi membuat metric backtest crash. Server MCP sekarang mendukung Streamable HTTP, `write_file` aman melakukan recovery terhadap argumen path yang alias atau hilang, update hypothesis menolak field unsupported, dan request Correlation diautentikasi. NVIDIA NIM sekarang menjadi first-class provider di Web Settings dan kedua path onboarding CLI, dengan compatibility User-Agent berversi untuk menangani laporan 403; Web Settings sekarang menulis ke canonical `~/.vibe-trading/.env`, memigrasikan legacy config, dan melaporkan permission failure dengan jelas, memperbaiki DeepSeek save-time 500 ([#534](https://github.com/HKUDS/Vibe-Trading/pull/534), menutup [#516](https://github.com/HKUDS/Vibe-Trading/issues/516)/[#524](https://github.com/HKUDS/Vibe-Trading/issues/524); [#528](https://github.com/HKUDS/Vibe-Trading/issues/528)/[#529](https://github.com/HKUDS/Vibe-Trading/issues/529)). Terima kasih @fanfpy, @asahikiko, @santhreal, @sTunnaSu, @abhishekjaisinghani, @huangcheng, @ShiroKSH, @Meru143, @DIEGOD79, dan @not-knope atas code, report, dan diagnosis.

- **2026-07-13** 🔒 **Security hardening: seluruh 10 temuan external audit ditutup + batch contributor**: setiap temuan dari external security audit 2026-07-10 (issue [#476](https://github.com/HKUDS/Vibe-Trading/issues/476), discussion [#468](https://github.com/HKUDS/Vibe-Trading/discussions/468)) sekarang sudah ditangani di `main` — rebuild Docker multi-stage dengan image digest-pinned, backtest sandbox yang diperkeras AST untuk memblokir network/subprocess/eval/os.environ/unsafe-open (termasuk di dalam nested function body), short-lived single-use SSE auth ticket, Compose yang diharden (read-only rootfs, capability dibuang, resource limit), auth + rate limiting pada `/correlation`, security header, dependency hash-locked, dan lainnya. Juga digabungkan: **TAP mode** opt-in untuk isolasi key Alpaca ([#377](https://github.com/HKUDS/Vibe-Trading/pull/377), terima kasih @0xZKnw), realized portfolio turnover ditampilkan di metric backtest ([#478](https://github.com/HKUDS/Vibe-Trading/pull/478), terima kasih @Robin1987China), factor akademik **Frazzini-Pedersen betting-against-beta** (Alpha Zoo → 461, [#480](https://github.com/HKUDS/Vibe-Trading/pull/480), terima kasih @YogeshModi24), fix look-ahead-bias di seluruh 5 portfolio optimizer ([#487](https://github.com/HKUDS/Vibe-Trading/pull/487), terima kasih @YZY0108), dan dua fix preflight/provider-config ([#479](https://github.com/HKUDS/Vibe-Trading/pull/479)/[#484](https://github.com/HKUDS/Vibe-Trading/pull/484), menutup [#477](https://github.com/HKUDS/Vibe-Trading/issues/477)/[#482](https://github.com/HKUDS/Vibe-Trading/issues/482), terima kasih @ananaymital/@Bortlesboat).

- **2026-07-12** 🧪 **Strategy Development Manager + batch fix contributor**: skill baru `strategy-dev-manager` (#87) mengubah paper akademik dan broker research menjadi factor/strategy terdaftar dengan persistent artifact store dan automated IC/Sharpe decay monitoring — `sdm_register` / `sdm_status` / `sdm_decay_scan` menggerakkan lifecycle active → monitoring → decayed → disabled di bawah `~/.vibe-trading/` ([#457](https://github.com/HKUDS/Vibe-Trading/pull/457), menutup [#455](https://github.com/HKUDS/Vibe-Trading/issues/455), terima kasih @shadowinlife). Juga digabungkan: tab Correlation menerima ticker bare (`AAPL,SPY`) dan berjalan melalui seluruh loader fallback chain ([#472](https://github.com/HKUDS/Vibe-Trading/pull/472), menutup [#471](https://github.com/HKUDS/Vibe-Trading/issues/471), terima kasih @yxhuang), loader `local` menghormati interval yang diminta melalui OHLCV resampling ([#467](https://github.com/HKUDS/Vibe-Trading/pull/467), terima kasih @Shizoqua), history Binance USD-M perpetual hadir dengan routing eksplisit `BTC-USDT-PERP` + pemisahan execution/mark price sebagai slice pertama [#462](https://github.com/HKUDS/Vibe-Trading/issues/462) ([#470](https://github.com/HKUDS/Vibe-Trading/pull/470), terima kasih @honginp), import transport FastMCP sekarang bekerja untuk kedua layout module ([#469](https://github.com/HKUDS/Vibe-Trading/pull/469), terima kasih @roberttidball), dan Requesty tersedia sebagai provider LLM gateway kompatibel OpenAI ([#474](https://github.com/HKUDS/Vibe-Trading/pull/474), terima kasih @Thibaultjaigu).

- **2026-07-11** 🚀 **v0.1.11 dirilis** (`pip install -U vibe-trading-ai`): merangkum tiga minggu sejak 0.1.10 — backtesting equity India (NSE/BSE) sebagai first-class feature, layer fundamental factor PIT-safe (Alpha Zoo → 460), runtime IM channel 16 adapter, scheduled research end-to-end, optional premium data QVeris, serta batch contributor hari ini: optimizer yang turnover-aware ([#466](https://github.com/HKUDS/Vibe-Trading/pull/466), terima kasih @Robin1987China), tool vision `analyze_image` + pairing NapCat DM + fix read media IM ([#464](https://github.com/HKUDS/Vibe-Trading/pull/464)/[#463](https://github.com/HKUDS/Vibe-Trading/pull/463)/[#465](https://github.com/HKUDS/Vibe-Trading/issues/465), terima kasih @fei-moss), serialization Decimal Longbridge ([#459](https://github.com/HKUDS/Vibe-Trading/pull/459), terima kasih @fanfpy), dan guard count packaged-manifest ([#461](https://github.com/HKUDS/Vibe-Trading/pull/461), terima kasih @asahikiko). Detail lengkap: [CHANGELOG](CHANGELOG.md) · [catatan rilis](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.11).

- **2026-07-10** 🇮🇳 **Dukungan equity India (NSE/BSE) + centralized env config**: `IndiaEquityEngine` dedicated hadir — T+1 delivery, circuit band, serta stack biaya STT/stamp/exchange/SEBI/GST berbasis config — dengan routing simbol `.NS`/`.BO`, bridge data Shoonya/Dhan read-only opt-in, dan 255 factor alpha101/qlib158 yang diopt-in ke universe baru `equity_in` ([#305](https://github.com/HKUDS/Vibe-Trading/pull/305), terima kasih @muku314115). Environment variable sekarang mengalir melalui satu schema Pydantic `EnvConfig` dengan CI gate berbasis AST untuk mencegah sprawl `os.getenv` di masa depan ([#440](https://github.com/HKUDS/Vibe-Trading/pull/440), menutup [#438](https://github.com/HKUDS/Vibe-Trading/issues/438), terima kasih @shadowinlife). Juga: dialog second-confirmation sebelum commit mandate trading nyata plus unified error toast ([#453](https://github.com/HKUDS/Vibe-Trading/pull/453), terima kasih @wison1717-maker), test route scheduled-research ([#452](https://github.com/HKUDS/Vibe-Trading/pull/452), terima kasih @Robin1987China), dan GLM thinking model tidak lagi kehilangan reasoning stream pada provider zhipu ([#458](https://github.com/HKUDS/Vibe-Trading/issues/458)).

- **2026-07-09** 🧯 **Startup Docker tidak lagi terblokir + batch contributor provider/CLI**: startup Docker/server tidak lagi crash ketika iterasi route FastAPI melihat entry mirip included-router tanpa `path` ([#450](https://github.com/HKUDS/Vibe-Trading/issues/450), terima kasih @Penn-Live). Kami juga memasukkan queued quick-win fix dari contributor: signature loader `fetch()` sekarang sesuai protocol untuk OKX / Tushare / yfinance ([#437](https://github.com/HKUDS/Vibe-Trading/pull/437), terima kasih @shadowinlife), prompt resume CLI mempertahankan message pertama user ([#448](https://github.com/HKUDS/Vibe-Trading/pull/448), menutup [#447](https://github.com/HKUDS/Vibe-Trading/issues/447), terima kasih @morluto), default Codex OAuth menjadi `openai-codex/gpt-5.4` ([#446](https://github.com/HKUDS/Vibe-Trading/pull/446), terima kasih @morluto), Kimi for Coding tersedia sebagai provider terpisah ([#435](https://github.com/HKUDS/Vibe-Trading/pull/435), terima kasih @yxhuang), mapping provider opencode terhubung ([#444](https://github.com/HKUDS/Vibe-Trading/pull/444), terima kasih @imsankz), dan code fence referensi Tushare sekarang menulis `python` alih-alih `pyhton` ([#449](https://github.com/HKUDS/Vibe-Trading/pull/449), terima kasih @flash1234pku). Validation mencakup focused test server/CLI/provider/loader plus Docker build dan smoke `/health`.

- **2026-07-08** 💎 **Layer fundamental factor (Phase 1) + optional premium data QVeris + maintainer day**: fundamentals SEC yang PIT-safe sekarang masuk langsung ke daily factor panel — column panel `fund:*`, anchoring berdasarkan filed date dengan proteksi restatement dan YTD frame, serta 4 factor quality/value baru (registry sekarang 460 alpha). Data routing mendapat optional premium track: 18 source gratis tetap menjadi default, sedangkan QVeris membuka 63+ provider melalui Settings → QVeris atau `vibe-trading data mode paid` (lihat bagian QVeris di bawah). Juga: modularisasi `api_server` selesai (1.103 → 371 baris, [#424](https://github.com/HKUDS/Vibe-Trading/pull/424) menutup [#331](https://github.com/HKUDS/Vibe-Trading/issues/331), terima kasih @shadowinlife), `validation.json` backtest tidak lagi membutuhkan directory artifacts yang sudah ada sebelumnya ([#429](https://github.com/HKUDS/Vibe-Trading/pull/429), terima kasih @isaveall), error `--swarm-run` lebih jelas ([#428](https://github.com/HKUDS/Vibe-Trading/issues/428), terima kasih @isaveall), dan kami merevert governance stack yang merusak session chat ([#433](https://github.com/HKUDS/Vibe-Trading/issues/433), terima kasih @yxhuang atas diagnosis yang presisi).

- **2026-07-07** ✅ **Batch PR contributor**: queued contributor work untuk konfigurasi timeout IM channel digabungkan ([#413](https://github.com/HKUDS/Vibe-Trading/pull/413), terima kasih @SyntaxSawdust), bersama social preview Alpha Library dan tutorial pemula ([#396](https://github.com/HKUDS/Vibe-Trading/pull/396), [#393](https://github.com/HKUDS/Vibe-Trading/pull/393), terima kasih @kadaliao), skill / tool / committee preset value-investing ([#407](https://github.com/HKUDS/Vibe-Trading/pull/407), terima kasih @sambazhu), penanganan zero-sized order field di `trading_place_order` ([#417](https://github.com/HKUDS/Vibe-Trading/pull/417), terima kasih @irfanallana-oss), dan timestamp UTC timezone-aware di seluruh path session/API ([#397](https://github.com/HKUDS/Vibe-Trading/pull/397), terima kasih @mustafakamal88).

- **2026-07-06** 🧭 **Hardening preflight, slice API, dan fallback search CN**: provider preflight tidak lagi mengikuti redirect ([#404](https://github.com/HKUDS/Vibe-Trading/pull/404), menutup [#402](https://github.com/HKUDS/Vibe-Trading/issues/402), terima kasih @SyntaxSawdust), route API yang tersisa dipindahkan ke module terfokus ([#387](https://github.com/HKUDS/Vibe-Trading/pull/387), menggantikan [#383](https://github.com/HKUDS/Vibe-Trading/pull/383)-[#386](https://github.com/HKUDS/Vibe-Trading/pull/386), terima kasih @shadowinlife), dan fallback web-search CN sekarang mencakup Alibaba Cloud IQS ([#408](https://github.com/HKUDS/Vibe-Trading/pull/408), terima kasih @sambazhu). Maintainer cleanup menambahkan test no-network fallback dan cleanup whitespace EOF ([fbac74f](https://github.com/HKUDS/Vibe-Trading/commit/fbac74f77bfed58dd7fc23d0f001c29190b4b2b6)); CI `main` hijau ([run 28780619018](https://github.com/HKUDS/Vibe-Trading/actions/runs/28780619018)).

- **2026-07-05** ✅ **Queue PR contributor ditutup + baseline Windows hijau**: empat PR non-draft yang dipilih untuk maintainer pass hari ini digabungkan. Batch pull mootdx A-share sekarang membiarkan `KeyboardInterrupt` / `SystemExit` propagate alih-alih tertelan oleh bare `except` ([#399](https://github.com/HKUDS/Vibe-Trading/pull/399), menutup [#398](https://github.com/HKUDS/Vibe-Trading/issues/398), terima kasih @shadowinlife). Slice route Settings dan patched dependency floor sekarang digabungkan di bawah PR contributor aslinya ([#382](https://github.com/HKUDS/Vibe-Trading/pull/382), [#390](https://github.com/HKUDS/Vibe-Trading/pull/390), terima kasih @shadowinlife dan @aeonframework). Compatibility baseline Windows sekarang mengisolasi loader cache, membuat assertion OAuth cache platform-aware, melewati satu fork-only mock test di Windows, dan bypass proxy untuk fixture loopback MCP ([#401](https://github.com/HKUDS/Vibe-Trading/pull/401), terima kasih @Elfsa-Miranda). Validation: `4701 passed, 47 skipped`.

- **2026-07-04** 🧩 **Slice route API, tutorial docs, dan dependency floor**: route IM channel dan Settings dipindahkan keluar dari `api_server.py` ke `src/api/channels_routes.py` dan `src/api/settings_routes.py`, melanjutkan jalur modularisasi sempit [#331](https://github.com/HKUDS/Vibe-Trading/issues/331) dari contributor work ([#379](https://github.com/HKUDS/Vibe-Trading/pull/379), [#382](https://github.com/HKUDS/Vibe-Trading/pull/382), terima kasih @shadowinlife). Wiki mendapat tutorial pemula berbahasa Mandarin untuk pembaca non-finance ([#393](https://github.com/HKUDS/Vibe-Trading/pull/393), terima kasih @kadaliao), dan dependency floor sekarang menjaga Pillow / LangChain / LangGraph tetap pada track patched yang dapat diinstall ([#390](https://github.com/HKUDS/Vibe-Trading/pull/390), terima kasih @aeonframework).

- **2026-07-04** 🧹 **Cleanup timestamp UTC untuk path session dan API**: fix timestamp #395 diperketat sehingga timestamp session, goal, channel, dan API sekarang menghasilkan nilai UTC timezone-aware dalam format ISO eksplisit.

- **2026-07-03** 🛡️ **Refresh MCP Robinhood + modularisasi API + SSRF guard**: Robinhood Agentic Trading sekarang memakai nama tool MCP terbaru pada generic read, plumbing live-runner, seed read-only default, dan test mandate-gate, sementara startup interaktif menghormati urutan pencarian `.env` yang sama dengan provider loader (`~/.vibe-trading/.env` → `agent/.env` → `$CWD/.env`) ([#391](https://github.com/HKUDS/Vibe-Trading/pull/391), menutup [#381](https://github.com/HKUDS/Vibe-Trading/issues/381) dan [#380](https://github.com/HKUDS/Vibe-Trading/issues/380)). Route system (`/health`, `/correlation`, `/system/shutdown`, `/skills`, `/api`) dipindahkan ke `src/api/system_routes.py` sebagai slice modularisasi API sempit berikutnya ([#378](https://github.com/HKUDS/Vibe-Trading/pull/378), terima kasih @shadowinlife). Defense SSRF media channel sekarang menolak target CGNAT/mesh/non-global dan redirect media QQ ke internal sebelum fetch ([#389](https://github.com/HKUDS/Vibe-Trading/pull/389), terima kasih @hobostay).

- **2026-07-02** ⚡ **Akselerasi factor + boundary runtime yang lebih aman**: operator rolling factor yang hot sekarang memakai fast path `bottleneck`/NumPy, parallelism alpha bench menghindari pengiriman large-panel payload berulang ke worker, dan base equity math mendapat regression coverage ([#376](https://github.com/HKUDS/Vibe-Trading/pull/376), menutup [#339](https://github.com/HKUDS/Vibe-Trading/issues/339), original work dari [#342](https://github.com/HKUDS/Vibe-Trading/pull/342) oleh @shadowinlife). Route upload dan Shadow report dipindahkan keluar dari monolithic `api_server.py` sebagai slice modularisasi API sempit pertama sementara [#331](https://github.com/HKUDS/Vibe-Trading/issues/331) tetap terbuka ([#375](https://github.com/HKUDS/Vibe-Trading/pull/375), berdasarkan [#358](https://github.com/HKUDS/Vibe-Trading/pull/358), terima kasih @shadowinlife). Generated backtest sekarang hanya mewarisi subprocess environment dalam allowlist alih-alih seluruh secret surface parent ([#374](https://github.com/HKUDS/Vibe-Trading/pull/374), menutup [#332](https://github.com/HKUDS/Vibe-Trading/issues/332)), dan IM channel mendapat reset session `/new` plus pairing command yang case-insensitive ([#372](https://github.com/HKUDS/Vibe-Trading/pull/372), menutup [#371](https://github.com/HKUDS/Vibe-Trading/issues/371), terima kasih @shadowinlife).

- **2026-07-01** 🧹 **Polish security + cleanup tracker**: default development API/Docker/frontend diperketat, edge Settings channel dan `zh-CN` distabilkan, alert dependency/CSP frontend dibersihkan, dan item tracker WhatsApp + paper-trading yang stale ditutup ([#338](https://github.com/HKUDS/Vibe-Trading/pull/338), [#351](https://github.com/HKUDS/Vibe-Trading/pull/351), [#349](https://github.com/HKUDS/Vibe-Trading/pull/349), [#365](https://github.com/HKUDS/Vibe-Trading/pull/365), [#367](https://github.com/HKUDS/Vibe-Trading/pull/367), [#350](https://github.com/HKUDS/Vibe-Trading/pull/350), [#335](https://github.com/HKUDS/Vibe-Trading/pull/335), [#283](https://github.com/HKUDS/Vibe-Trading/issues/283)).

- **2026-06-30** 💬 **Runtime IM channel untuk delivery research**: Vibe-Trading sekarang dapat menghubungkan runtime agent session yang sama ke 16 built-in message adapter — WebSocket, Telegram, Slack, Discord, Matrix, WhatsApp, Signal, QQ/NapCat, WeChat/WeCom, Feishu/Lark, DingTalk, Teams, email, dan Mochat. CLI (`vibe-trading channels status/start/stop/login/pairing`), REST (`/channels/status`, `/channels/start`, `/channels/stop`, `/channels/pairing/command`), dan panel Web UI Settings mengekspos status, recovery hint, start/stop, dan sender pairing; adapter berbasis SDK tetap berada di balik extra seperti `vibe-trading-ai[telegram]` atau `vibe-trading-ai[channels]` ([#341](https://github.com/HKUDS/Vibe-Trading/pull/341)).

- **2026-06-29** 🛡️ **Live advisory safety + connector Trading 212 read-only + fix Windows/Gemini**: live order guard sekarang memiliki `PreTradeAdvisoryInterface` broker-agnostic yang opt-in untuk merekam advisory review tanpa melewati mandate gate, kill switch, atau audit trail ([#328](https://github.com/HKUDS/Vibe-Trading/pull/328), menutup [#317](https://github.com/HKUDS/Vibe-Trading/issues/317), terima kasih @shadowinlife). Trading 212 bergabung ke layer connector dengan dukungan read-only account, position, order, history, dan instrument metadata; `place_order` / `cancel_order` tetap hard-refuse sampai ada boundary struktural paper/live ([#321](https://github.com/HKUDS/Vibe-Trading/pull/321), menutup [#309](https://github.com/HKUDS/Vibe-Trading/issues/309), terima kasih @mvanhorn). Startup Windows menghindari crash pandas 3.0 `Timestamp` melalui constraint `<3.0.0` ([#329](https://github.com/HKUDS/Vibe-Trading/pull/329), menutup [#324](https://github.com/HKUDS/Vibe-Trading/issues/324), terima kasih @hannibal-lee); replay dict-history `thought_signature` Gemini diverifikasi/diperbaiki di `main` ([#318](https://github.com/HKUDS/Vibe-Trading/issues/318)); financial statement `.US` sekarang dirutekan ke SEC EDGAR alih-alih Eastmoney ([#325](https://github.com/HKUDS/Vibe-Trading/issues/325)); dan landing page Alpha Library mendapat hardening cache/date/selector/noscript/DNS-prefetch sementara follow-up CSP dan social-card yang lebih berat tetap dilacak ([#323](https://github.com/HKUDS/Vibe-Trading/issues/323)).

- **2026-06-28** 🧰 **Setup/dev cross-platform + hardening runtime dan file-tool**: `vibe-trading setup` dan `vibe-trading dev` sekarang menangani build TypeScript di Windows, meluncurkan backend dari cwd yang benar, memakai port Vite 5899, dan mematikan child process dengan bersih ([#292](https://github.com/HKUDS/Vibe-Trading/pull/292), terima kasih @digger-yu). Polling runtime status sekarang degrade alih-alih crash ([#322](https://github.com/HKUDS/Vibe-Trading/issues/322)); key cache OAuth MCP disanitasi ([#313](https://github.com/HKUDS/Vibe-Trading/issues/313)); default OpenAI dan validation `agent.json` Robinhood diperketat ([#319](https://github.com/HKUDS/Vibe-Trading/pull/319), [#320](https://github.com/HKUDS/Vibe-Trading/pull/320), terima kasih @mvanhorn); dan file tool mendapat read/write root terisolasi plus sandbox test yang lebih luas ([#299](https://github.com/HKUDS/Vibe-Trading/pull/299), terima kasih @skloxo).

- **2026-06-27** 🧯 **Ketahanan content-filter + cleanup contract fitur Shadow Account**: event-driven run dan swarm run sekarang melewati hit content-moderation LLM individual, memberi warning pada run card ketika rate filter tinggi, dan mengenali Gemini safety finish reason alih-alih membatalkan seluruh analysis ([#308](https://github.com/HKUDS/Vibe-Trading/pull/308), menutup [#307](https://github.com/HKUDS/Vibe-Trading/issues/307), terima kasih @shadowinlife). Extraction/codegen Shadow Account sekarang berbagi satu contract `PRICE_FEATURES` dan mempertahankan return bound empat desimal, mencegah drift rule/codegen dan hilangnya precision pada `prior_5d_return` ([#316](https://github.com/HKUDS/Vibe-Trading/pull/316), terima kasih @Robin1987China).

- **2026-06-26** 🎯 **Conditional entry Shadow Account + routing ETF/index/HK tushare**: rule Shadow Account hasil extraction sekarang membawa bound RSI / prior-return, sehingga SignalEngine yang dihasilkan masuk berdasarkan condition nyata (RSI dalam range, prior-return dalam range) alih-alih membuta mereplay holding cadence ([#314](https://github.com/HKUDS/Vibe-Trading/pull/314), mengikuti [#302](https://github.com/HKUDS/Vibe-Trading/pull/302), terima kasih @Robin1987China). Loader tushare juga merutekan ETF/LOF → `fund_daily()`, index → `index_daily()`, dan equity HK → `hk_daily()` alih-alih selalu memanggil `daily()` (yang diam-diam mengembalikan empty untuk non-stock), dengan warning empty-result + partial-fetch per simbol ([#315](https://github.com/HKUDS/Vibe-Trading/pull/315), menutup [#310](https://github.com/HKUDS/Vibe-Trading/issues/310), terima kasih @shadowinlife).

- **2026-06-25** 🧪 **Strict validation JSON + context agent yang lebih tenang**: standalone backtest validation sekarang menormalisasi nested `NaN` / `Infinity` sebelum menulis `artifacts/validation.json` atau stdout CLI, sehingga parser strict JSON tidak lagi gagal pada validation payload ([#306](https://github.com/HKUDS/Vibe-Trading/pull/306), terima kasih @gyx09212214-prog). Prompt agent juga menurunkan count data source saat ini dari loader registry, dan `_microcompact()` sekarang menunggu token pressure nyata alih-alih membersihkan tool result lama selama run pendek ([#296](https://github.com/HKUDS/Vibe-Trading/pull/296), menutup [#282](https://github.com/HKUDS/Vibe-Trading/issues/282), terima kasih @MarkfuGod).

- **2026-06-24** 🎯 **Price context Shadow Account + UI Mandarin reaktif + fix auth LAN**: extraction rule Shadow Account sekarang melihat entry context yang PIT-safe — `entry_rsi14` dan `prior_5d_return` diambil melalui loader registry as-of `buy_dt`, dengan graceful degradation ketika offline/tidak ada data ([#302](https://github.com/HKUDS/Vibe-Trading/pull/302), mengikuti [#295](https://github.com/HKUDS/Vibe-Trading/issues/295), terima kasih @Robin1987China). Panel utama Web UI sekarang memakai translation English / zh-CN yang reaktif di chart, chat, Alpha Library, Correlation, dan Run Detail ([#301](https://github.com/HKUDS/Vibe-Trading/pull/301), terima kasih @skloxo). Deployment Web UI remote same-origin dengan `API_AUTH_KEY` dapat post dan upload lagi setelah CSRF hardening, sementara origin cross-site yang mismatch tetap diblokir ([#304](https://github.com/HKUDS/Vibe-Trading/pull/304), terima kasih @Hinotoi-agent).

- **2026-06-23** 🛡️ **Hardening CSRF API lokal**: web page malicious tidak lagi dapat menggerakkan request cross-site yang unsafe (POST/PUT/DELETE) terhadap loopback API — CORS memblokir pembacaan response tetapi tidak side effect-nya, jadi trust loopback dev-mode sekarang menerapkan cross-site guard yang sudah ada pada unsafe method *sebelum* menghormati trust tersebut. Safe method dan upload CLI lokal / non-browser tidak terdampak ([#293](https://github.com/HKUDS/Vibe-Trading/pull/293), terima kasih @Hinotoi-agent).

- **2026-06-22** 🔧 **Fix OAuth live-authorize + fix headline Alpha Zoo**: `connector authorize` sekarang menjaga OAuth handshake tetap terbuka selama sign-in broker yang dapat memakan beberapa menit (dapat diatur melalui `VIBE_LIVE_AUTHORIZE_TIMEOUT_SECONDS`) dan tidak lagi membuat callback server pesaing saat retry, sehingga token benar-benar tersimpan ([#281](https://github.com/HKUDS/Vibe-Trading/pull/281), menutup [#259](https://github.com/HKUDS/Vibe-Trading/issues/259), terima kasih @Robin1987China). Halaman Alpha Zoo tidak lagi mencetak alpha count dua kali ([#287](https://github.com/HKUDS/Vibe-Trading/pull/287), menutup [#286](https://github.com/HKUDS/Vibe-Trading/issues/286), terima kasih @digger-yu). Scheduled research juga mendapat docs penggunaan end-to-end ([#288](https://github.com/HKUDS/Vibe-Trading/pull/288)).

- **2026-06-21** ⏰ **Executor scheduled-research + Reports library + attribution pasca-backtest**: scheduled research sekarang berjalan **end-to-end** — background executor default-off (`VIBE_TRADING_ENABLE_SCHEDULER`) menjalankan interval/cron job yang due melalui session runtime ([#278](https://github.com/HKUDS/Vibe-Trading/pull/278), terima kasih @mvanhorn, menutup [#254](https://github.com/HKUDS/Vibe-Trading/issues/254)). Halaman **`/reports` Run Library** baru menampilkan, mencari, dan memfilter run yang layak report dengan link ke Run Detail + Compare ([#224](https://github.com/HKUDS/Vibe-Trading/pull/224), terima kasih @LemonCANDY42). Setelah setiap backtest, agent sekarang menjalankan **layered attribution** — winner/loser pada level trade, beta regression, market-regime analysis, dan Monte Carlo permutation test, semuanya digate oleh availability serta routing data ([#280](https://github.com/HKUDS/Vibe-Trading/pull/280), terima kasih @shadowinlife).

- **2026-06-20** 🔬 **Loop Research Autopilot selesai (Phase 3) + OHLC integrity guard loader + 4 alpha akademik**: **Research Autopilot** sekarang menjalankan **hypothesis → signal-engine → backtest** end-to-end — `scaffold_signal_engine` menulis engine yang sesuai contract dan `link_autopilot_backtest` memberi run metric kembali ke hypothesis (**68 tool**) ([#267](https://github.com/HKUDS/Vibe-Trading/pull/267)). **OHLC sanity check** struktural membuang dirty bar (`high < low`, non-positive price, bracketing buruk) secara centralized pada loader boundary, melindungi setiap data source ([#274](https://github.com/HKUDS/Vibe-Trading/pull/274), terima kasih @Shizoqua). Keluarga **academic alpha tumbuh 6 → 10** — Jegadeesh reversal, George-Hwang 52-week-high, Amihud illiquidity, Harvey-Siddique skew (**456 factor**) ([#277](https://github.com/HKUDS/Vibe-Trading/pull/277), terima kasih @Robin1987China).

- **2026-06-19** 🚀 **v0.1.10 — Global data layer**: market-data source tumbuh 10 → 18 (gratis **Eastmoney / Sina / Stooq / Yahoo** + key-gated **Finnhub / Alpha Vantage / Tiingo / FMP**, fallback berisiko ban) plus **18 data tool read-only** (fund flow, dragon-tiger, northbound, margin, block trade, SEC EDGAR + XBRL, financials, options chain, full-market screening…) untuk A-share / US / HK, semuanya melalui MCP. Juga merangkum semua sejak 0.1.9 — 10 connector broker, `alpha compare`, overhaul reliability provider, dan data cache opt-in. `pip install -U vibe-trading-ai`

- **2026-06-18** 🔬 **Research Autopilot Phase 1 + loader Data Bridge lokal + security notice Discord**: `run_research_autopilot` + `generate_backtest_config` baru menghubungkan **Hypothesis → Research Goal → backtest** end-to-end (sekarang **50 tool**), dan loader **`local`** membaca OHLCV langsung dari file **CSV / Parquet / DuckDB** Anda sendiri ([#260](https://github.com/HKUDS/Vibe-Trading/pull/260), [#252](https://github.com/HKUDS/Vibe-Trading/pull/252), terima kasih @Robin1987China), bersama parsing tool-call DeepSeek `DSML` dan gelombang hardening identifier-containment. ⚠️ **Keamanan:** invite Discord community lama sekarang mengarah ke server yang tidak kami kontrol dan menjalankan scam phishing "verification" wallet Collab.Land palsu — link tersebut dihapus di semua tempat; **satu-satunya** Discord resmi adalah server HKUDS ([discord.gg/6TdQnT5xcF](https://discord.gg/6TdQnT5xcF)), dan kami tidak akan pernah meminta Anda menghubungkan wallet.

- **2026-06-17** 🧩 **Kompatibilitas install + fix provider Opus/Kimi**: baseline `pip install vibe-trading-ai` tidak lagi menarik dependency chain optional `pyharmonics` / `ta`; harmonic detection sekarang berada di balik `vibe-trading-ai[harmonic]` sementara bundled detector tetap tersedia ([#250](https://github.com/HKUDS/Vibe-Trading/pull/250), menutup [#249](https://github.com/HKUDS/Vibe-Trading/issues/249)). Agent loop juga menghindari assistant-prefill handoff message yang ditolak Opus 4.8+, dan Kimi/Moonshot dapat mengoverride `User-Agent` client melalui `MOONSHOT_USER_AGENT` ([#248](https://github.com/HKUDS/Vibe-Trading/pull/248), menutup [#246](https://github.com/HKUDS/Vibe-Trading/issues/246) dan [#204](https://github.com/HKUDS/Vibe-Trading/issues/204)); follow-up test sekarang mencakup langsung path handoff background-result dan auto-compact ([#251](https://github.com/HKUDS/Vibe-Trading/pull/251)).

- **2026-06-16** 🛡️ **Hardening security/API + alias GLM/Zhipu**: write Settings membutuhkan auth ketika dikonfigurasi ([#245](https://github.com/HKUDS/Vibe-Trading/pull/245)); tool API yang dapat menjalankan shell membutuhkan opt-in eksplisit `VIBE_TRADING_ENABLE_SHELL_TOOLS=1` ([#243](https://github.com/HKUDS/Vibe-Trading/pull/243)); local shutdown membutuhkan auth ketika API key dikonfigurasi ([#241](https://github.com/HKUDS/Vibe-Trading/pull/241)); dan host tidak tepercaya yang terlihat seperti loopback ditolak alih-alih dianggap lokal ([#242](https://github.com/HKUDS/Vibe-Trading/pull/242)). Edge runtime juga dibersihkan: Web chat mensinkronkan completed attempt ([#236](https://github.com/HKUDS/Vibe-Trading/pull/236)), run card menghasilkan strict JSON untuk metric non-finite ([#238](https://github.com/HKUDS/Vibe-Trading/pull/238)), `RSSHUB_TIMEOUT_S` / `RSSHUB_FETCH_BUDGET_S` malformed fallback dengan aman ([#240](https://github.com/HKUDS/Vibe-Trading/pull/240)), dan retry fallback ddgs mendapat regression coverage ([#239](https://github.com/HKUDS/Vibe-Trading/pull/239)). GLM/Zhipu sekarang menjadi alias provider first-class dengan inference nama model ([#247](https://github.com/HKUDS/Vibe-Trading/pull/247), menutup [#237](https://github.com/HKUDS/Vibe-Trading/issues/237)).

- **2026-06-15** 🧭 **Ketahanan web-search + fix kontinuitas run Web UI**: `web_search` tidak lagi gagal ketika satu engine terkena rate limit — sekarang beberapa engine gratis tanpa key ditanya secara berurutan (DuckDuckGo, Google, Bing, Brave, Mojeek, Yahoo) dengan retry/backoff, "no results" diperlakukan sebagai jawaban kosong bukan error, dan ketika semua engine throttled sistem mengembalikan pesan actionable alih-alih sekadar ❌ (override daftar engine melalui `VIBE_TRADING_SEARCH_BACKENDS`) ([#232](https://github.com/HKUDS/Vibe-Trading/pull/232), menutup [#231](https://github.com/HKUDS/Vibe-Trading/issues/231), terima kasih @Ethan-sun01). Di Web UI, berpindah page saat run berlangsung tidak lagi membuatnya freeze — chat resubscribe ke live stream dan mereplay progress yang terlewat saat kembali ([#234](https://github.com/HKUDS/Vibe-Trading/pull/234)) — dan tombol Stop sekarang bekerja di tengah stream serta di antara tool, bukan hanya pada boundary iteration ([#235](https://github.com/HKUDS/Vibe-Trading/pull/235)), menutup kedua bagian [#229](https://github.com/HKUDS/Vibe-Trading/issues/229) (terima kasih @kalkinj). Loader baostock juga menerima code native `sh.601398` / `sz.000001` selain format tushare `601398.SH` ([#230](https://github.com/HKUDS/Vibe-Trading/pull/230), terima kasih @bhlt).

- **2026-06-14** 📊 **Usage token per run + chart Run Detail progresif**: setiap agent run sekarang mempersist usage token yang dilaporkan provider sebagai `llm_usage.json` scoped per run — provider/model, aggregate total, dan count per iteration — ditampilkan secara additive pada `/runs/{id}`, sehingga biaya token run yang selesai tetap auditable setelah live stream hilang (hanya data dari provider; tanpa capture prompt/content dan tanpa estimasi harga) ([#223](https://github.com/HKUDS/Vibe-Trading/pull/223), terima kasih @LemonCANDY42). Halaman Run Detail tidak lagi memuat candlestick setiap simbol di awal: response default `/runs/{id}` tidak berubah, tetapi UI sekarang merender summary run lebih dulu lalu memuat chart setiap simbol on demand melalui mode opt-in `?chart_payload=summary` / `?chart_symbol=`, dengan loading state per simbol dan control load-all-with-progress ([#225](https://github.com/HKUDS/Vibe-Trading/pull/225), terima kasih @LemonCANDY42). Dua fix loader menutup cycle: boundary `end` eksklusif yfinance tidak lagi membuang trading day terakhir yang diminta — download sekarang meneruskan `end + 1 day` sementara cache key tetap memakai range asli ([#226](https://github.com/HKUDS/Vibe-Trading/pull/226), terima kasih @gyx09212214-prog) — dan nilai `CCXT_TIMEOUT_MS` / `OKX_TIMEOUT_S` malformed sekarang memberi warning lalu fallback ke default alih-alih raise saat import dan memblokir startup ([#227](https://github.com/HKUDS/Vibe-Trading/pull/227), terima kasih @gyx09212214-prog).

- **2026-06-13** ↩️ **Resume session lama berdasarkan ID dari CLI**: CLI interaktif sekarang mencetak session-id saat keluar, bersama hint copy-paste `vibe-trading resume <session-id>` — sehingga mencari trace run yang selesai tidak lagi berarti menebak folder terbaru di `agent/sessions/` berdasarkan timestamp. Subcommand baru `vibe-trading resume <session-id>` membuka kembali exact session tersebut dan mereplay turn terbaru ke loop; id yang tidak dikenal fail fast alih-alih diam-diam memulai session kosong ([#218](https://github.com/HKUDS/Vibe-Trading/pull/218), terima kasih @zwrong).

- **2026-06-12** 🩺 **Overhaul reliability provider — DeepSeek hang, akses Kimi, liveness streaming**: sekumpulan laporan provider — run DeepSeek stuck pada "Agent is working…" ([#208](https://github.com/HKUDS/Vibe-Trading/issues/208), terima kasih @XYWOX), `reached max iterations` yang menutupi empty response model ([#203](https://github.com/HKUDS/Vibe-Trading/issues/203), terima kasih @mojianliang), UI tidak pernah recovery setelah stall ([#195](https://github.com/HKUDS/Vibe-Trading/issues/195), terima kasih @mafia23), dan Kimi menolak client ([#204](https://github.com/HKUDS/Vibe-Trading/issues/204), terima kasih @liao497) — ternyata memiliki satu root cause: setiap provider kompatibel OpenAI berjalan melalui satu shim yang menerapkan quirk DeepSeek/Kimi/Gemini secara global dan diam-diam menelan failure stream. Behaviour spesifik provider sekarang berada di **capability layer** eksplisit — capture/replay reasoning, thought signature Gemini, `User-Agent` Kimi, reasoning body OpenRouter masing-masing digate hanya ke provider sendiri agar tidak saling mengontaminasi. Stream yang hanya berisi reasoning menampilkan indicator live **"Reasoning…"** alih-alih dead air; failure stream raise `provider_stream_error` kontekstual dengan satu retry otomatis untuk transient reset (4xx deterministic fail fast) alih-alih diam-diam fallback ke call non-streaming lambat; empty model response dilaporkan sebagai `empty_model_response` alih-alih "max iterations"; heartbeat SSE tidak lagi merusak reconnect replay; dan read-only tool yang stuck timeout alih-alih tersembunyi selamanya di balik heartbeat. Tool baru **`vibe-trading provider doctor`** mencetak snapshot provider/model/package/proxy yang sudah diredaaksi untuk triage environment-side hang dalam satu command. Pengguna DeepSeek dapat opt-in ke official native adapter dengan `pip install "vibe-trading-ai[deepseek]"`, dan requirement `temperature=1` untuk kimi-k2.x diterapkan otomatis — path Kimi diverifikasi end-to-end terhadap live API (tool call + strict multi-turn reasoning replay pada `kimi-k2.6`).

- **2026-06-11** 🐝 **Swarm worker sekarang mengambil market data melalui loader layer**: run investment-committee pada NVDA mengungkap rantai gap — worker menulis script yfinance ad-hoc, mempercayai latest bar malformed (volume ada, OHLC kosong), membocorkan `NaN` ke JSON non-strict, dan continuation prompt tanpa context dirutekan ulang ke preset yang salah ([#198](https://github.com/HKUDS/Vibe-Trading/issues/198), terima kasih @BillDin atas diagnosis luar biasa sekaligus kedua fix). Swarm worker sekarang mendapat tool lokal `get_market_data` yang didukung normalized loader registry yang sama dengan MCP — strict JSON, float non-finite terserialize sebagai `null` — dihubungkan ke **setiap preset market-data** (21 worker di 13 preset) dengan prompt policy yang mengarahkan pekerjaan OHLCV agar tool-first ([#199](https://github.com/HKUDS/Vibe-Trading/pull/199)); `run_swarm` menerima `preset_name` eksplisit dan menolak continuation fragment ambiguous alih-alih diam-diam fallback ke `equity_research_team` ([#200](https://github.com/HKUDS/Vibe-Trading/pull/200)). Grounding juga lebih pintar: ticker US bare seperti `NVDA` dalam swarm prompt dipromosikan menjadi `NVDA.US` (dengan stopword guard), sehingga worker memulai dari pre-fetched price yang authoritative. Tool tersebut juga bergabung ke main agent registry — sekarang **48 tool**. Juga: **data Docker Anda sekarang bertahan saat update** — persistent memory, session search index, user-created skill, shadow account, dan broker config hidup di named volume, sehingga `docker compose up --build` tidak lagi menghapusnya ([#197](https://github.com/HKUDS/Vibe-Trading/issues/197), terima kasih @FlyerJ).

- **2026-06-10** 🐳 **Docker dapat menjangkau Ollama di host secara default**: di dalam container, `localhost` adalah container itu sendiri, sehingga `OLLAMA_BASE_URL=http://localhost:11434` bawaan gagal pada LLM preflight untuk setiap setup Ollama melalui Docker. `docker-compose.yml` sekarang default ke `http://host.docker.internal:11434` (export `OLLAMA_BASE_URL` untuk menunjuk tempat lain) dan menambahkan mapping `extra_hosts` `host-gateway` agar file yang sama bekerja di Linux maupun Docker Desktop ([#196](https://github.com/HKUDS/Vibe-Trading/pull/196), terima kasih @ShahNewazKhan).

- **2026-06-09** 🔑 **Error lebih jelas ketika Web UI dibuka dari mesin lain**: mengakses chat dari client non-loopback (mesin lain, VM host, ponsel di LAN) tanpa `API_AUTH_KEY` sebelumnya mengembalikan `403` pada setiap endpoint sensitif — mengirim message, listing session, live status — tetapi chat hanya menampilkan generic "Failed to send message, please retry." Path send sekarang menampilkan alasan sebenarnya — *"Remote API access requires an API key. Add it in Settings, or run the backend on localhost for local-only use."* — dan setup Web UI di README menjelaskan aturan localhost-vs-LAN beserta tiga solusi (akses melalui `localhost` pada mesin yang sama; set `API_AUTH_KEY` dan masukkan sekali di Settings; atau `VIBE_TRADING_TRUST_DOCKER_LOOPBACK=1` untuk host gateway Docker Desktop) ([#191](https://github.com/HKUDS/Vibe-Trading/issues/191), terima kasih @mafia23).

- **2026-06-08** 🔧 **Fix multi-turn tool-calling Gemini 3.x**: ini menyelesaikan fix thinking model Gemini 3.x. Round-trip 6/05 ([#176](https://github.com/HKUDS/Vibe-Trading/pull/176)) hanya mencakup history in-memory, tetapi agent loop nyata mereplay history sebagai dict format OpenAI, tempat LangChain membuang `thought_signature` per tool-call sebelum request dibangun — sehingga multi-turn tool calling masih menghasilkan 400 `missing thought_signature`. Sekarang signature dipasang kembali di satu chokepoint `_convert_input` yang dilalui `invoke` maupun `stream` (termasuk parallel call, tempat hanya call pertama dari N yang ditandatangani) ([#184](https://github.com/HKUDS/Vibe-Trading/pull/184), terima kasih @ngoanpv).

- **2026-06-07** 🐝 **Live swarm status di timeline chat**: ketika agent meluncurkan multi-agent swarm (investment committee, quant desk, risk committee, …), chat sekarang merender **status card** inline yang menstream state setiap worker — waiting / running / done / failed / blocked / retrying — secara real time, dengan visibility per-agent yang sama seperti standalone swarm dashboard. Event runtime dijembatani ke session SSE stream tanpa mengubah API `/swarm/runs` yang sudah ada, dan card yang selesai direhydrate dari final result `run_swarm` saat reconnect atau history replay ([#188](https://github.com/HKUDS/Vibe-Trading/pull/188), terima kasih @BillDin). Routing preset juga diperjelas: preset yang disebut eksplisit (mis. `investment_committee`, dengan atau tanpa underscore) sekarang menang atas keyword scoring, dan keyword derivatives bare `IV` tidak lagi false-match di dalam kata biasa seperti "g**iv**en" ([#189](https://github.com/HKUDS/Vibe-Trading/pull/189), terima kasih @BillDin).

- **2026-06-06** ⚖️ **Alpha compare — head-to-head di CLI, Web UI, REST & agent**: `alpha compare` baru membenchmark shortlist Alpha Zoo pilihan Anda satu sama lain pada universe dan period, lalu meranking berdasarkan IC mean/std, IR, IC-positive ratio, atau sample count — masing-masing disertai gap terhadap leader. Berbeda dari full-zoo bench, fitur ini mengevaluasi **hanya alpha yang Anda sebutkan** (filter subset baru `run_bench(only=…)`), sehingga membandingkan tiga alpha tidak lagi menscore seluruh 191 alpha di zoo. Satu core bersama mendukung semua surface: `vibe-trading alpha compare <id1> <id2> … --sort ir` (CLI), **Compare view** di Web UI Alpha Zoo (centang alpha di catalogue → one-click compare dengan streamed ranking table), `POST /alpha/compare` + SSE (REST), dan agent tool read-only `alpha_compare` (**sekarang 47 tool**).

- **2026-06-05** 🇮🇳 **Connector Dhan + Shoonya (India) — total 10 broker**: layer trading connector-first menambahkan **Dhan** dan **Shoonya** untuk market India (equity NSE/BSE + F&O), membawa total menjadi sepuluh broker. Keduanya **paper + read-only** — seperti Longbridge, API mereka tidak menyediakan runtime discriminator paper/live, sehingga `place_order` / `cancel_order` melakukan hard-refuse untuk config non-paper sejak baris pertama (rule: broker tanpa structural paper/live guard dibatasi pada paper + read-only) ([#181](https://github.com/HKUDS/Vibe-Trading/pull/181), menutup [#174](https://github.com/HKUDS/Vibe-Trading/issues/174)). Cycle ini juga memperbaiki **thinking model Gemini 2.5 / 3.x**: `thoughtSignature` per tool-call sekarang round-trip melalui path kompatibel OpenAI, sehingga multi-turn function calling tidak lagi gagal dengan `INVALID_ARGUMENT` ([#176](https://github.com/HKUDS/Vibe-Trading/pull/176), menutup [#170](https://github.com/HKUDS/Vibe-Trading/issues/170), terima kasih @mvanhorn & @jliu6789). Docstring Mandarin hadir pada seluruh **452 factor Alpha Zoo** ([#180](https://github.com/HKUDS/Vibe-Trading/pull/180), terima kasih @LeeCQiang), dan **frontend test suite (197 vitest test)** plus test security backend auth / path-traversal / CORS bergabung ke CI ([#175](https://github.com/HKUDS/Vibe-Trading/pull/175), terima kasih @sambazhu).

- **2026-06-04** 🗃️ **Local data cache opt-in untuk seluruh 7 data source**: switch baru `VIBE_TRADING_DATA_CACHE` memungkinkan setiap loader backtest — tushare, okx, ccxt, akshare, mootdx, yfinance, futu — mengcache settled historical bar di bawah `~/.vibe-trading/cache` (user home, bukan repo), sehingga backtest berulang, long-horizon, dan cross-market dapat melewati network serta menghindari provider rate limit. Off secara default. Loader batch dan connection (yfinance, futu) melewati bulk download / koneksi FutuOpenD sepenuhnya ketika cache hit lengkap, staleness guard tidak pernah mengcache range yang berakhir hari ini (last bar-nya masih terbentuk), dan cached frame round-trip byte-identical dengan fresh fetch ([#177](https://github.com/HKUDS/Vibe-Trading/pull/177), terima kasih @mvanhorn). Contributor guide baru untuk PR yang dibantu AI / automation juga hadir, memetakan safe local check dan surface broker/MCP/credential berisiko tinggi ([#173](https://github.com/HKUDS/Vibe-Trading/pull/173)).

- **2026-06-03** 🧹 **Community triage + trace correlation**: entry trace tool-call sekarang membawa `call_id` asal, sehingga `tool_result` dapat dicocokkan kembali ke `tool_call` ketika mereplay run trace — preview argumen tetap ditruncate agar file trace kecil ([#168](https://github.com/HKUDS/Vibe-Trading/pull/168), terima kasih @zwrong). Comment source tidak lagi menunjuk ke path docs internal-only yang tidak dapat ditemukan contributor eksternal ([#166](https://github.com/HKUDS/Vibe-Trading/issues/166), terima kasih @jaleelpersonal). Juga diperjelas bahwa warning resolver `langchain-community` saat install hanyalah notice leftover-package yang harmless, bukan failure ([#167](https://github.com/HKUDS/Vibe-Trading/issues/167)), dan round-trip `thoughtSignature` Gemini 2.5/3.0 untuk function call discoping sebagai task `help wanted` dengan full fix plan ([#170](https://github.com/HKUDS/Vibe-Trading/issues/170), terima kasih @jliu6789).

- **2026-06-02** 🔌 **Enam connector broker baru (Tiger / Longbridge / Alpaca / OKX / Binance / Futu)**: layer trading connector-first mendapat transport direct-SDK selain IBKR (lokal) dan Robinhood (MCP). Setiap connector mengekspos read-only account / position / order / quote / history **plus penempatan order pada paper account** — sehingga strategi dapat diuji di paper account broker-broker tersebut. Lima di antaranya (Tiger, Alpaca, OKX, Binance, Futu) juga mendukung **bounded, mandate-gated order placement** di balik safety model yang sama seperti Robinhood: mandate yang dicommit user (symbol universe / order size / exposure / leverage / daily cap), filesystem kill switch, pre-trade gate fail-closed, dan full audit ledger. **Longbridge hanya paper + read-only** (API-nya tidak menyediakan runtime discriminator paper/live). Setiap perbedaan paper/live dijaga secara struktural per broker — format account-id, pemisahan host, demo flag, atau trade environment. Tool baru `trading_place_order` / `trading_cancel_order`; asset class HK dan A-share ditambahkan ke mandate universe. Eksperimental / gunakan dengan risiko Anda sendiri.

- **2026-06-01** 🚀 **v0.1.9 dirilis** (`pip install -U vibe-trading-ai`): merangkum semua sejak 0.1.8. Profile broker connector-first (IBKR lokal read-only TWS / IB Gateway + Robinhood Agentic Trading di balik OAuth, committed mandate, order guard, audit ledger, dan instant halt). Runtime Research Goal di CLI / REST / MCP / Web. Satu swarm pass — live reconcile + MCP keepalive, tool MCP worker yang dikonfigurasi operator, strict alpha-bench random control, dan `retry_run` baru untuk meluncurkan ulang run failed/stale (**sekarang 36 MCP tool**). Refactor package `agent/cli/` dengan terminal UI yang direfresh, loader A-share `mootdx` tanpa token, dan robustness pass pada backtest / agent loop / session. `--version` sekarang selalu cocok dengan package yang terinstall, memperbaiki drift 0.1.8 ([#156](https://github.com/HKUDS/Vibe-Trading/issues/156)).

- **2026-05-31** 🔌 **Arsitektur broker connector-first (IBKR + Robinhood)**: akses trading sekarang dimulai dari profile connector yang dapat dipilih alih-alih entry point broker/live terpisah. `vibe-trading connector list/use/check/account/positions/orders/quote/history` dan tool MCP `trading_*` berbagi profile terpilih yang sama, dengan paper/live sebagai atribut connector. IBKR dapat langsung digunakan melalui profile TWS / IB Gateway lokal read-only, sedangkan path MCP remote resmi IBKR diseed sebagai probe OAuth `mcp.read` sampai nama read tool stabil tersedia. Robinhood Agentic Trading tetap menjadi bounded live MCP connector di balik OAuth, committed mandate, order guard, audit ledger, dan instant halt.

- **2026-05-30** 🧰 **Robustness pass — backtest, agent loop, session**: signal engine yang dihasilkan LLM sekarang melewati pre-flight interface validation sebelum instantiation, menangkap circular self-import, `generate()` yang hilang, argumen `__init__` tanpa default, dan return type salah dengan actionable JSON error alih-alih raw traceback ([#149](https://github.com/HKUDS/Vibe-Trading/pull/149)); follow-up merutekan source-level AST validation error melalui clean JSON envelope yang sama. Agent loop tidak lagi membakar seluruh 50 iteration hingga status `failed` tanpa output — sekarang meniru wrap-up nudge swarm worker pada 80% iteration budget dan membuang tool definition pada iteration terakhir untuk memaksa final text answer ([#148](https://github.com/HKUDS/Vibe-Trading/pull/148)), diguard agar hanya fire di tengah run sehingga tidak pernah menggantikan research-goal context. Write session message sekarang melakukan `flush + fsync` pada setiap append agar response AI mahal bertahan dari crash di tengah write, dan read path melewati line JSONL corrupt (melog 200 karakter pertama untuk recovery) alih-alih membuat seluruh endpoint `/messages` 500 ([#147](https://github.com/HKUDS/Vibe-Trading/pull/147)). Web composer juga memperbaiki handling IME Enter sehingga Enter yang mengonfirmasi composition tidak lagi submit di tengah kata ([#146](https://github.com/HKUDS/Vibe-Trading/pull/146)).

- **2026-05-29** 🔐 **Dukungan Robinhood Agentic Trading (opt-in, bounded autonomy)**: menambahkan dukungan untuk Robinhood Agentic Trading (remote MCP, OAuth). Off dan read-only secara default; agent hanya bertindak di dalam mandate yang dicommit user (simbol / order size / exposure / leverage / daily cap), dengan instant kill switch level filesystem, preemptive flatten, auto-expiry mandate, full audit ledger, dan persistent autonomous runner. Tidak ada custody dan tidak menjadi venue — broker menyimpan dana serta mengeksekusi; kami hanya merelay intent. Eksperimental / gunakan dengan risiko Anda sendiri.

- **2026-05-28** 🧪 **Safety swarm + strict alpha gate + worker MCP**: DAG swarm memblokir downstream task ketika upstream gagal ([#145](https://github.com/HKUDS/Vibe-Trading/pull/145)). `run_bench_strict()` baru menambahkan same-universe random control + OOS split untuk menangkap factor yang sebenarnya hanya mengikuti market beta ([#143](https://github.com/HKUDS/Vibe-Trading/pull/143), terima kasih @Soli22de). Swarm worker dapat memanggil external MCP server yang dikonfigurasi operator, dengan trust boundary yang dipin ([#142](https://github.com/HKUDS/Vibe-Trading/pull/142), terima kasih @shadowinlife).

- **2026-05-27** 📊 **Data source A-share mootdx + polish output**: loader baru `mootdx` berbicara protocol TCP native 通达信 untuk OHLCV A-share (tanpa auth, tanpa IP rate-limit, daily + intraday dengan pagination walk-back 25 page), ditempatkan di antara tushare dan akshare pada fallback chain ([#107](https://github.com/HKUDS/Vibe-Trading/issues/107)). Loader CCXT sekarang membaca `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY` sehingga public data Binance/OKX bekerja dari network terbatas ([#126](https://github.com/HKUDS/Vibe-Trading/pull/126), terima kasih @ruok808). Rendering final answer juga menghapus separator horizontal full-width `---` yang mengganggu di CLI dan Web: system prompt sekarang mengarahkan agent ke markdown table dan heading `##`, renderer CLI menghapus standalone HR sebagai defense-in-depth, dan chat bubble menyembunyikan `<hr>` yang masih lolos ([#139](https://github.com/HKUDS/Vibe-Trading/issues/139), terima kasih @sdwxm188).

- **2026-05-26** ✅ **Penutupan lifecycle Research Goal**: Goal mode sekarang berperilaku seperti task runner nyata: pembuatan goal dari Web UI membuat atau mengikat session lalu langsung mengirim kickoff turn; active goal dapat dilanjutkan, diedit, dibatalkan, dan diselesaikan dari Web/API/CLI/MCP; dan agent maju dari snapshot goal saat ini (criteria, evidence, claim, open item), bukan hanya original prompt. Goal yang sudah covered tetapi masih active sekarang masuk ke audit/status update alih-alih berhenti diam-diam, dengan regression coverage di backend, CLI, MCP, dan event frontend.

- **2026-05-25** 🧼 **Chat UI lebih bersih + workflow composer**: Web UI menjaga chat tetap fokus pada tindakan berikutnya: mode upload, swarm, dan research-goal sekarang berada di balik menu `+` composer alih-alih floating panel. Active context tampil di atas input sebagai chip ringkas, dan detail goal expand inline hanya saat dibutuhkan. UI juga menghapus custom i18n layer lama dan memakai direct English copy, membatasi Full Report card hanya untuk run yang layak report, serta memperkeras startup/status reporting local dev agar browser smoke test lebih andal.

- **2026-05-24** 🎯 **Runtime Research Goal**: menambahkan layer Research Goal scoped per session di backend, CLI, API/MCP, SSE, dan Web UI. Goal mempersist claim, acceptance criteria, evidence row, budget, dan completion policy; agent tool dapat membuat goal dan melampirkan evidence; `/goal` memberi CLI direct entry point; REST/MCP mengekspos snapshot goal dan evidence write; SSE menjaga chat client tetap fresh. Follow-up audit fix mengunci verified evidence, memblokir risk tier live-trading melalui agent tool, menghubungkan goal buatan CLI ke turn berikutnya, membersihkan goal ledger saat session dihapus, mengaktifkan replay-all, dan memperbaiki race frontend lintas session.

- **2026-05-23** 🖥️ **Refresh CLI interaktif**: front door terminal sekarang dibuka dengan banner Vibe-Trading lebih besar, prompt divider lebih bersih, recap turn sebelumnya, timing pasca-run, dan activity rail bergaya Claude Code untuk live agent work. Tool call, fetch web/data, action bergaya shell, jawaban Markdown, dan pipe table dirender dalam transcript yang lebih mudah dibaca, sementara run piped atau non-TTY mempertahankan plain-text output untuk automation. Screenshot CLI yang digenerate sekarang diperlakukan sebagai artifact lokal alih-alih file docs yang dicommit, membuat repository lebih ringan.

- **2026-05-22** 🧭 **Recovery swarm + keepalive MCP**: status swarm sekarang direkonsiliasi dari live task file pada setiap read, sehingga view API/MCP/SSE/list memulihkan run crash atau stale alih-alih menampilkan snapshot `running` permanen. `run_swarm` mengirim progress heartbeat MCP selama polling, dengan first frame tetap `swarm_started run_id=<id>` untuk client yang reconnect setelah transport drop; worker sekarang heartbeat selama LLM streaming, grounding fetch, dan tool execution. Stale-run reaper memakai threshold per run dan menurunkan terminal status dari task state, `SwarmTool` tidak lagi membatalkan team yang masih berjalan hanya karena wait budget habis, dan client MCP dapat memanggil `reap_stale_runs()` untuk explicit cleanup. DX pass hari ini juga merefresh default model provider dan menyelaraskan syntax check CI dengan package `agent/cli/` baru. 22 regression baru mencakup hydration, terminal recovery, stale reaping, cadence keepalive, env parsing, dan wiring heartbeat; full swarm/MCP suite berada di 169 passed, 4 skipped.

- **2026-05-21** 🧱 **Refactor package CLI**: `agent/cli.py` (3216 LOC) dipecah menjadi package `agent/cli/` — interactive front door, slash router, Rich component, plus shim `_legacy.py` yang mempertahankan setiap subcommand dan mereexport setiap public symbol agar `cli.cmd_*` / `cli._INIT_ENV_PATH` / `cli.Confirm` tetap bekerja. Middleware FastAPI baru menyajikan SPA shell ketika browser membuka `/runs/{id}` atau `/correlation` secara langsung; narrowing yang sama masuk ke Vite dev proxy. Version disatukan melalui `cli/_version.py` (tidak ada lagi drift antara `--version` dan banner), `python -m cli` dipulihkan lewat `__main__.py`, dan chat-gate dipersempit agar `chat --help` / `chat extra` mencapai legacy argparse alih-alih tertelan REPL.

- **2026-05-20** 🔬 **CLI Hypothesis Registry**: menutup sisi CLI dari Hypothesis Registry yang dikirim backend-only pada 2026-05-16. `vibe-trading hypothesis list` mencetak Rich table atau JSON (filter `--status`, `--limit`); `show <id>` merender detail panel termasuk linked run card; `invalidate <id> --note "..."` mengubah status menjadi `rejected` sambil mempertahankan prior invalidation note ketika `--note` dihilangkan. Menghormati env override `VIBE_TRADING_HYPOTHESES_PATH` yang sudah ada dan menambahkan `--path` per invocation. 22 test baru mencakup wiring, JSON output, status filter, limit, missing-id error, dan persistence note.

- **2026-05-19** ✨ **Feedback tool live + cancel yang graceful**: tool yang berjalan lama (backtest, PDF besar, swarm worker) tidak lagi terlihat freeze. Setiap tool call sekarang mengirim heartbeat setiap 3 detik plus progress terstruktur per stage — `run_backtest` menampilkan marker phase (`validate` / `simulate` / `finalize`), `read_document` tick per page untuk PDF atau per sheet untuk Excel, `read_url` menandai `fetch` / `parse`. Dashboard CLI Rich Live merender Unicode spinner, ASCII progress bar, ETA, dan menumpuk hingga 3 tool paralel berdasarkan nama; frontend chat mengirim `ToolProgressIndicator` baru dengan render yang dicoalesce rAF, ARIA `role="status"` + native `<progress>` tersembunyi untuk screen reader, serta SVG `ProgressRing` determinate ketika total diketahui. `Ctrl+C` pertama selama run CLI sekarang memanggil `agent.cancel()` untuk keluar secara graceful (step saat ini selesai, trace ditutup dengan bersih); yang kedua dalam 2 detik melakukan force-quit. Primitive reusable yang diekstrak sepanjang proses: `ProgressBar.tsx` dan `lib/tools.ts` (i18n nama tool bersama).

- **2026-05-18** 🧹 **Cleanup pass + tiga latent bug fix**: `CompositeEngine` tidak lagi salah merutekan code China-futures bare seperti `RB2410` ke `GlobalFuturesEngine` — `_is_china_futures` dipindahkan ke module `_market_hooks` bersama dengan product table yang case-normalized dan guard exchange non-CN, plus 9 regression case baru. Index FTS5 session sekarang mempersist timestamp agar cross-session search dapat diurutkan berdasarkan tanggal; path yang sama juga memperbaiki re-upsert yang sebelumnya mengganti `started_at` setiap session dengan wall clock saat ini. Vite dev-mode proxy mendapat entry `/alpha` yang hilang sehingga halaman AlphaZoo resolve pada `npm run dev`. `tests/test_e2e_harness_v2.py` (real-LLM e2e suite) sekarang digate di balik `VIBE_TRADING_RUN_LIVE_E2E=1` agar bentuk CI tidak lagi berubah hanya karena adanya env key. Ruff `per-file-ignores` ditambahkan untuk factor zoo (3783 → 0 noise F401), frontend tsconfig mengaktifkan `noUnusedLocals` / `noUnusedParameters` sebagai regression guard, dan 76 baris boilerplate `vw = vwap(...)` yang tidak terpakai dihapus dari alpha `gtja191`. Net **-918 LOC**.

- **2026-05-17** 🧬 **Alpha Zoo v1 (0.1.8)**: 452 quant alpha siap pakai di 4 zoo — `qlib158` (Microsoft Qlib, atribusi Apache-2), `alpha101` (Kakushadze 101 Formulaic Alphas, rewrite paper dari arXiv:1601.00991), `gtja191` (report factor short-horizon Guotai Junan 2014), dan `academic` (proxy berbasis harga Fama-French 5 + Carhart). Satu baris CLI untuk membenchmark zoo mana pun pada universe Anda: `vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025`. Hadir dengan AST purity gate, test lookahead-guard, network kill-switch `pytest-socket`, `LICENSE.md` per zoo, dan workflow Developer Certificate of Origin (DCO) untuk PR community. Alpha Library dirender otomatis di [vibetrading.wiki/alpha-library/](https://vibetrading.wiki/alpha-library/) + post Research Lab [Which of the 191 GTJA alphas still work in 2026?](https://vibetrading.wiki/research-lab/posts/alpha-191-in-2026.html).

- **2026-05-16** 🧪 **Update research spine**: menambahkan Hypothesis Registry backend dengan `create_hypothesis`, `update_hypothesis`, `link_backtest`, dan `search_hypotheses`; reader external-content sekarang melampirkan `security_warnings` yang hanya berupa warning; dan scanning Shadow Account sekarang memakai evaluasi feature OHLCV deterministic alih-alih stub calendar-phase lama.

- **2026-05-15** 🪪 Halaman run detail sekarang menampilkan run card Trust Layer bersama metric dan artifact, menyelesaikan sisi UI dari pekerjaan `run_card.json` yang masuk pada 2026-05-12. `PersistentMemory.add()` juga diperkeras untuk length, nama empty/whitespace-only, dan byte control C0/C1 dari triage #108/#109/#110 ([#112](https://github.com/HKUDS/Vibe-Trading/pull/112), terima kasih @Teerapat-Vatpitak).

- **2026-05-14** 🌐 wiki publik sekarang live di [vibetrading.wiki](https://vibetrading.wiki/) dengan bagian docs, tutorial, Research Lab, dan Alpha Library yang dideploy melalui Cloudflare Pages. Persistent memory juga dapat diinspect dari CLI melalui `vibe-trading memory list/show/search/forget` ([#102](https://github.com/HKUDS/Vibe-Trading/pull/102), terima kasih @Teerapat-Vatpitak), dan tokenization/slug memory sekarang mendukung teks Thai, Arabic, Hebrew, dan Cyrillic ([#104](https://github.com/HKUDS/Vibe-Trading/pull/104)).

- **2026-05-13** 🧭 Swarm run sekarang memberi grounding worker dengan market data yang sudah difetch dan report persisted yang lebih bersih ([#93](https://github.com/HKUDS/Vibe-Trading/pull/93), [#84](https://github.com/HKUDS/Vibe-Trading/pull/84)).

- **2026-05-12** 🧾 Backtest sekarang menghasilkan `run_card.json` dan `run_card.md` bersama artifact untuk research run yang reproducible.

- **2026-05-11** 🧭 **Memory slug, accounting swarm, dan preflight CLI**: persistent memory sekarang mempertahankan karakter CJK saat membuat file slug, mencegah silent filename collision untuk note Mandarin/Jepang/Korea ([#95](https://github.com/HKUDS/Vibe-Trading/pull/95), terima kasih @voidborne-d). Total swarm run sekarang memprioritaskan token usage yang dilaporkan provider dengan fallback estimasi yang sudah ada ([#94](https://github.com/HKUDS/Vibe-Trading/pull/94), terima kasih @Teerapat-Vatpitak), dan UI run CLI mendapat startup preflight check untuk masalah environment umum ([#96](https://github.com/HKUDS/Vibe-Trading/pull/96), terima kasih @ykykj).

- **2026-05-10** 🧱 **Regression guardrail + metadata run**: memory recall sekarang memperlakukan underscore sebagai token boundary, sehingga saved memory snake_case seperti `mcp_wiring_test` cocok dengan query natural-language seperti "mcp wiring" ([#87](https://github.com/HKUDS/Vibe-Trading/pull/87), terima kasih @hp083625). Server MCP memiliki subprocess smoke test yang mencakup initialize → `tools/list` → `tools/call` untuk menjaga first-call deadlock path ([#86](https://github.com/HKUDS/Vibe-Trading/pull/86)), sementara hardening low-risk masuk untuk test Windows yang path-sensitive, API best-effort exception handling, validation allowed-root `run_dir` backtest, dan metadata provider/model SwarmRun ([#88](https://github.com/HKUDS/Vibe-Trading/pull/88), [#90](https://github.com/HKUDS/Vibe-Trading/pull/90), [#91](https://github.com/HKUDS/Vibe-Trading/pull/91), [#92](https://github.com/HKUDS/Vibe-Trading/pull/92), terima kasih @Teerapat-Vatpitak).

- **2026-05-09** 🛡️ **Hardening path API + stabilitas server MCP**: route run/session API sekarang memvalidasi path ID sebelum lookup, menolak parameter malformed yang mengandung newline dan mengunci behaviour tersebut dalam auth/security regression suite ([#80](https://github.com/HKUDS/Vibe-Trading/pull/80), terima kasih @SJoon99). Server MCP sekarang melakukan pre-warm tool registry di main thread sebelum melayani `tools/call`, menghindari first-call deadlock pada lazy tool discovery ([#85](https://github.com/HKUDS/Vibe-Trading/pull/85), terima kasih @Teerapat-Vatpitak). Vite dev proxy juga menghormati `VITE_API_URL` untuk target backend non-default ([#82](https://github.com/HKUDS/Vibe-Trading/pull/82), terima kasih @voidborne-d).

- **2026-05-08** 🧾 **Field statement Tushare dalam filter**: daily backtest A-share sekarang dapat meminta field financial statement yang PIT-safe melalui `fundamental_fields`, sehingga signal engine dapat melakukan screening pada `income_total_revenue`, `income_n_income`, `balancesheet_total_hldr_eqy_exc_min_int`, `fina_indicator_roe`, dan column berprefix table serupa setelah tanggal announcement/disclosure mereka ([#76](https://github.com/HKUDS/Vibe-Trading/pull/76), terima kasih @mrbob-git). Follow-up hardening membuat request statement-field eksplisit fail fast ketika enrichment Tushare tidak dapat berjalan, alih-alih diam-diam fallback ke raw price bar ([#77](https://github.com/HKUDS/Vibe-Trading/pull/77)).

- **2026-05-07** 📈 **Fundamentals Tushare + community triage**: menambahkan contract point-in-time `TushareFundamentalProvider` untuk workflow fundamental research, dengan regression coverage untuk path environment `TUSHARE_TOKEN` milik project ([#74](https://github.com/HKUDS/Vibe-Trading/pull/74)). Community triage juga memperjelas bahwa Vibe-Trading untuk sementara mempertahankan rapid iteration dengan fokus pada satu bahasa UI, menghindari dependency search redundan selama `web_search` berbasis DuckDuckGo sudah dibundel, dan memperlakukan unofficial hosted deployment sebagai tempat yang tidak tepercaya untuk API key atau token data source.

- **2026-05-06** 🚀 **v0.1.7 dirilis** ([Catatan rilis](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.7), `pip install -U vibe-trading-ai`): hardening security boundary sekarang dipublish di PyPI dan ClawHub, mencakup default API/read/upload/file/URL/generated-code/shell-tool/Docker yang lebih aman sambil mempertahankan workflow CLI/Web UI localhost tetap low-friction. Cycle ini juga mencakup Web UI Settings, correlation heatmap, OpenAI Codex OAuth, pre-ST filtering A-share, UX CLI interaktif, inspeksi swarm preset, dividend analysis, polish workflow dev, dan audited dependency floor untuk build frontend. Terima kasih kepada contributor 0.1.7 dan lemi9090 (S2W) atas coordinated security validation.

- **2026-05-05** 🛡️ **Follow-up security boundary**: menyelesaikan hardening security boundary yang tersisa seputar explicit CORS origin, indicator credential Settings, web URL reading, dan code generation Shadow Account, dengan regression test ditambahkan untuk setiap path. Workflow CLI/Web UI localhost normal tetap sama; remote deployment sebaiknya terus memakai `API_AUTH_KEY` dan trusted origin eksplisit.

- **2026-05-04** 🖥️ **UX CLI interaktif + cleanup CI**: interactive mode sekarang memiliki live bottom status bar yang menampilkan provider/model, durasi session, latency run terakhir, dan cumulative tool-call stat, plus navigasi prompt history serta cursor editing dengan arrow key melalui `prompt_toolkit` ([#69](https://github.com/HKUDS/Vibe-Trading/pull/69)). CLI tetap fallback ke Rich prompt ketika `prompt_toolkit` atau TTY tidak tersedia. Ekspektasi path CI juga diselaraskan dengan file-import sandbox yang sudah diharden dan resolution `/tmp` lintas platform, membuat `main` kembali hijau ([`bb67dc7`](https://github.com/HKUDS/Vibe-Trading/commit/bb67dc7cfcc11553c57d8962bee56381dca43758)).

- **2026-05-03** 🛡️ **Patch security hardening**: memperketat default authentication API untuk deployment non-local, melindungi read run/session/swarm sensitif, membatasi boundary upload dan local file-reading, menggate tool yang shell-capable berdasarkan entry point, memvalidasi loading generated strategy sebelum import, dan menjalankan Docker image sebagai user non-root dengan port yang secara default hanya dipublish ke localhost. Workflow CLI lokal dan Web UI localhost tetap low-friction; deployment API/Web remote sebaiknya menetapkan `API_AUTH_KEY`.

- **2026-05-02** 🧭 **Dividend analysis + roadmap yang lebih tajam**: menambahkan skill `dividend-analysis` untuk income stock, sustainability payout, dividend growth, shareholder yield, mechanics ex-dividend, dan check yield-trap, dikunci oleh bundled-skill regression test. Roadmap publik sekarang berfokus pada pekerjaan berikutnya: Research Autopilot, Data Bridge, Options Lab, Portfolio Studio, Alpha Zoo, Research Delivery, Trust Layer, dan Community sharing.

- **2026-05-01** 🔥 **Correlation heatmap + OpenAI Codex OAuth + pre-ST filter A-share**: dashboard/API correlation baru menghitung rolling return correlation dan merender ECharts heatmap untuk analysis portfolio dan simbol ([#64](https://github.com/HKUDS/Vibe-Trading/pull/64)). Dukungan provider OpenAI Codex sekarang memakai ChatGPT OAuth melalui `vibe-trading provider login openai-codex`, dengan metadata Settings dan regression test adapter ([#65](https://github.com/HKUDS/Vibe-Trading/pull/65)). Skill `ashare-pre-st-filter` ditambahkan dan diperkeras untuk risk screening ST/*ST A-share, termasuk relevance filtering penalty Sina agar penyebutan securities-account tidak menggelembungkan count E2 ([#63](https://github.com/HKUDS/Vibe-Trading/pull/63)).

- **2026-04-30** ⚙️ **Web UI Settings + hardening validation CLI**: halaman Settings baru untuk provider/model LLM, base URL, reasoning effort, dan credential data source, didukung settings API lokal/auth-protected serta provider metadata data-driven ([#57](https://github.com/HKUDS/Vibe-Trading/pull/57)). Juga memperkeras `python -m backtest.validation <run_dir>` agar input missing, blank, malformed, non-existent, dan bukan directory gagal dengan pesan yang jelas untuk operator sebelum validation dimulai ([#60](https://github.com/HKUDS/Vibe-Trading/pull/60)).

- **2026-04-28** 🚀 **v0.1.6 dirilis** (`pip install -U vibe-trading-ai`): memperbaiki `vibe-trading --swarm-presets` yang mengembalikan kosong setelah `pip install` / `uv tool install` ([#55](https://github.com/HKUDS/Vibe-Trading/issues/55)) — preset YAML sekarang dibundel di dalam package `src.swarm` dan dikunci oleh regression suite 6 test. Loader AKShare juga sekarang merutekan ETF (`510300.SH`) dan forex (`USDCNH`) ke endpoint yang benar dengan fallback registry yang diperkeras. Merangkum semua sejak v0.1.5: panel benchmark comparison, streaming `/upload` + size limit, loader Futu (HK + A-share), skill export vnpy, security hardening, dan lazy loading frontend (688KB → 262KB).

- **2026-04-27** 📊 **Panel benchmark + keamanan upload**: output backtest sekarang menyertakan panel benchmark comparison (ticker / benchmark return / excess return / information ratio) dengan resolution berbasis yfinance untuk SPY, CSI 300, dan lainnya ([#48](https://github.com/HKUDS/Vibe-Trading/issues/48)). Selain itu, `/upload` menstream request body dalam chunk 1 MB dan abort ketika melewati `MAX_UPLOAD_SIZE`, membatasi memory untuk client oversized/malformed ([#53](https://github.com/HKUDS/Vibe-Trading/pull/53)) — dikunci oleh regression suite 4 case.

- **2026-04-22** 🛡️ **Hardening + integration baru**: path containment ditegakkan di `safe_path` + sandbox tool journal/shadow, `MANIFEST.in` menyertakan `.env.example` / test / file Docker dalam sdist, dan lazy loading level route mengecilkan initial bundle frontend dari 688KB → 262KB. Ditambah loader data Futu untuk equity HK & A-share ([#47](https://github.com/HKUDS/Vibe-Trading/pull/47)) dan skill export vnpy CtaTemplate ([#46](https://github.com/HKUDS/Vibe-Trading/pull/46)).

- **2026-04-21** 🛡️ **Workspace + docs**: `run_dir` relatif dinormalisasi ke active run dir ([#43](https://github.com/HKUDS/Vibe-Trading/pull/43)). Contoh penggunaan README ([#45](https://github.com/HKUDS/Vibe-Trading/pull/45)).

- **2026-04-20** 🔌 **Reasoning + Swarm**: `reasoning_content` dipertahankan di seluruh path `ChatOpenAI` — thinking Kimi / DeepSeek / Qwen bekerja end-to-end ([#39](https://github.com/HKUDS/Vibe-Trading/issues/39)). Streaming swarm + Ctrl+C yang bersih ([#42](https://github.com/HKUDS/Vibe-Trading/issues/42)).

- **2026-04-19** 📦 **v0.1.5**: dipublish ke PyPI & ClawHub. Floor CVE `python-multipart` dinaikkan, 5 tool MCP baru dihubungkan (`analyze_trade_journal` + 4 tool shadow-account), fix registry `pattern_recognition` → `pattern`, parity dependency Docker, manifest SKILL disinkronkan (22 tool MCP / 71 skill).

- **2026-04-18** 👥 **Shadow Account**: ekstrak rule strategi Anda dari broker journal → backtest shadow lintas market → report HTML/PDF 8 bagian yang menunjukkan secara tepat berapa banyak peluang yang terlewat (rule violation, early exit, missed signal, counterfactual trade). 4 tool baru, 1 skill, total 32 tool. Sample Trade Journal + Shadow Account sekarang tersedia di welcome screen Web UI.

- **2026-04-17** 📊 **Trade Journal Analyzer + Universal File Reader**: upload export broker (同花顺/东财/富途/generic CSV) → auto trading profile (holding days, win rate, rasio PnL, drawdown) + 4 diagnostic bias (disposition effect, overtrading, chasing momentum, anchoring). `read_document` sekarang mendispatch PDF, Word, Excel, PowerPoint, image (OCR), dan 40+ format teks melalui satu unified call.

- **2026-04-16** 🧠 **Agent Harness**: persistent cross-session memory, pencarian session FTS5, self-evolving skill (full CRUD), context compression 5 layer, batching tool read/write. 27 tool, 107 test baru.

- **2026-04-15** 🤖 **Z.ai + MiniMax**: provider Z.ai ([#35](https://github.com/HKUDS/Vibe-Trading/pull/35)), fix temperature MiniMax + update model ([#33](https://github.com/HKUDS/Vibe-Trading/pull/33)). 13 provider.

- **2026-04-14** 🔧 **Stabilitas MCP**: memperbaiki error tool backtest `Connection closed` pada transport stdio ([#32](https://github.com/HKUDS/Vibe-Trading/pull/32)).

- **2026-04-13** 🌐 **Cross-Market Composite Backtest**: `CompositeEngine` baru membacktest portfolio mixed-market (mis. A-share + crypto) dengan shared capital pool dan rule per market. Juga memperbaiki fallback variable template swarm dan timeout frontend.

- **2026-04-12** 🌍 **Multi-Platform Export**: `/pine` mengekspor strategi ke TradingView (Pine Script v6), TDX (通达信/同花顺/东方财富), dan MetaTrader 5 (MQL5) dalam satu command.

- **2026-04-11** 🛡️ **Reliability & DX**: bootstrap `.env` melalui `vibe-trading init` ([#19](https://github.com/HKUDS/Vibe-Trading/pull/19)), preflight check, runtime data-source fallback, dan backtest engine yang diharden. README multi-language ([#21](https://github.com/HKUDS/Vibe-Trading/pull/21)).

- **2026-04-10** 📦 **v0.1.4**: fix Docker ([#8](https://github.com/HKUDS/Vibe-Trading/issues/8)), tool MCP `web_search`, 12 provider LLM, dependency `akshare`/`ccxt`. Dipublish ke PyPI dan ClawHub.

- **2026-04-09** 📊 **Backtest Wave 2**: engine ChinaFutures, GlobalFutures, Forex, Options v2. Monte Carlo, Bootstrap CI, validation Walk-Forward.

- **2026-04-08** 🔧 **Backtest multi-market** dengan rule per market, export Pine Script v6, dan 5 data source dengan auto-fallback.

</details>

---

<a id="-key-features"></a>
## ✨ Fitur Utama

<div align="center">
<table align="center" width="94%" style="width:94%; margin-left:auto; margin-right:auto;">
  <tr>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-self-improving-trading-agent.png" height="130" alt="Agent trading yang terus berkembang"/><br>
      <h3>🔍 Agent Trading yang Terus Berkembang</h3>
      <div align="left">
        • Riset market dengan bahasa alami<br>
        • Draft strategi serta analisis file/web<br>
        • Workflow berbasis memory
      </div>
    </td>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-multi-agent-trading-teams.png" height="130" alt="Tim trading multi-agent"/><br>
      <h3>🐝 Tim Trading Multi-Agent</h3>
      <div align="left">
        • Tim investasi, quant, crypto, dan risiko<br>
        • Progress streaming dan laporan yang tersimpan<br>
        • Worker berlandaskan data market yang diambil
      </div>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-cross-market-data-backtesting.png" height="130" alt="Data dan backtest lintas market"/><br>
      <h3>📊 Data & Backtest Lintas Market</h3>
      <div align="left">
        • Saham A / HK / AS / Kanada / UK / India / Korea, crypto, futures, dan forex<br>
        • Fallback data dan backtest komposit<br>
        • Data PIT, validasi, dan run card
      </div>
    </td>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-shadow-account.png" height="130" alt="Shadow Account"/><br>
      <h3>👥 Shadow Account</h3>
      <div align="left">
        • Diagnosis perilaku dari jurnal broker<br>
        • Perbandingan Shadow Account berbasis aturan<br>
        • Laporan audit dan kode strategi yang dapat diekspor
      </div>
    </td>
  </tr>
</table>
</div>

## 💡 Apa Itu Vibe-Trading?

Vibe-Trading adalah workspace riset open-source untuk mengubah pertanyaan finansial menjadi analisis yang dapat dijalankan. Vibe-Trading menghubungkan prompt bahasa alami dengan loader data market, pembuatan strategi, engine backtest, laporan, ekspor, dan memory riset yang persisten.

Vibe-Trading dirancang untuk riset, simulasi, dan backtest — serta, jika Anda memilihnya, trading otonom melalui broker yang Anda otorisasi sendiri (misalnya Robinhood Agentic Trading). Vibe-Trading tidak menyimpan dana dan tidak pernah melakukan trading di luar batas yang Anda tetapkan, serta dapat dihentikan seketika.

---

## ✨ Apa yang Dapat Anda Lakukan

| Tugas | Output |
|------|--------|
| **Ajukan pertanyaan trading** | Riset market menggunakan tool, data, dokumen, dan konteks sesi yang dapat digunakan kembali. |
| **Backtest ide strategi** | Kode strategi, metrik, konteks benchmark, artefak validasi, dan run card. |
| **Tinjau trade Anda sendiri** | Parsing jurnal broker, diagnosis perilaku, ekstraksi aturan, dan perbandingan Shadow Account. |
| **Baca dokumen & chart** | Parse PDF / DOCX / XLSX / PPTX / gambar dengan OCR pluggable (`read_document`), dan baca screenshot chart secara semantik dengan vision model (`analyze_image`). Web chat menerima hingga lima file sekaligus melalui file picker, drag-and-drop, atau paste dari clipboard. |
| **Baca filing institusi & fund book** | SEC 13F manager book dengan perbedaan posisi quarter-over-quarter, konstituen ETF lintas market, implied probability kontrak event, dan ekstraksi faktor arXiv / OpenAlex — semuanya read-only dari sumber publik gratis. |
| **Tingkatkan riset berulang** | Memory persisten dan skill yang dapat diedit mengubah rutinitas berguna menjadi workflow yang dapat digunakan kembali. |
| **Jalankan tim analis** | Review riset multi-agent untuk workflow investasi, quant, crypto, makro, dan risiko. |
| **Bawa riset ke channel IM** | Jalankan runtime sesi yang sama melalui WebSocket, Telegram, Slack, Discord, Matrix, WhatsApp, Signal, QQ/NapCat, WeChat/WeCom, Feishu/Lark, DingTalk, Teams, email, dan Mochat dengan kontrol CLI, REST, dan Web UI. |
| **Hasilkan artefak yang siap digunakan** | Laporan, TradingView Pine Script, TDX, MetaTrader 5, tool MCP, dan sesi riset lanjutan. |
| **Benchmark alpha zoo siap pakai** | Satu baris untuk IC + kategorisasi alive/reversed/dead pada 462 alpha (Qlib 158 + Kakushadze 101 + GTJA 191 + akademik + fundamental PIT-safe) di universe Anda. |
| **Deteksi regime korelasi** | Timeline edge-density + hysteresis pada surface `/correlation` yang menunjukkan kapan market menyatu menjadi satu blok — konteks risiko deskriptif, bukan sinyal. |

---

## ⚡ Contoh Cepat

```bash
pip install vibe-trading-ai

# Natural-language research
vibe-trading run -p "Backtest a BTC-USDT 20/50 moving-average strategy for 2024, summarize return and drawdown, then export the report"

# Bench a pre-built alpha zoo (one line)
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

```bash
vibe-trading --upload trades_export.csv
vibe-trading run -p "Analyze my trading behavior, extract my shadow strategy, and compare it with my actual trades"
```

---

<a id="-shadow-account"></a>
## 👥 Shadow Account

Shadow Account dimulai dari catatan trading Anda sendiri, bukan dari template strategi generik.

Upload export broker, biarkan agent merangkum perilaku Anda, lalu bandingkan jalur trading aktual dengan strategi shadow berbasis aturan.

| Langkah | Output Agent |
|------|--------------|
| **1. Baca jurnal Anda** | Parse export broker dari 同花顺, 东方财富, 富途, dan format CSV generik. |
| **2. Profilkan perilaku Anda** | Hari holding, persentase kemenangan, rasio PnL, drawdown, disposition effect, overtrading, momentum chasing, dan pemeriksaan anchoring. |
| **3. Ekstrak aturan Anda** | Mengubah pola entry/exit berulang menjadi profil strategi eksplisit, bukan sekadar ringkasan yang samar. |
| **4. Jalankan shadow** | Melakukan backtest aturan yang diekstrak dan menyoroti pelanggaran aturan, exit terlalu cepat, sinyal terlewat, serta jalur trade alternatif. |
| **5. Hasilkan laporan** | Membuat laporan HTML/PDF yang dapat diperiksa, diarsipkan, atau disempurnakan di sesi berikutnya. |

```bash
vibe-trading --upload trades_export.csv
vibe-trading run -p "Analyze my trading behavior, extract my shadow strategy, and compare it with my actual trades"
```

---

## 💼 Portofolio Multi-Broker Lokal

Web UI menambahkan halaman **Portofolio** read-only yang mengagregasi kepemilikan dari koneksi broker yang Anda pilih. Sumbernya adalah instance koneksi dari profil read-only yang mendeklarasikan `account.read` dan `positions.read` — atur di bagian **Broker Connectors** pada [Kapabilitas Detail](#-detailed-capabilities). Kelayakan hanyalah safety gate; connection center juga menunjukkan sejauh mana setiap connector telah diverifikasi untuk valuasi portofolio.

| Perilaku | Yang Anda dapatkan |
|----------|--------------|
| **Provenance per sumber** | Setiap kepemilikan menyebut koneksi asalnya, dinilai dalam USD dengan konversi CNY. |
| **Sumber gagal dikecualikan** | Sumber yang error dilaporkan sebagai error dan dikeluarkan dari total — tidak pernah dibawa ke depan — dan snapshot ditandai tidak lengkap. |
| **Snapshot immutable** | Setiap refresh disimpan di `~/.vibe-trading/portfolio/portfolio.sqlite3`; pengaturan tanpa kredensial berada di `~/.vibe-trading/portfolio.json` dan `connections.json`. |
| **Ekspor & analisis** | Ekspor CSV, plus tool agent `portfolio_summary` yang sudah disanitasi; `risk_xray_args` diteruskan langsung ke `portfolio_risk_xray`. Snapshot yang sama dapat dicetak di terminal dengan `vibe-trading portfolio show` (`refresh` / `sources` tersedia juga). |

Mata uang sumber yang dilaporkan broker dipertahankan saat valuasi: total akun dan posisi HKD, termasuk kepemilikan Futu `HK.*`, dikonversi menggunakan rate USD/HKD snapshot sebelum nilai USD dan CNY ditampilkan. Snapshot lama tetap disimpan, tetapi riwayat nilai hanya membandingkan snapshot yang dibuat dengan metodologi valuasi saat ini agar perbaikan valuasi tidak tampak sebagai keuntungan atau kerugian palsu.

### Kompatibilitas connector portofolio

| Badge | Arti |
|-------|---------|
| **Native adapter** | Tersedia normalisasi portofolio dan perilaku valuasi khusus untuk connector tersebut. |
| **Contract-tested** | Fixture berbentuk respons connector telah lolos contract akun/posisi bersama, tetapi ini bukan jaminan bahwa setiap variasi akun broker sudah diuji secara live. |
| **Experimental** | Profil secara struktural read-only dan dapat dipilih, tetapi mata uang, total akun, atau semantik instrumennya masih memerlukan verifikasi khusus broker. |

Every position row must provide a symbol and quantity. Unsupported currencies fail the source explicitly instead of being silently treated as USD. The current valuation core supports USD, HKD and CNY; IBKR, Longbridge and Binance use native handling, while Alpaca and OKX have common-contract coverage. OKX account balance details are adapted into spot holdings alongside any open positions. Robinhood reads the one account you pick from the broker's own list (`vibe-trading connector select-account <id>` or the connection center) and never falls back to a default account; its equity positions are listed unpriced until the quote reply is mapped, and an account that also holds options, crypto, futures, event contracts, mutual funds or fixed income fails the source instead of showing an equity-only view. A new built-in connector or local plugin defaults to **Experimental** until its portfolio contract fixtures are added.

### Onboarding connector yang ramah AI

Connector SDK bawaan memublikasikan satu kontrak onboarding machine-readable: tipe autentikasi, field kredensial wajib, dependency opsional, perintah instalasi, dan operasi read-only yang digunakan untuk verifikasi. `trading_connections` mengekspos kontrak yang sama kepada client MCP, sementara connection center Portofolio merendernya sebagai form generik. Kontrak hanya berisi nama field — tidak pernah nilai kredensial.

Untuk setup yang berfokus pada terminal, biarkan CLI mengumpulkan secret secara lokal alih-alih menaruhnya di prompt atau argumen shell:

```bash
vibe-trading connector setup okx-live-sdk-readonly \
  --connection-id main-okx \
  --label "Main OKX"
```

CLI meminta input di terminal lokal, menyimpan nilainya di OS keyring berdasarkan connection id tersebut, lalu menjalankan pemeriksaan read-only connector. Flow Web yang setara adalah **Portofolio → Kelola akun → Buka pusat koneksi → pilih template → simpan ke keyring → uji koneksi**. Tool read MCP dapat menggunakan `connection_id`; proses akan mengambil kredensial dari vault sehingga key tidak pernah melewati MCP. Konfigurasi lama `~/.vibe-trading/<connector>.json` dan environment tetap menjadi fallback kompatibilitas sampai sebuah koneksi memiliki set kredensial vault yang lengkap.

Jangan menempelkan API key broker ke chat AI. Biarkan AI memilih connector, menginstal dependency yang dideklarasikan, dan menafsirkan diagnostik; masukkan secret hanya melalui prompt terminal lokal yang tersembunyi atau form koneksi lokal.

Connector read-only yang Anda instal sendiri tetap berada di luar checkout, di `~/.vibe-trading/connectors/<name>/`: manifest `connector.json` dan `adapter.py` yang mengimplementasikan `check_status` / `get_account_snapshot` / `get_positions`. Manifest yang mendeklarasikan kapabilitas write akan ditolak.

```bash
vibe-trading connector init my-broker --destination /tmp
vibe-trading connector validate /tmp/my-broker
vibe-trading connector install /tmp/my-broker
```

Kredensialnya disimpan ke OS keyring (macOS Keychain, Windows Credential Manager, Linux Secret Service) dengan `pip install "vibe-trading-ai[keyring]"`, bukan ke file config. Tidak ada jalur ini yang dapat membuat atau membatalkan order.

---

## 🧪 Workflow Riset

Sebagian besar run mengikuti jalur bukti yang sama: rute request, muat konteks market yang tepat, jalankan tool, validasi output, dan pertahankan artefak agar dapat diperiksa.

Agent berhenti dengan permintaan pemulihan yang terlihat setelah delapan iterasi tool-call berturut-turut tanpa observasi berhasil yang baru.
Mengulangi hasil read yang sama atau call gagal tidak mereset budget ini.
Call yang identik ditolak mulai dari kegagalan KEDUA — satu retry setelah kegagalan sementara (rate limit, gangguan jaringan, timeout tool) masih diperbolehkan —
hingga tool yang mengubah state berhasil dijalankan atau run baru dimulai; argumen yang berubah selalu dapat dieksekusi.
Pemulihan meminta path artefak atau izin untuk menjalankan ulang langkah riset yang hilang, dan run tetap dianggap gagal meskipun metrik lama tersedia.
Guard ini terpisah dari watchdog aktivitas berbasis wall-clock.
asks for an artifact path or permission to rerun the missing research step, and
the run remains failed even if older metrics exist. This guard is separate from
the wall-clock activity watchdog.

| Lapisan | Yang terjadi |
|-------|--------------|
| **Plan** | Memilih skill finansial, tool, sumber data, dan preset swarm yang relevan bila berguna. |
| **Ground** | Mengambil A-share, saham HK/AS/Kanada/UK, crypto, futures, forex, dokumen, atau konteks web melalui loader yang tersedia. |
| **Execute** | Menghasilkan kode strategi yang dapat diuji, menjalankan tool, dan memakai engine backtest atau workflow analisis yang sesuai. |
| **Validate** | Menambahkan metrik, perbandingan benchmark, Monte Carlo, Bootstrap, Walk-Forward, run card, dan warning bila relevan. |
| **Deliver** | Mengembalikan laporan, artefak, tool trace, dan ekspor untuk TradingView, TDX, MetaTrader 5, client MCP, atau sesi berikutnya. |

---

## 📡 Sumber Data & Smart Fallback

Satu call `get_market_data`, **28 sumber data market**, salah satunya marketplace premium opsional **QVeris**. Atur `source: "auto"` — loader memilih berdasarkan simbol lalu mengikuti chain per market yang diurutkan berdasarkan **risiko IP-ban**: sumber publik yang tidak pernah diblokir lebih dulu, sumber throttled / membutuhkan key belakangan. Zero-config, tanpa single point of failure.

| Sumber | Market | Auth | Peran |
|--------|---------|------|------|
| `tencent` · `mootdx` | A-share + HK | tidak ada | tidak terkena IP-ban (`mootdx` = 通达信 TCP) |
| `eastmoney` | A / AS / HK | tidak ada | OHLCV + fundamental mendalam & tool flow (throttled) |
| `baostock` · `akshare` | A (+ AS/HK/futures/makro/fx) | tidak ada | fallback gratis |
| `tushare` | A / HK / futures / fund / makro | token | A-share paling kaya |
| `gildata` | A-share | token (Settings / `GILDATA_TOKEN`) | feed komersial Hundsun Juyuan (恒生聚源) — data harian forward-adjusted, bergabung di ujung chain A-share |
| `yahoo` | AS / HK / Kanada / UK | tidak ada | chart/quote/options langsung; TSX `.TO` / TSXV `.V`; LSE `.L` dengan normalisasi mata uang yang dideklarasikan |
| `sina` · `stooq` | AS | tidak ada | K-line hingga 1984 · EOD CSV |
| `yfinance` | AS / HK / Kanada / UK | tidak ada | wrapper; TSX `.TO` / TSXV `.V`; LSE `.L` dengan contract GBP/GBp yang sama |
| `longbridge` | AS / HK | App Key + App Secret + Access Token | sumber historis OHLCV opsional; instal SDK opsional |
| `finnhub` · `alphavantage` · `tiingo` · `fmp` | AS | key | provider opsional |
| `qveris` | global multi-aset | key · kredit | **marketplace premium** — 63+ provider melalui satu key (hanya eksplisit, tidak pernah masuk auto fallback) |
| `nobitex` · `wallex` | crypto (pair Iranian Toman) | tidak ada | endpoint UDF publik; **hanya eksplisit** — satu-satunya sumber berdenominasi Toman, sehingga tidak masuk chain crypto yang dapat menggantikannya dengan series USD |
| `okx` · `ccxt` · `binance` | crypto | tidak ada | OKX + 100+ exchange + historis Binance / USD-M perps |
| `futu` | HK / A | OpenD | FutuOpenD lokal opsional |
| `mt5` | forex / metals | terminal MT5 | bar forex / metal MetaTrader 5 (gaya Exness), 1m–1D |
| `tickerall` | forex / metals | key + akun (read-only) | feed broker MT5 yang sama, **hosted** — tanpa terminal lokal, OS apa pun (hanya eksplisit, tidak pernah auto fallback) |
| `pykrx` | Korea (KRX: KOSPI/KOSDAQ) | tidak ada | bar harian KOSPI / KOSDAQ untuk `.KS` / `.KQ` (extra `krx` opsional) |
| `india_broker` | India (NSE/BSE) | login broker | bar Zerodha / Shoonya / Dhan read-only untuk `.NS` / `.BO` (ujung fallback chain) |
| `local` | apa pun | tidak ada | CSV / Parquet / DuckDB Anda sendiri melalui prefix `local:` |

**Fallback chain (berdasarkan risiko IP-ban):**

- **A-share** → `tencent` · `mootdx` · `eastmoney` · `baostock` · `akshare` · `tushare` · `gildata` · `local`
- **US** → `yahoo` · `stooq` · `sina` · `eastmoney` · `yfinance` · `tiingo` · `fmp` · `finnhub` · `alphavantage` · `longbridge` · `akshare` · `local`
- **HK** → `tencent` · `eastmoney` · `yahoo` · `futu` · `akshare` · `yfinance` · `tushare` · `longbridge` · `local`
- **India (NSE/BSE)** → `yahoo` · `yfinance` · `india_broker` · `local`
- **Korea (KOSPI/KOSDAQ)** → `pykrx` · `yahoo` · `yfinance` · `local`
- **UK (LSE)** → `yahoo` · `yfinance` · `local` *(declared GBP/GBp quotes only)*
- **Crypto** → `okx` · `ccxt` · `binance` · `yfinance` · `local`
- **Forex / metals** → `mt5` · `yfinance` · `akshare` · `local` &nbsp;·&nbsp; *(futures / fund / macro → `tushare`/`akshare` → `local`)*

### Menggunakan Longbridge secara eksplisit

Longbridge adalah loader historis OHLCV opsional untuk AS/HK. Instal SDK-nya dengan:

```bash
pip install "vibe-trading-ai[longbridge]"
```

Konfigurasikan tiga kredensial di `.env`:

```dotenv
LONGBRIDGE_APP_KEY=...
LONGBRIDGE_APP_SECRET=...
LONGBRIDGE_ACCESS_TOKEN=...
```

Untuk backtest, atur `source` di `config.json`:

```json
{
  "codes": ["QQQ.US"],
  "start_date": "2025-01-01",
  "end_date": "2025-01-10",
  "interval": "1D",
  "source": "longbridge"
}
```

Dalam percakapan Agent, minta secara eksplisit: **"Gunakan Longbridge untuk mengambil data historis QQQ.US."** Permintaan sumber eksplisit terpisah dari `source: "auto"`; `auto` tetap memakai fallback chain normal per market.

Di luar OHLCV, **22 tool data read-only** menjangkau fundamental & flow — fund flow, dragon-tiger, northbound, margin, block trade, jumlah pemegang saham, lockup, sektor, laporan riset, berita, filing SEC, laporan keuangan, options chain, profil saham, market screening, pencarian simbol, makro, iwencai, kepemilikan institusi (13F), ETF look-through, prediction market, dan paper riset — semuanya tersedia melalui MCP. Simbol `local:` eksplisit tidak pernah diam-diam fallback ke sumber jaringan.

<!-- QVERIS-START -->
### 💎 Data premium opsional — QVeris

<img src="https://www.qveris.com/logo-color.png" alt="QVeris" height="36">

**Data: routing gratis atau premium, pilihan Anda.** Mode gratis tetap default: 23 sumber bawaan dengan fallback berdasarkan risiko ban, tanpa key dan tanpa biaya. Premium melalui QVeris menambahkan 10.000+ kapabilitas (menurut QVeris) dari 63+ provider untuk options Greeks, fundamental premium, data China/HK/global, makro, crypto, berita, dan filing; call yang gagal tidak dikenakan biaya. Aktifkan di Settings -> QVeris atau `vibe-trading data mode paid`.

*Disclosure QVeris: [mendaftar melalui referral link Vibe-Trading](https://qveris.ai/?ref=Vyjjo5G_1cAHJA) memberi Anda **+1.000 bonus kredit** sekaligus mendukung proyek.*
<!-- QVERIS-END -->

---

<a id="-detailed-capabilities"></a>
## 🔩 Kapabilitas Detail

Inventaris detail dilipat di bawah agar README utama tetap mudah dipindai. Buka bagian yang Anda perlukan saat ingin memeriksa building block yang tersedia.

<details>
<summary><b>Library Skill Finansial</b> <sub>90 skill dalam 9 kategori</sub></summary>

- 📊 90 skill finansial khusus yang diorganisasi dalam 9 kategori
- 🌐 Cakupan lengkap dari market tradisional hingga crypto & DeFi
- 🔬 Kapabilitas menyeluruh dari sourcing data hingga riset quant

| Kategori | Skill | Contoh |
|----------|--------|----------|
| Data Source | 10 | `data-routing`, `tushare`, `yfinance`, `okx-market`, `akshare`, `mootdx`, `ccxt`, `eastmoney`, `sec-edgar`, `qveris` |
| Strategy | 19 | `strategy-generate`, `cross-market-strategy`, `technical-basic`, `candlestick`, `ichimoku`, `elliott-wave`, `smc`, `multi-factor`, `ml-strategy` |
| Analysis | 23 | `factor-research`, `correlation-regime`, `macro-analysis`, `global-macro`, `valuation-model`, `investor-lenses`, `credit-analysis`, `dividend-analysis` |
| Asset Class | 9 | `options-strategy`, `options-advanced`, `convertible-bond`, `etf-analysis`, `asset-allocation`, `sector-rotation` |
| Crypto | 7 | `perp-funding-basis`, `liquidation-heatmap`, `stablecoin-flow`, `defi-yield`, `onchain-analysis` |
| Flow | 8 | `hk-connect-flow`, `us-etf-flow`, `edgar-sec-filings`, `financial-statement`, `adr-hshare` |
| Tool | 10 | `backtest-diagnose`, `report-generate`, `pine-script`, `doc-reader`, `web-reader`, `vnpy-export`, `trade-journal` |
| Research | 3 | `alpha-zoo`, `strategy-dev-manager`, `strategy-discovery` |
| Risk Analysis | 1 | `ashare-pre-st-filter` |

</details>

<details>
<summary><b>Sumber Data Kustom</b> <sub>daftarkan loader OHLCV historis Anda sendiri</sub></summary>

Butuh market atau vendor yang belum memiliki loader bawaan? Tambahkan loader historical bar Anda sendiri dan pilih dengan `source="<name>"`. Langkah berikut mengedit source package, jadi jalankan dari clone (`pip install -e .`).
loader and select it with `source="<name>"`. The steps edit package source, so
run from a clone (`pip install -e .`).

1. **Tulis loader** — buat `agent/backtest/loaders/<name>_loader.py` dengan class yang memenuhi `DataLoaderProtocol` (duck-typed, tidak perlu base class) dan diberi `@register`:
   class that satisfies `DataLoaderProtocol` (duck-typed, no base class needed)
   and is tagged with `@register`:

   ```python
   import pandas as pd
   from backtest.loaders.registry import register

   @register
   class DataLoader:
       name = "mysource"            # the value you pass as source=
       markets = {"us_equity"}      # a_share/us_equity/hk_equity/crypto/futures/fund/macro/forex
       requires_auth = False

       def is_available(self) -> bool:
           return True              # token present? network reachable?

       def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
           # return {symbol: DataFrame indexed by trade_date,
           #         columns: open, high, low, close, volume}
           ...
   ```

2. **Daftarkan modul** agar `@register` dieksekusi — tambahkan `"backtest.loaders.<name>_loader"` ke `_loader_modules` di `agent/backtest/loaders/registry.py`.
   `"backtest.loaders.<name>_loader"` to `_loader_modules` in
   `agent/backtest/loaders/registry.py`.
3. **Izinkan nama tersebut** melalui validasi config — tambahkan `"mysource"` ke `_VALID_SOURCES` di `agent/backtest/runner.py`.
   `_VALID_SOURCES` in `agent/backtest/runner.py`.
4. *(Opsional)* tempatkan di `FALLBACK_CHAINS` market pada `registry.py` agar `source="auto"` dapat mencapainya.
   `source="auto"` can reach it.
5. **Gunakan** — `source="mysource"` pada config backtest, atau melalui CLI / agent.

> **Real-time tick / order-book depth berada di luar scope loader** —
> layer loader hanya untuk historical bar point-in-time. Data market live mengalir
> melalui broker connector: `okx` / `binance` / `ccxt` untuk crypto,
> `futu` / `tiger` untuk saham.

</details>

<details>
<summary><b>Broker Connectors</b> <sub>18 broker — read + paper, bounded-live bila didukung</sub></summary>

Profil berorientasi connector. Sebagian besar mendukung read + penempatan order akun paper — IBKR read-only, Robinhood live-only (tanpa akun paper), Scalable Capital read-only (tidak memiliki akun paper sama sekali), sedangkan Trading 212 dan Toss Securities menolak penempatan order sepenuhnya, termasuk paper; penempatan order live dibatasi oleh mandat yang ditentukan pengguna (allowlist simbol, batas ukuran order / eksposur, batas trade harian, dan penghentian darurat) serta tidak pernah menyimpan dana — broker yang mengeksekusi. Tool penempatan order tetap nonaktif di MCP (hanya agent + CLI). Jalur riset / backtest secara struktural tidak dapat mengakses endpoint live.

| Broker | Market | Kapabilitas |
|--------|---------|--------------|
| **IBKR** | global | local TWS / Gateway, read-only |
| **Robinhood** | US | Agentic MCP (desktop OAuth) — read + bounded live |
| **Scalable Capital** | DE / EU | Agentic MCP (desktop OAuth) — fully read-only; no paper account exists |
| **Tiger** | US / HK / A | read + paper + bounded live |
| **Alpaca** | US | read + paper + bounded live (+ TAP credential-isolation mode) |
| **OKX** · **Binance** | crypto | read + paper + bounded live |
| **Futu** | HK / US / A | read + paper + bounded live |
| **eToro** | global | read + paper + bounded live (Public API; demo keys reach only `/demo` paths, plus copy-trading workflows) |
| **MetaTrader 5** | forex / CFD | read + paper + bounded live (Exness-style; demo ⇔ paper identity guard) |
| **KIS** (한국투자증권) | Korea (KOSPI/KOSDAQ) | read + genuine paper (모의투자, a real broker-side sandbox on a separate host) — live order placement not yet wired for this market |
| **Longbridge** · **Dhan** · **Shoonya** · **Zerodha** · **Upbit** | US / HK · India (NSE/BSE) · Korea (crypto) | read + paper only — no runtime paper/live discriminator, so live order placement is hard-refused |
| **Trading 212** · **Toss Securities** | UK / EU · Korea/US | fully read-only — `place_order` / `cancel_order` hard-refuse even paper (no verified sandbox) |

Pemisahan paper-vs-live adalah **guard runtime struktural per broker** (format account-id, pemisahan host, demo flag, atau trade environment), bukan config flag yang dapat diubah agent. Broker yang tidak menyediakan discriminator tersebut dibatasi pada paper + read-only.

</details>

<details>
<summary><b>Preset Tim Trading</b> <sub>30 preset swarm</sub></summary>

- 🏢 30 tim agent siap pakai
- ⚡ Workflow finansial yang sudah dikonfigurasi
- 🎯 Preset investasi, trading & manajemen risiko

| Preset | Workflow |
|--------|----------|
| `investment_committee` | Bull/bear debate → risk review → PM final call |
| `global_equities_desk` | A-share + HK/US + crypto researcher → global strategist |
| `crypto_trading_desk` | Funding/basis + liquidation + flow → risk manager |
| `earnings_research_desk` | Fundamental + revision + options → earnings strategist |
| `macro_rates_fx_desk` | Rates + FX + commodity → macro PM |
| `quant_strategy_desk` | Screening + factor research → backtest → risk audit |
| `technical_analysis_panel` | Classic TA + Ichimoku + harmonic + Elliott + SMC → consensus |
| `risk_committee` | Drawdown + tail risk + regime review → sign-off |
| `global_allocation_committee` | A-shares + crypto + HK/US → cross-market allocation |

<sub>Plus 20+ preset spesialis tambahan — jalankan vibe-trading --swarm-presets untuk melihat semuanya.
Bawa preset Anda sendiri: taruh YAML preset di <code>~/.vibe-trading/swarm/presets/</code> — preset akan tampil
bersama roster bawaan (file dengan nama sama akan override, seperti user skill) dan tetap ada setelah upgrade.

</sub>

</details>

<details>
<summary><b>Alpha Zoo</b> <sub>462 alpha quant siap pakai dalam 5 keluarga</sub></summary>

- 🧬 462 alpha cross-sectional, lookahead dilarang pada layer operator
- 📈 IC + IR + kategorisasi alive/reversed/dead dalam satu perintah CLI
- 🔬 AST purity gate + test sentinel lookahead 300 baris + network kill-switch `pytest-socket`
- 📦 Atribusi Apache-2 untuk Qlib; `LICENSE.md` per-zoo menyatakan formula sebagai konten matematis
- 🤝 Workflow sign-off Developer Certificate of Origin (DCO) untuk PR komunitas

| Zoo | Jumlah | Sumber | Lisensi |
|-----|-------|--------|---------|
| **qlib158** | 154 | Microsoft Qlib `Alpha158` (Apache-2.0, commit-pinned) | Apache-2.0 |
| **alpha101** | 101 | Kakushadze (2015), "101 Formulaic Alphas", arXiv:1601.00991 | Formulas are mathematical content |
| **gtja191** | 191 | Guotai Junan (2014), "191 Short-period Trading Alpha Factors" | Formulas are mathematical content |
| **academic** | 12 | Fama-French 5 + Carhart momentum + Jegadeesh reversal + George-Hwang 52-week-high + Amihud illiquidity + Harvey-Siddique skew + Frazzini-Pedersen betting-against-beta + correlation-rewiring stability (price-based proxies) | Public academic literature |
| **fundamental** | 4 | PIT-safe SEC company facts — earnings yield, ROE, gross profitability, asset growth (filed-date anchored) | Public financial data |

Jalankan `vibe-trading alpha list` untuk menjelajah, `vibe-trading alpha show <id>` untuk formula + source, `vibe-trading alpha bench --zoo X --universe Y --period Z` untuk menilai seluruh zoo, dan `vibe-trading alpha compare --all` untuk memberi peringkat antar-zoo.

</details>

<details>
<summary><b>Engine Backtest</b> <sub>10 engine + portofolio opsi, komposit lintas market</sub></summary>

| Engine | Market | Catatan |
|--------|--------|-------|
| **ChinaA** | A-share | T+1, price limits, pre-ST filter |
| **GlobalEquity** | US / HK / Canada / UK | same-session trading; market-specific lots, ticks, settlement currencies, and costs |
| **IndiaEquity** | India (NSE/BSE) | T+1, circuit bands, config-driven STT / stamp / SEBI / GST cost stack |
| **KoreaEquity** | Korea (KRX: KOSPI/KOSDAQ) | long-only, ±30% band judged at execution time on the unified tick grid, 2026 0.20% transaction tax |
| **VietnamEquity** | Vietnam (HOSE) | long-only, T+2 settlement hold, ±7% band on the 10/50/100-VND tick grid, 100-share lots, 0.1% sell-side tax |
| **Crypto** | crypto spot / USD-M perps | funding settlements, execution/mark split |
| **ChinaFutures** · **GlobalFutures** | futures | margin, contract multipliers |
| **Forex** | FX / metals | via the `mt5` loader (local terminal) or the hosted `tickerall` loader (no terminal, any OS) |
| **Composite** | cross-market | one shared capital pool across markets (`source="auto"`) |
| **options_portfolio** | options | multi-leg, Greeks, payoff/scenario |

Bar: 1m / 5m / 15m / 30m / 1H / 4H / 1D, plus mingguan / bulanan (1W / 1M, dibangun dari bar harian). 15 metrik + perbandingan benchmark, **5 optimizer portofolio** (equal-volatility / risk-parity / mean-variance / max-diversification / turnover-aware), dan 3 tool validasi (Monte Carlo / Bootstrap / Walk-Forward).

</details>

<details>
<summary><b>Quant Library</b> <sub>306 fungsi teruji dalam 23 modul, dapat dipanggil dari setiap transport</sub></summary>

`src/quantlib` menyimpan satu implementasi teruji untuk setiap matematika finansial yang dibutuhkan agent.
Skill **mengimpor** fungsi-fungsi ini alih-alih membawa formula di dalam
blok kode markdown — jika Anda menemukan formula pricing berada di `SKILL.md`,
itu adalah bug, bukan pola.

| Modul | Cakupan |
|--------|----------------|
| `options` | Black-Scholes price + greeks, implied-volatility inversion |
| `fixedincome` | Bond math, Nelson-Siegel / Svensson curve fitting |
| `credit` | Altman Z-score, Merton / KMV distance-to-default |
| `timeseries` | Stationarity, cointegration, GARCH, bootstrap |
| `risk` · `var_backtest` | VaR / CVaR / EVT and their backtests |
| `attribution` | Brinson-Fachler decomposition |
| `performance` · `fundmath` | TWR / MWR / Modified Dietz; XIRR / MOIC / DPI / TVPI |
| `factormodel` · `eventstudy` | Factor regressions, event studies |
| `multipletesting` · `crossvalidation` | Deflated significance, purged CV |
| `impact` | Market-impact models |
| `volatility` | Heston (1993) stochastic-volatility pricing |
| `portfolio` | Hierarchical Risk Parity allocation |
| `copula` | Gaussian and Archimedean copulas |
| `microstructure` | VPIN, Roll spread, Amihud illiquidity, Kyle's lambda |

Tool read-only `quantlib_call` menjangkau semuanya melalui satu contract, sehingga
matematika finansial bekerja di CLI, Web UI, REST API, dan MCP — termasuk
deployment ketika `bash` dinonaktifkan. Secara struktural ini bukan shell —
module allowlist, dispatch hanya `__all__`, dan `export_*` ditolak.
Econometrics memerlukan extra `stats`
(`pip install "vibe-trading-ai[stats]"`); fungsi-fungsinya lazy-import dan akan memberi tahu
dependency mana yang belum tersedia.

</details>

<details>
<summary><b>Valuasi & Riset Institusional</b> <sub>DCF, comps, three-statement, dan enam perintah riset</sub></summary>

Engine valuasi yang menolak mengarang input sendiri. Satu aturan di
`contracts.py`: **input yang hilang membuat model NOT RUNNABLE dan tidak pernah
diam-diam diberi default** — setiap default di model valuasi adalah opini yang
disamarkan sebagai konstanta.

| Model | Perilaku yang perlu diketahui |
|-------|-------------------------|
| `run_dcf` | FCFF bridge, WACC build, mid-year discounting, net-debt bridge, WACC×g sensitivity grid. Dual terminal value: each method is cross-checked against the other's implied multiple and implied g |
| `run_comps` | EV bridge, LTM + calendar-year calendarisation, multiple matrix. A peer with a non-positive denominator is **excluded and reported**, never averaged in as a negative multiple |
| `threestatement` | Linked projection with a hard balance assertion, an explicit revolver plug, and an iterated interest↔debt circularity that must converge or raise |

Artefak diberi hash berdasarkan input dan diberi versi, dengan ekspor xlsx / pptx.

Enam slash command menjalankan workflow — `/comps` `/dcf` `/attrib` `/memo`
`/earnings` `/screen` — masing-masing membawa skeleton langkah dan
contoh kerja yang konsisten secara aritmetika (dekomposisi Brinson menjumlah tepat ke
active return; earnings bridge menjumlah tepat ke delta EPS). Skill
`investor-lenses` menumpuk framework reasoning investor bernama sebagai
overlay analisis: setiap lens adalah prosedur operasi — sinyal prioritas,
kondisi diskualifikasi, dan penyalahgunaan umum — bukan biografi, dan tidak menyebut tool.

Di luar bar, `src/entities` mengonsumsi cash flow bertanggal yang tidak beraturan (NAV, capital
call, coupon) dan `cashflow_performance` melaporkan XIRR / MOIC / DPI / TVPI /
TWR / Modified Dietz / MWR. Jalur ini sengaja paralel dengan
bar engine agar kolom `nav` tidak pernah masuk dan diperlakukan sebagai close.

</details>

<details>
<summary><b>Governance & Audit Trail</b> <sub>menjawab "metodologi apa yang menghasilkan angka itu?"</sub></summary>

Setiap run menulis **manifest** yang melakukan hash atas prompt, isi skill, registry tool,
dan versi package, sehingga angka yang dihasilkan bulan lalu dapat ditelusuri
ke metodologi tepat yang menghasilkannya.

**Audit ledger** menghubungkan setiap record ke hash pendahulunya dan melakukan fsync, sehingga
pengeditan atau penghapusan record dapat dideteksi — bahkan edit yang menghitung ulang
hash-nya sendiri tetap tertangkap satu record kemudian melalui `prev_hash_mismatch`. Timestamp
selalu diberikan caller; tidak ada modul di sini yang memanggil `datetime.now()`.

Redaksi trace bersifat **sink-aware**: argumen tool-call dan live audit ledger
memakai fail-closed sink di mana `content` tetap disamarkan, sementara tool-result
sink melepaskannya lalu melakukan pattern-scrub pada string leaf. `env` tidak pernah dilepas
di keduanya.

</details>

<a id="-demo"></a>
## 🎬 Demo

<div align="center">
<table>
<tr>
<td width="50%">

https://github.com/user-attachments/assets/4e4dcb80-7358-4b9a-92f0-1e29612e6e86

</td>
<td width="50%">

https://github.com/user-attachments/assets/3754a414-c3ee-464f-b1e8-78e1a74fbd30

</td>
</tr>
<tr>
<td colspan="2" align="center"><sub>☝️ Backtest bahasa alami & debat swarm multi-agent — Web UI + CLI</sub></td>
</tr>
</table>
</div>

---

<a id="-quick-start"></a>
## 🚀 Mulai Cepat

### Instal satu baris (PyPI)

```bash
pip install vibe-trading-ai
```

Lalu jalankan tugas riset pertama:

```bash
vibe-trading init
vibe-trading run -p "Backtest a BTC-USDT 20/50 moving-average strategy for 2024 and summarize return and drawdown"
```

> **Upgrade dari versi lama?** 0.1.10 berpindah ke LangChain 1.x. Jika import rusak setelah `pip install -U vibe-trading-ai` dari instalasi sebelum 0.1.10 (mis. langgraph gagal diimport), buat ulang venv atau jalankan `pip install --force-reinstall vibe-trading-ai`. Instalasi baru tidak terpengaruh.

> **Nama package vs perintah:** Package PyPI adalah `vibe-trading-ai`. Setelah terinstal, Anda mendapatkan tiga perintah:
>
> | Perintah | Tujuan |
> |---------|---------|
> | `vibe-trading` | CLI / TUI interaktif |
> | `vibe-trading serve` | Jalankan web server FastAPI |
> | `vibe-trading-mcp` | Jalankan server MCP (untuk Claude Desktop, OpenClaw, Cursor, dll.) |

```bash
vibe-trading init              # interactive .env setup
vibe-trading                   # launch CLI
vibe-trading serve --port 8899 # launch web UI
vibe-trading-mcp               # start MCP server (stdio)
```

### Atau pilih jalur

| Jalur | Cocok untuk | Waktu |
|------|----------|------|
| **A. Docker** | Coba sekarang, tanpa setup lokal | 2 menit |
| **B. Instalasi lokal** | Development, akses CLI penuh | 5 menit |
| **C. Plugin MCP** | Hubungkan ke agent yang sudah Anda gunakan | 3 menit |
| **D. ClawHub** | Satu perintah, tanpa clone | 1 menit |

### Prasyarat

- **LLM API key** dari provider yang didukung — atau jalankan secara lokal dengan **Ollama** (tanpa key)
- **Python 3.11+** untuk Jalur B
- **Docker** untuk Jalur A
- OpenAI Codex juga dapat digunakan dengan ChatGPT OAuth: atur `LANGCHAIN_PROVIDER=openai-codex`, lalu jalankan `vibe-trading provider login openai-codex`. Ini tidak menggunakan `OPENAI_API_KEY`.
- GitHub Copilot dapat digunakan dengan subscription Copilot aktif tanpa LLM API key yang ditagihkan terpisah. Lihat [provider GitHub Copilot SDK](#github-copilot-sdk-provider).

> **Provider LLM yang didukung:** OpenRouter, OpenAI, Anthropic (native Messages API), DeepSeek, OpenCode (Go / Zen), Gemini, Groq, DashScope/Qwen, Zhipu, Moonshot/Kimi, MiniMax, SiliconFlow (CN + Global), Xiaomi MIMO, Novita AI, iFlytek Spark, Z.ai, NVIDIA NIM, ModelScope, GitHub Copilot, Ollama (lokal). Jika `*_BASE_URL` tidak diatur, setiap provider fallback ke endpoint canonical-nya, jadi cukup key saja. Lihat `.env.example` untuk config.

> **Tip:** Semua market dapat bekerja tanpa API key berkat fallback otomatis. yfinance/Yahoo (HK/AS/Kanada/UK), OKX (crypto), mootdx (A-share, TCP langsung, tanpa throttle IP), dan AKShare (A-share, AS, HK, futures, forex) semuanya gratis. Quote LSE `.L` harus mendeklarasikan GBP atau GBp agar pence dapat dinormalisasi sebelum accounting GBP. Token Tushare opsional — mootdx adalah fallback A-share tanpa token yang disarankan, dengan AKShare sebagai backup yang lebih luas.

<a id="github-copilot-sdk-provider"></a>
### Provider GitHub Copilot SDK

GitHub Copilot SDK resmi tersedia sebagai extra opsional, jadi instal bersama Vibe-Trading dengan `pip install "vibe-trading-ai[copilot]"`; instalasi Copilot CLI bersifat opsional. Autentikasikan dengan salah satu metode berikut:

```bash
gh auth login                         # use GitHub CLI credentials
# or run `copilot` and sign in         # stores credentials in the OS keychain
# or export COPILOT_GITHUB_TOKEN=gho_xxx
```

Lalu konfigurasikan `agent/.env`:

```dotenv
LANGCHAIN_PROVIDER=copilot
LANGCHAIN_MODEL_NAME=claude-sonnet-5
# COPILOT_GITHUB_TOKEN=gho_xxx         # optional; recommended for Docker/CI
```

Jalankan Vibe-Trading seperti biasa. Preflight akan melaporkan apakah SDK dapat melakukan autentikasi:

```bash
vibe-trading
```

Prioritas autentikasi adalah `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`, kredensial Copilot CLI yang tersimpan, lalu kredensial `gh`. Vibe-Trading tidak menyalin atau menyimpan kredensial SDK. Kredensial keychain host tidak otomatis tersedia di dalam Docker, jadi container sebaiknya menerima `COPILOT_GITHUB_TOKEN`.

### Jalur A: Docker (tanpa setup)

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
cp agent/.env.example agent/.env
# Edit agent/.env — uncomment your LLM provider and set API key
docker compose up --build
```

Buka `http://localhost:8899`. Backend + frontend berjalan dalam satu container.

> [!NOTE]
> **OpenAI Codex OAuth dengan Docker:** login browser memerlukan terminal agar Anda
> dapat menempelkan callback URL. Jalankan melalui Compose, yang menyediakan
> terminal interaktif secara otomatis:
>
> ```bash
> docker compose exec vibe-trading vibe-trading provider login openai-codex
> ```
>
> Jika menggunakan `docker exec` secara langsung, tambahkan `-it` sebelum nama container.

Docker memublikasikan backend di `127.0.0.1:8899` secara default dan menjalankan aplikasi sebagai user container non-root. Jika Anda sengaja mengekspos API di luar mesin sendiri, atur `API_AUTH_KEY` yang kuat dan kirim `Authorization: Bearer <key>` dari client.

> [!NOTE]
> **Menggunakan Ollama dengan Docker:** container mengakses Ollama di host melalui `host.docker.internal`, bukan `localhost` (di dalam container, `localhost` merujuk ke container itu sendiri). `docker-compose.yml` secara default mengatur `OLLAMA_BASE_URL` ke `http://host.docker.internal:11434`; ekspor `OLLAMA_BASE_URL` (atau atur di `.env` level atas) untuk menggunakan alamat lain. Ini bergantung pada mapping `host-gateway` di `extra_hosts`, yang memerlukan **Docker Engine ≥ 20.10 / Compose v2** (tersedia otomatis di Docker Desktop).

Data Anda tetap bertahan setelah update: memory persisten, index pencarian lintas-sesi, skill buatan pengguna, shadow account, config broker connector, sesi web, run backtest, riwayat swarm, dan upload semuanya berada di named Docker volume, sehingga `git pull && docker compose up --build` mempertahankannya. Respons Web yang sedang berlangsung juga di-checkpoint, sehingga restart memulihkan respons parsial dan menandai attempt sebagai terinterupsi alih-alih menghilangkannya diam-diam. Data hanya dihapus oleh `docker compose down -v`.

### Jalur B: Instalasi lokal

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
python -m venv .venv

# Activate
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\activate.bat       # Windows CMD
# .venv\Scripts\Activate.ps1       # Windows PowerShell

pip install -e .
cp agent/.env.example agent/.env   # Edit — set your LLM provider API key
vibe-trading                       # Launch interactive TUI
```

> [!NOTE]
> **Di Windows:** `cp` adalah alias PowerShell untuk `Copy-Item`, jadi snippet di atas bekerja apa adanya di PowerShell. CMD tidak memiliki `cp` — gunakan `copy agent\.env.example agent\.env` (berlaku juga untuk snippet Docker). Jika PowerShell menolak menjalankan `Activate.ps1`, jalankan `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` terlebih dahulu; hanya berlaku untuk sesi shell tersebut.

<details>
<summary><b>Jalankan Web UI (opsional)</b></summary>

```bash
# Terminal 1: API server
vibe-trading serve --port 8899

# Terminal 2: Frontend dev server
cd frontend && npm install && npm run dev  # requires Node >= 22.22
```

Buka `http://localhost:5899`. Frontend mem-proxy call API ke `localhost:8899`.

**Mode production (satu server):**

```bash
cd frontend && npm run build && cd ..
vibe-trading serve --port 8899     # FastAPI serves dist/ as static files
```

> [!NOTE]
> `vibe-trading serve` bind ke `0.0.0.0` dan secara default hanya mengizinkan loopback: membuka UI di **mesin yang sama** (`http://localhost:8899`) bekerja tanpa config tambahan. Jika Anda membuka dari **mesin lain, host VM, atau ponsel di LAN**, endpoint sensitif mengembalikan `403` dan chat menampilkan "Remote API access requires an API key" — atur `API_AUTH_KEY` yang kuat di `agent/.env`, restart, lalu masukkan key yang sama sekali saja di **Settings**. (Host gateway Docker Desktop: atur `VIBE_TRADING_TRUST_DOCKER_LOOPBACK=1` dengan bind port default `127.0.0.1`.)

</details>

### Jalur C: Plugin MCP

Lihat bagian [Plugin MCP](#-mcp-plugin) di bawah.

### Jalur D: ClawHub (satu perintah)

```bash
npx clawhub@latest install vibe-trading --force
```

Skill + config MCP diunduh ke direktori skill agent Anda. Lihat [instalasi ClawHub](#-mcp-plugin) untuk detail.

---

## 🧠 Environment Variable

Salin `agent/.env.example` ke `agent/.env` lalu uncomment block provider yang Anda inginkan. Setiap provider memerlukan 3–4 variable:

| Variable | Wajib | Deskripsi |
|----------|:--------:|-------------|
| `LANGCHAIN_PROVIDER` | Ya | Nama provider (`openrouter`, `deepseek`, `groq`, `ollama`, dll.) |
| `<PROVIDER>_API_KEY` | Ya* | API key (`OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, dll.) |
| `<PROVIDER>_BASE_URL` | Ya | URL endpoint API |
| `LANGCHAIN_MODEL_NAME` | Ya | Nama model (mis. `deepseek-v4-pro`) |
| `LANGCHAIN_REASONING_EFFORT` | Tidak | Tingkat reasoning (`none`, `low`, `medium`, `high`, atau `max`) |
| `LANGCHAIN_USE_RESPONSES_API` | Tidak | Override transport Responses: literal `true` memakai `/v1/responses` jika endpoint mendukung; native adapter mempertahankan transport sendiri; nilai lain memakai Chat Completions |
| `TUSHARE_TOKEN` | Tidak | Token Tushare Pro untuk data A-share (fallback ke AKShare) |
| `TIMEOUT_SECONDS` | Tidak | Timeout call LLM, default 120 detik |
| `API_AUTH_KEY` | Disarankan untuk deployment jaringan | Bearer token yang diwajibkan saat API dapat diakses client non-lokal |
| `VIBE_TRADING_ENABLE_SHELL_TOOLS` | Tidak | Opt-in eksplisit untuk tool shell pada deployment remote API/MCP-SSE |
| `VIBE_TRADING_ALLOWED_FILE_ROOTS` | Tidak | Root tambahan dipisah koma untuk import dokumen dan jurnal broker |
| `VIBE_TRADING_ALLOWED_RUN_ROOTS` | Tidak | Root tambahan dipisah koma untuk direktori run kode yang dihasilkan |
| `VIBE_TW_STOCK_DB` | Tidak | Path ke snapshot SQLite market Taiwan; tool read-only `taiwan_stock_data` hanya terdaftar jika schema valid |
| `VIBE_TRADING_EXTRA_CORS_ORIGINS` | Tidak | Origin dipisah koma yang **ditambahkan** ke default CORS loopback (`CORS_ORIGINS` menggantikannya) |
| `CONTENT_FILTER_WARNING_THRESHOLD` | Tidak | Threshold rasio warning content-filter (default 0.05 = 5%). Jika rasio respons LLM yang diblokir moderasi melebihi ini, run card menyarankan mengganti provider. |

<sub>* Ollama tidak memerlukan API key. OpenAI Codex menggunakan ChatGPT OAuth dan menyimpan token melalui `oauth-cli-kit`, bukan di `agent/.env`. Autentikasi GitHub Copilot ditangani SDK resmi.</sub>

**Data gratis (tanpa key):** A-share melalui AKShare, saham HK/AS/Kanada/UK melalui Yahoo/yfinance, crypto melalui OKX, dan 100+ exchange crypto melalui CCXT. Sistem otomatis memilih sumber terbaik yang tersedia untuk setiap market.

### 🎯 Model yang Direkomendasikan

Vibe-Trading adalah agent yang sangat bergantung pada tool — skill, backtest, memory, dan swarm semuanya berjalan melalui tool call. Pilihan model langsung menentukan apakah agent benar-benar *menggunakan* tool atau mengarang jawaban dari data training.

| Tier | Contoh | Kapan digunakan |
|------|----------|-------------|
| **Terbaik** | `anthropic/claude-opus-4.7`, `anthropic/claude-sonnet-4.6`, `openai/gpt-5.5-pro`, `google/gemini-3.5-flash` | Swarm kompleks (3+ agent), sesi riset panjang, analisis setara paper |
| **Sweet spot** (default) | `deepseek-v4-pro`, `deepseek/deepseek-v4-pro`, `x-ai/grok-4.20`, `z-ai/glm-5.1`, `moonshotai/kimi-k2.6`, `qwen/qwen3-max-thinking` | Daily driver — tool-calling andal dengan biaya sekitar 1/10 |
| **Hindari untuk penggunaan agent** | `*-nano`, `*-flash-lite`, `*-coder-next`, varian kecil / distilled | Tool-calling tidak andal — agent akan terlihat "menjawab dari memory" alih-alih memuat skill atau menjalankan backtest |

Default `agent/.env.example` menggunakan API resmi DeepSeek + `deepseek-v4-pro`; pengguna OpenRouter dapat memakai `deepseek/deepseek-v4-pro`.

---

## 🖥 Referensi CLI

TUI interaktif (`vibe-trading`) kini memakai transcript native terminal: startup banner, prompt rule, recap turn sebelumnya, activity rail live, rendering Markdown/tabel, dan timing run semuanya tetap berada di CLI. Pemanggilan non-interaktif seperti `vibe-trading run`, pipe, dan `--json` tetap ramah script.

```bash
vibe-trading               # interactive TUI
vibe-trading run -p "..."  # single run
vibe-trading serve         # API server
vibe-trading alpha list    # browse 462 pre-built alphas; show / bench / compare / export-manifest sub-commands available
vibe-trading playbook list # five scheduled-research templates; show / create sub-commands available
vibe-trading channels status --local  # inspect IM channel config and install hints
vibe-trading provider doctor  # print redacted provider/proxy/package diagnostics
```

<details>
<summary><b>Slash command di dalam TUI</b></summary>

| Perintah | Deskripsi |
|---------|-------------|
| `/help` | Tampilkan shortcut keyboard dan daftar perintah |
| `/model` | Ganti provider dan model LLM |
| `/memory` | Tampilkan / kelola memory persisten |
| `/history` | Jelajahi dan lanjutkan sesi sebelumnya |
| `/goal` | Mulai / periksa tujuan riset finansial |
| `/search` | Pencarian full-text di seluruh sesi |
| `/swarm` | Preset multi-agent (committee / quant / risk) |
| `/skill` | Daftar / muat / unload skill |
| `/show` | Tampilkan run sebelumnya berdasarkan id |
| `/clear` | Bersihkan percakapan saat ini |
| `/pine` | Ekspor strategi saat ini sebagai Pine Script |
| `/journal` | Analisis CSV jurnal trading |
| `/shadow` | Latih / lihat shadow account |
| `/export` | Ekspor sesi saat ini (md / json) |
| `/debug` | Toggle panel debug (penggunaan token / latency) |
| `/comps` | Analisis comparable company (peer multiple -> implied range) |
| `/dcf` | Valuasi discounted cash flow dengan sensitivity grid |
| `/attrib` | Atribusi Brinson-Fachler (alokasi vs seleksi) |
| `/memo` | Memo investasi — tesis, variant view, skenario, kill criteria |
| `/earnings` | Review earnings — surprise bridge dari revenue ke EPS |
| `/screen` | Screen ide sistematis — hipotesis, funnel, survivor queue |
| `/playbook` | Template riset terjadwal (list / run / schedule) |
| `/connector` | Profil connector trading (status / start / halt) |
| `/halt` | Penghentian darurat — hentikan SEMUA live trading sekarang |
| `/resume` | Nonaktifkan penghentian darurat (aktifkan kembali live trading) |
| `/data` | Mode routing data |
| `/quit` | Keluar (juga: q, exit, :q) |

</details>

<details>
<summary><b>Single run & flag</b></summary>

```bash
vibe-trading run -p "Backtest BTC-USDT MACD strategy, last 30 days"
vibe-trading run -p "Analyze AAPL momentum" --json
vibe-trading run -f strategy.txt
echo "Backtest 000001.SZ RSI" | vibe-trading run
```

```bash
vibe-trading -p "your prompt"
vibe-trading --skills
vibe-trading --swarm-presets
vibe-trading --swarm-run investment_committee '{"topic":"BTC outlook"}'
vibe-trading --list
vibe-trading --show <run_id>
vibe-trading --code <run_id>
vibe-trading --pine <run_id>           # Export indicators (TradingView + TDX + MT5)
vibe-trading --trace <run_id>
vibe-trading --continue <run_id> "refine the strategy"
vibe-trading --upload report.pdf
```

```bash
vibe-trading alpha list --zoo gtja191 --limit 10
vibe-trading alpha show gtja191_171
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

</details>

<details>
<summary><b>Channel IM</b></summary>

Adapter channel IM menghubungkan aplikasi chat eksternal ke runtime sesi yang sama dengan Web UI dan CLI. Konfigurasikan adapter aktif di bawah `channels` dalam `~/.vibe-trading/agent.json`; adapter berbasis SDK adalah extra opsional, dan SDK yang hilang menampilkan recovery hint alih-alih membuat runtime crash.

Untuk tugas channel yang berjalan lama, atur budget tunggu respons assistant terpusat dengan `replyTimeoutS` (detik, default `600`):

```json
{
  "channels": {
    "replyTimeoutS": 1800,
    "feishu": {
      "enabled": true
    }
  }
}
```

Ini mengontrol berapa lama runtime channel bersama menunggu sesi agent menghasilkan pesan assistant; timeout HTTP/socket adapter tetap spesifik per adapter.

```bash
vibe-trading channels status --local   # inspect config and missing SDK hints without API
vibe-trading channels status           # query the running API runtime
vibe-trading channels start            # start enabled adapters through the API
vibe-trading channels stop             # stop enabled adapters through the API
vibe-trading channels login weixin     # run an adapter login hook when needed
vibe-trading channels pairing --channel telegram list
```

`vibe-trading channels login feishu` menyimpan kredensial app yang diotorisasi QR ke
`~/.vibe-trading/agent.json` dengan permission file hanya untuk owner sebelum melaporkan
login berhasil.

Adapter bawaan mencakup `websocket`, `telegram`, `slack`, `discord`, `matrix`, `whatsapp`, `signal`, `qq`, `napcat`, `weixin`, `wecom`, `feishu`, `dingtalk`, `msteams`, `email`, dan `mochat`. Gunakan extra sempit seperti `pip install "vibe-trading-ai[telegram]"`, atau instal seluruh set channel dengan `pip install "vibe-trading-ai[channels]"`.

**Slash command di chat** (agnostik terhadap channel, bekerja di seluruh 16 adapter):

| Perintah | Deskripsi |
|---------|-------------|
| `/new` | Reset sesi saat ini — pesan berikutnya memulai percakapan baru |
| `/reset` | Alias untuk `/new` |
| `/newsession` | Alias untuk `/new` |
| `/pairing list` | Tampilkan request pairing sender yang tertunda (operator saja) |

Perintah tidak peka huruf besar/kecil dan harus dikirim sebagai seluruh isi pesan (mis. `hello /new` diperlakukan sebagai pesan biasa, bukan reset).

> **`/pairing` dibatasi untuk operator.** Perintah kontrol pairing di chat ditolak kecuali sender terdaftar sebagai operator — atur `channels.operators` (otoritas lintas-channel) atau daftar `operators` milik section channel di config Anda. Jika tidak ada operator yang dikonfigurasi, `/pairing` di chat ditolak secara fail-closed dan pairing hanya dikelola melalui CLI terautentikasi (`vibe-trading channels pairing …`) dan endpoint REST yang dilindungi auth. Ini mencegah anggota grup yang hanya di-allowlist mengambil alih pairing antar-channel.

**Konfigurasi dari Web UI**: panel **IM Channels** di halaman Settings mengonfigurasi channel tanpa mengedit file secara manual. Buka sebuah channel untuk melihat panel konfigurasinya: field dirender dari metadata backend, dan nilai secret tidak pernah dikirim kembali ke browser, hanya versi tersamarkan (`****` ditambah 4 karakter terakhir). DingTalk adalah channel pertama dengan panduan lengkap: buat app di [open-dev.dingtalk.com](https://open-dev.dingtalk.com/), tambahkan kemampuan bot, aktifkan Stream Mode (tidak perlu URL callback publik), salin AppKey ke Client ID dan AppSecret ke Client Secret, lalu publikasikan app. QQ menyusul sebagai channel dengan panduan lengkap: daftarkan bot di QQ Open Platform ([q.qq.com](https://q.qq.com/)), salin AppID dan AppSecret ke formulir, verifikasi dengan **Test connection** sebelum menyimpan, lalu aktifkan; tidak perlu URL callback publik (WebSocket melalui SDK resmi botpy). **Test connection** menguji nilai di formulir sebelum apa pun disimpan dan menjawab dengan kode hasil yang jujur (`ok`, `invalid_credentials`, `network`, atau `unsupported`). **Enable** langsung berlaku: runtime channel yang sedang berjalan mengganti adapter tersebut saja tanpa restart proses, dan pengaktifan memverifikasi kredensial secara otomatis kecuali Anda memilih **Enable anyway** setelah pemeriksaan gagal. Menonaktifkan channel tetap menyimpan kredensialnya, sehingga mengaktifkannya kembali tidak perlu mengisi ulang. Hanya adapter bawaan yang tercantum di sini; channel plugin dari entry-points tetap dikonfigurasi lewat file.

Penyimpanan menulis section `channels.<name>` di `~/.vibe-trading/agent.json` secara atomik. File konfigurasi YAML bersifat read-only bagi Web UI (edit dari browser memerlukan JSON), dan panel menyatakannya alih-alih gagal. Channel tanpa panduan khusus menampilkan formulir generik yang diturunkan dari default-nya.

</details>

---

<a id="-examples"></a>
## 💡 Contoh

### Strategi & Backtest

```bash
# Moving average crossover on US equities
vibe-trading run -p "Backtest a 20/50-day moving average crossover on AAPL for the past year, show Sharpe ratio and max drawdown"

# RSI mean-reversion on crypto
vibe-trading run -p "Test RSI(14) mean-reversion on BTC-USDT: buy below 30, sell above 70, last 6 months"

# Multi-factor strategy on A-shares
vibe-trading run -p "Backtest a momentum + value + quality multi-factor strategy on CSI 300 constituents over 2 years"

# After backtesting, export to TradingView / TDX / MetaTrader 5
vibe-trading --pine <run_id>
```

Untuk partial rebalancing berbasis kalender, pertahankan sinyal strategi tetap dense dan
pilih bar eksekusi di `config.json`:

```json
{
  "position_adjustment": "rebalance",
  "rebalance_mask": "MS"
}
```

`MS` mengeksekusi target yang sudah disejajarkan pada bar trading pertama yang teramati setiap
bulan. Alias pandas offset mingguan/kuartalan (misalnya `W-FRI` dan `QS`) serta
daftar tanggal ISO eksplisit juga diterima. Alias tidak boleh lebih halus daripada
interval bar yang sudah disejajarkan. Alias periode memilih bar pertama yang teramati di setiap
periode; `W-FRI` memulai minggu berpatokan Jumat dan karena itu biasanya mengeksekusi
pada Senin berikutnya, bukan Jumat. Hilangkan `rebalance_mask` untuk
mempertahankan perilaku rebalance setiap bar yang ada sekarang. Mask sengaja
tidak kompatibel dengan `position_adjustment="hold"`.

**Benchmark alpha zoo siap pakai** (satu baris):
```bash
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

**Jelajahi katalog** dan periksa satu alpha:
```bash
vibe-trading alpha list --zoo gtja191 --theme reversal --limit 10
vibe-trading alpha show gtja191_171
```

**Susun sinyal multi-faktor** dari zoo (Python):
```python
from src.skills.multi_factor.zoo_signal_engine import ZooSignalEngine
engine = ZooSignalEngine.from_zoo(["gtja191_171", "gtja191_111", "gtja191_163"])
panel = ...  # your wide OHLCV panel
signal = engine.compute_signal(panel)
```

### Riset Market

```bash
# Equity deep-dive
vibe-trading run -p "Research NVDA: earnings trend, analyst consensus, option flow, and key risks for next quarter"

# Macro analysis
vibe-trading run -p "Analyze the current Fed rate path, USD strength, and impact on EM equities and gold"

# Crypto on-chain
vibe-trading run -p "Deep dive BTC on-chain: whale flows, exchange balances, miner activity, and funding rates"
```

### Workflow Swarm

```bash
# Bull/bear debate on a stock
vibe-trading --swarm-run investment_committee '{"topic": "Is TSLA a buy at current levels?"}'

# Quant strategy from screening to backtest
vibe-trading --swarm-run quant_strategy_desk '{"universe": "S&P 500", "horizon": "3 months"}'

# Crypto desk: funding + liquidation + flow → risk manager
vibe-trading --swarm-run crypto_trading_desk '{"asset": "ETH-USDT", "timeframe": "1w"}'

# Global macro portfolio allocation
vibe-trading --swarm-run macro_rates_fx_desk '{"focus": "Fed pivot impact on EM bonds"}'

# Resume a failed or cancelled run while keeping its completed tasks
vibe-trading --swarm-retry <run_id> --swarm-resume
```

### Memory Lintas-Sesi

```bash
# Save your preferences once
vibe-trading run -p "Remember: I prefer RSI-based strategies, max 10% drawdown, hold period 5–20 days"

# The agent recalls them in future sessions automatically
vibe-trading run -p "Build a crypto strategy that fits my risk profile"
```

### Upload & Analisis Dokumen

```bash
# Analyze a broker export or earnings report
vibe-trading --upload trades_export.csv
vibe-trading run -p "Profile my trading behavior and identify any biases"

vibe-trading --upload NVDA_Q1_earnings.pdf
vibe-trading run -p "Summarize the key risks and beats/misses from this earnings report"
```

---

<a id="-api-server"></a>
## 🌐 Server API

```bash
vibe-trading serve --port 8899
```

| Method | Endpoint | Deskripsi |
|--------|----------|-------------|
| `GET` | `/runs` | Daftar run |
| `GET` | `/runs/{run_id}` | Detail run |
| `GET` | `/runs/{run_id}/pine` | Ekspor indikator multi-platform |
| `POST` | `/sessions` | Buat sesi |
| `POST` | `/sessions/{id}/messages` | Kirim pesan |
| `GET` | `/sessions/{id}/events` | Stream event SSE |
| `POST` | `/upload` | Upload dokumen, file data, atau gambar |
| `GET` | `/swarm/presets` | Daftar preset swarm |
| `POST` | `/swarm/runs` | Mulai run swarm |
| `GET` | `/swarm/runs/{id}/events` | Stream SSE swarm |
| `GET` | `/alpha/list` | Daftar alpha (filter berdasarkan zoo/theme/universe) |
| `GET` | `/alpha/{alpha_id}` | Metadata alpha + kode sumber |
| `POST` | `/alpha/bench` | Mulai job bench (mengembalikan `job_id`) |
| `GET` | `/alpha/bench/{job_id}/stream` | Stream progress SSE |
| `GET` | `/settings/llm` | Baca pengaturan LLM Web UI |
| `PUT` | `/settings/llm` | Perbarui pengaturan LLM lokal |
| `GET` | `/settings/data-sources` | Baca pengaturan sumber data lokal |
| `PUT` | `/settings/data-sources` | Perbarui pengaturan sumber data lokal |
| `GET` | `/channels/status` | Baca runtime channel IM dan status adapter |
| `POST` | `/channels/start` | Jalankan adapter channel IM yang dikonfigurasi |
| `POST` | `/channels/stop` | Hentikan adapter channel IM yang dikonfigurasi |
| `POST` | `/channels/pairing/command` | Jalankan perintah pairing sender pada store bersama |
| `POST` | `/scheduled-runs` | Buat job riset terjadwal (interval-ms atau cron) |
| `GET` | `/scheduled-runs` | Daftar job terjadwal |
| `GET` | `/scheduled-runs/status` | State executor dan target delivery terkonfigurasi |
| `GET` | `/scheduled-runs/{job_id}` | Baca satu job terjadwal |
| `DELETE` | `/scheduled-runs/{job_id}` | Batalkan job terjadwal |
| `POST` | `/scheduled-runs/proposals/{proposal_id}/commit` | Konfirmasi create/cancel yang diusulkan agent |
| `POST` | `/scheduled-runs/proposals/{proposal_id}/discard` | Buang proposal agent |
| `GET` | `/scheduled-runs/playbooks` | Daftar template riset |
| `GET` | `/scheduled-runs/playbooks/{slug}` | Tampilkan satu template beserta variabelnya |
| `POST` | `/scheduled-runs/playbooks/{slug}` | Jadwalkan job dari template |
| `POST` | `/sessions/{id}/cancel` | Hentikan run yang sedang berjalan di sesi (dicatat sebagai cancelled, bukan failed) |
| `POST` | `/sessions/{id}/title/auto` | Rangkum exchange pertama menjadi judul sesi (tidak pernah menimpa rename manual) |
| `GET` | `/correlation/regime` | Timeline regime edge-density korelasi |
| `GET` | `/agents.json` · `POST` `/v1/query` | Bridge OpenBB Workspace — hanya terdaftar dengan extra `openbb`; `/v1/query` memerlukan auth |

Dokumentasi interaktif tersedia di `http://localhost:8899/docs` dalam mode development loopback
tanpa key. Saat `API_AUTH_KEY` dikonfigurasi, `/docs` dan
`/redoc` dinonaktifkan; tooling terautentikasi dapat mengambil `/openapi.json` dengan header
`Authorization: Bearer <key>`.

### Default keamanan

Untuk development localhost, `vibe-trading serve` menjaga workflow browser tetap sederhana. Untuk client non-lokal, endpoint API sensitif memerlukan `API_AUTH_KEY`; gunakan `Authorization: Bearer <key>` untuk request JSON/upload. Stream Browser EventSource ditangani Web UI setelah Anda memasukkan key yang sama sekali di Settings.

Tool proses yang mampu menjalankan shell (`bash` / `background_run` / `cancel_background`) hanya aktif pada CLI lokal interaktif. Surface lain — HTTP/SSE API dan server MCP di **semua** transport (termasuk stdio) — menonaktifkannya kecuali Anda opt-in eksplisit dengan `VIBE_TRADING_ENABLE_SHELL_TOOLS=1` (atau `--enable-shell-tools` untuk `vibe-trading-mcp`). Tipe transport tidak pernah otomatis memberikan akses shell. `cancel_background` hanya menghentikan task ID yang dilacak dan dikembalikan oleh `background_run`; terminasi proses Python secara luas berdasarkan nama ditolak karena dapat mematikan Vibe-Trading sendiri. Reader dokumen dan jurnal dibatasi ke root upload/import secara default; taruh file di `~/.vibe-trading/uploads`, `~/.vibe-trading/runs`, `./uploads`, `./data` (atau legacy `agent/uploads` / `agent/runs`), atau tambahkan direktori khusus melalui `VIBE_TRADING_ALLOWED_FILE_ROOTS`. Sesi, run, swarm run, upload, dan index `sessions.db` berada di `~/.vibe-trading` (dapat dipindah melalui environment variable `VIBE_TRADING_HOME`); riwayat lama dipindahkan otomatis saat run pertama.

Kode backtest yang dihasilkan berjalan sebagai subprocess Python lokal dan dapat membuat request jaringan melalui loader data market yang dikonfigurasi. Environment sengaja dibatasi: runner mempertahankan kebutuhan dasar OS/Python, pengaturan proxy/certificate, `VIBE_TRADING_ALLOWED_RUN_ROOTS`, dan key data market read-only seperti `TUSHARE_TOKEN`, `FMP_API_KEY`, `FRED_API_KEY`, dan `VIBE_TRADING_IWENCAI_KEY`. Secara default, LLM provider key, token auth API, switch shell-tool, secret trading broker, atau toggle live/advisory tidak diteruskan ke kode strategi yang dihasilkan.

### Pengaturan Web UI

Halaman Settings Web UI memungkinkan pengguna lokal memperbarui provider/model LLM, base URL, parameter generation, tingkat reasoning, dan kredensial data market opsional seperti token Tushare. Pengaturan disimpan ke `agent/.env`; default provider dimuat dari `agent/src/providers/llm_providers.json`.

Read Settings bebas side effect: `GET /settings/llm` dan `GET /settings/data-sources` tidak pernah membuat `agent/.env`, dan hanya mengembalikan path relatif proyek. Read/write Settings dapat mengekspos status kredensial atau memperbarui environment kredensial/runtime, sehingga memerlukan `API_AUTH_KEY` jika dikonfigurasi. Jika `API_AUTH_KEY` tidak diatur dalam dev mode, akses Settings hanya diterima dari client loopback.

Halaman Settings yang sama mencakup panel **IM Channels** untuk operator lokal. Panel melakukan polling `/channels/status`, menampilkan state configured/enabled/available/loaded/running, menampilkan recovery hint adapter, dan dapat menjalankan atau menghentikan runtime channel tanpa kembali ke terminal.

### Riset terjadwal

Jalankan prompt riset atau backtest pada jadwal berulang — dari halaman **Scheduled** di Web UI atau melalui REST. Background executor **nonaktif secara default** — jalankan server dengan `VIBE_TRADING_ENABLE_SCHEDULER=1` untuk mengaktifkannya:

```bash
VIBE_TRADING_ENABLE_SCHEDULER=1 vibe-trading serve --port 8899
```

Lalu buat job melalui REST. `schedule` dapat berupa integer biasa (interval dalam **milidetik**) atau ekspresi cron 5 field (`min hour dom mon dow`; setiap field menerima `*`, `*/n`, angka, daftar dipisah koma, atau range low-high seperti `1-5`). Cron berjalan berdasarkan wall clock dari `timezone` opsional job (IANA key), sehingga cadence tetap konsisten melewati transisi DST — waktu pada spring-forward gap dilewati, dan waktu ambigu saat fall-back dijalankan sekali pada kemunculan pertama. Job tanpa `timezone` tetap memakai semantik UTC biasa:

```bash
# every 6 hours (cron)
curl -X POST http://localhost:8899/scheduled-runs \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Scan CSI300 for momentum breakouts and backtest the top 5","schedule":"0 */6 * * *"}'

# weekdays at 23:30 Auckland wall time — DST-proof
curl -X POST http://localhost:8899/scheduled-runs \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Pre-open scan of NZX names","schedule":"30 23 * * 1-5","timezone":"Pacific/Auckland"}'

# list / cancel
curl http://localhost:8899/scheduled-runs
curl -X DELETE http://localhost:8899/scheduled-runs/<job_id>
```

Setiap trigger menjalankan `prompt` melalui sesi agent baru (parameter backtest opsional berada di `config`), dan job disimpan di `~/.vibe-trading/` sehingga tetap ada setelah restart. Tanpa flag tersebut, endpoint `/scheduled-runs` tetap mencatat job tetapi tidak ada yang dijalankan. Tambahkan `-H "Authorization: Bearer <key>"` pada setiap call jika `API_AUTH_KEY` diatur.

Agent melihat tepat satu tool scheduling, `scheduled_research`. Action read-nya memeriksa status/job/playbook; `propose_create` dan `propose_cancel` hanya menyimpan proposal konfirmasi berumur pendek. Keduanya tidak pernah mengubah job store.
actions inspect status/jobs/playbooks; `propose_create` and `propose_cancel`
only persist a short-lived confirmation proposal. They never mutate the job
Web merender kartu konfirmasi deterministik, CLI meminta `y/N`, dan percakapan IM memerlukan `confirm` (`确认`) atau `cancel` (`取消`) yang tepat; hanya action dari surface tersebut yang memanggil endpoint commit. Draft create membawa `title`, `source`, `schedule`, `end_at`, dan `delivery`. Setelah `end_at` lewat, job yang dipertahankan menjadi `expired` dan tidak akan didispatch lagi.
conversations require an exact `confirm` (`确认`) or `cancel` (`取消`); only
that surface action calls the commit endpoint. Create drafts carry `title`, `source`, `schedule`,
`end_at`, and `delivery`. Once `end_at` passes, the retained job becomes
`expired` and is not dispatched again.

Delivery terjadwal bersifat channel-agnostic. Konfigurasikan target ref opaque yang dapat digunakan kembali di bawah `channels.deliveryTargets`; tool agent dan surface konfirmasinya menampilkan ref, label, dan channel tetapi tidak pernah raw chat/user id provider. Field REST/admin langsung yang sudah ada tetap tersedia untuk kompatibilitas ke belakang:
under `channels.deliveryTargets`; the agent tool and its confirmation surfaces
expose the ref, label, and channel but never the provider's raw chat/user id.
The existing direct REST/admin fields remain available for backward
compatibility:

```json
{
  "channels": {
    "deliveryTargets": {
      "research-team": {
        "label": "Research Team",
        "channel": "feishu",
        "target": "<provider chat or user id>"
      }
    }
  }
}
```

Adapter channel mana pun yang dikonfigurasi dapat dipilih. Status delivery adalah `accepted` ketika adapter berhasil tanpa receipt provider, dan `sent` hanya jika adapter mengembalikan provider message id (saat ini end-to-end diimplementasikan untuk Feishu). Kegagalan tetap dapat di-retry dari outbox persisten.
when an adapter succeeded without a provider receipt, and `sent` only when the
adapter returned a provider message id (currently implemented end to end for
Feishu). Failures remain retryable in the persisted outbox.

**Lima template siap jadwal** tersedia bersama scheduler — `premarket-brief`, `earnings-season-tracker`, `portfolio-checkup`, `a-share-money-flow`, `institutional-holdings-diff`. Setiap template menyatakan data yang dibutuhkan run dalam bahasa biasa alih-alih menyebut tool, sehingga template tetap berfungsi saat surface tool berkembang, dan masing-masing wajib menyebut input yang hilang alih-alih mengisinya dari memory. Akses melalui CLI, REST, atau `/playbook` di TUI:

```bash
vibe-trading playbook list                     # the five templates
vibe-trading playbook show premarket-brief     # body, declared variables, suggested cadence
vibe-trading playbook create premarket-brief \
  --var home_market="US equities" --var watchlist="AAPL, MSFT, NVDA" \
  --timezone America/New_York

curl http://localhost:8899/scheduled-runs/playbooks
curl http://localhost:8899/scheduled-runs/playbooks/premarket-brief
curl -X POST http://localhost:8899/scheduled-runs/playbooks/premarket-brief \
  -H "Content-Type: application/json" \
  -d '{"variables":{"home_market":"US equities","watchlist":"AAPL, MSFT, NVDA"}}'
```

Mengirim `{}` akan menjadwalkan template memakai cadence yang disarankan beserta default yang dideklarasikan. Body hasil render menjadi prompt job secara verbatim, dan variabel yang tidak dideklarasikan ditolak alih-alih diabaikan diam-diam.

---

<a id="-mcp-plugin"></a>
## 🔌 Plugin MCP

Vibe-Trading mengekspos 74 tool MCP untuk client yang kompatibel MCP. Berjalan sebagai subprocess stdio — tidak perlu setup server. Tool riset inti bekerja tanpa API key untuk HK/AS/crypto; tool connector trading menggunakan profil connector terpilih, dan `run_swarm` memerlukan LLM key.

**Environment variable:** client menjalankan server sendiri, sehingga `export` dari shell tidak pernah sampai ke proses tersebut — atur di block `env` client. Kode backtest yang dihasilkan dibatasi ke root run yang diizinkan, jadi menulis hasil ke workspace Anda sendiri memerlukan `VIBE_TRADING_ALLOWED_RUN_ROOTS`:

```json
{
  "mcpServers": {
    "vibe-trading": {
      "command": "vibe-trading-mcp",
      "env": { "VIBE_TRADING_ALLOWED_RUN_ROOTS": "C:\\Users\\me\\research" }
    }
  }
}
```

<details>
<summary><b>Claude Desktop</b></summary>

Tambahkan ke `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "vibe-trading": {
      "command": "vibe-trading-mcp"
    }
  }
}
```

</details>

<details>
<summary><b>OpenClaw</b></summary>

Tambahkan ke `~/.openclaw/config.yaml`:

```yaml
skills:
  - name: vibe-trading
    command: vibe-trading-mcp
```

Untuk smoke test research-only pertama, konfirmasikan discovery tool lalu jalankan request data market atau backtest sebelum memilih profil connector trading.
Tool riset inti dapat berjalan tanpa kredensial broker; tool `trading_*` berbasis connector
sebaiknya hanya digunakan setelah Anda sengaja memilih dan memeriksa profil connector.
`run_swarm` memerlukan LLM key.
profile. `run_swarm` requires an LLM key.

</details>

<details>
<summary><b>Cursor / Windsurf / client MCP lainnya</b></summary>

```bash
vibe-trading-mcp                   # stdio (default)
vibe-trading-mcp --transport http  # Streamable HTTP (current MCP spec default) at http://127.0.0.1:8900/mcp
vibe-trading-mcp --transport sse   # legacy SSE (deprecated) for older clients
```

Untuk client HTTP (QwenPaw, dan client mana pun yang melakukan negosiasi dengan POST
`InitializeRequest`), gunakan `--transport http` dan arahkan client ke satu endpoint
`/mcp` — mis. `http://127.0.0.1:8900/mcp`. **Jangan** arahkan client HTTP
ke `/sse`; path tersebut milik transport SSE dua-endpoint yang deprecated
dan akan mengembalikan `405 Method Not Allowed` saat `POST`. Override bind address
dengan `--host` / `--port`.

</details>

**Tool MCP yang diekspos (74):** `list_skills`, `load_skill`, `start_research_goal`, `get_research_goal`, `add_goal_evidence`, `update_research_goal_status`, `backtest`, `factor_analysis`, `alpha_zoo`, `alpha_bench`, `analyze_options`, `analyze_options_payoff`, `pattern_recognition`, `read_url`, `read_document`, `web_search`, `write_file`, `read_file`, `list_strategies`, `query_strategies`, `get_strategy_evidence`, `refresh_strategy_evidence`, `trading_connections`, `trading_select_connection`, `trading_check`, `trading_account`, `trading_positions`, `trading_orders`, `trading_quote`, `trading_history`, `list_swarm_presets`, `run_swarm`, `get_market_data`, `get_fund_flow`, `get_dragon_tiger`, `get_northbound_flow`, `get_margin_trading`, `get_block_trades`, `get_shareholder_count`, `get_lockup_expiry`, `get_sector_info`, `get_research_reports`, `get_stock_news`, `get_sec_filings`, `get_financial_statements`, `get_options_chain`, `get_stock_profile`, `screen_market`, `search_symbol`, `get_macro_series`, `iwencai_search`, `qveris_search`, `qveris_inspect`, `qveris_execute`, `get_institutional_holdings`, `etf_holdings`, `prediction_market`, `research_papers`, `get_swarm_status`, `get_run_result`, `list_runs`, `reap_stale_runs`, `retry_run`, `analyze_trade_journal`, `extract_shadow_strategy`, `run_shadow_backtest`, `render_shadow_report`, `scan_shadow_signals`, `quantlib_call`, `cashflow_performance`, `orderbook_depth`, `sentiment`, `technical_indicators`, `get_fundamentals`.

### Tool MCP eksternal untuk SWARM

Worker `run_swarm` dapat memanggil tool yang disetujui operator dari server MCP eksternal. Konfigurasikan allowlist sisi server di `VIBE_TRADING_SWARM_AGENT_CONFIG`, `~/.vibe-trading/swarm-agent.json`, atau fallback `~/.vibe-trading/agent.json`; lalu daftarkan tool remote di preset swarm menggunakan nama wrapper MCP lokal, misalnya `mcp_internal_kb_search`. `variables` yang diberikan caller tetap hanya menjadi data template dan tidak dapat menyuntikkan URL MCP, command, environment variable, atau override allowlist.

<details>
<summary><b>Instal dari ClawHub (satu perintah)</b></summary>

```bash
npx clawhub@latest install vibe-trading --force
```

> `--force` diperlukan karena skill merujuk ke API eksternal sehingga memicu scan otomatis VirusTotal. Kode sepenuhnya open-source dan aman untuk diperiksa.

Ini mengunduh skill + config MCP ke direktori skill agent Anda. Tidak perlu clone.

Jelajahi di ClawHub: [clawhub.ai/skills/vibe-trading](https://clawhub.ai/skills/vibe-trading)

</details>

<details>
<summary><b>OpenSpace — skill yang berkembang sendiri</b></summary>

Semua 90 skill finansial dipublikasikan di [open-space.cloud](https://open-space.cloud) dan berkembang secara otonom melalui engine self-evolution OpenSpace.

Untuk menggunakan OpenSpace, tambahkan kedua server MCP ke config agent Anda:

```json
{
  "mcpServers": {
    "openspace": {
      "command": "openspace-mcp",
      "toolTimeout": 600,
      "env": {
        "OPENSPACE_HOST_SKILL_DIRS": "/path/to/vibe-trading/agent/src/skills",
        "OPENSPACE_WORKSPACE": "/path/to/OpenSpace"
      }
    },
    "vibe-trading": {
      "command": "vibe-trading-mcp"
    }
  }
}
```

OpenSpace akan menemukan seluruh 90 skill secara otomatis, mengaktifkan auto-fix, auto-improve, dan sharing komunitas. Cari skill Vibe-Trading melalui `search_skills("finance backtest")` pada agent mana pun yang terhubung OpenSpace.

</details>

---

### MetaTrader 5 (Exness dan broker MT5 lainnya)

Terhubung ke **terminal MT5 yang berjalan lokal** melalui package resmi `MetaTrader5` (**khusus Windows**):

```bash
pip install "vibe-trading-ai[mt5]"
```

Konfigurasikan `~/.vibe-trading/mt5.json` (buat sendiri; `chmod 600` jika didukung):

```json
{
  "login": 12345678,
  "password": "...",
  "server": "Exness-MT5Trial8",
  "symbol_suffix": "m",
  "max_order_volume": 1.0,
  "max_order_notional_usd": 10000
}
```

Lalu:

```bash
vibe-trading connector use mt5-paper-sdk
vibe-trading connector check
vibe-trading connector account
vibe-trading connector quote EURUSD
vibe-trading connector history EURUSD
```

| Profil | Akun | Order |
|---------|---------|--------|
| `mt5-paper-sdk` | demo | read-only |
| `mt5-live-sdk-readonly` | real | read-only |
| `mt5-paper-trade` | demo | penempatan langsung (guard ukuran per-order connector berlaku) |
| `mt5-live-trade` | real | dibatasi mandat + penghentian darurat |

Batas keamanan: **"paper" berarti akun demo milik broker sendiri**, diverifikasi ulang pada setiap call — terminal melaporkan `account_info().trade_mode` dan nomor akun login, sehingga profil paper yang diarahkan ke akun real-money (atau sebaliknya) ditolak langsung. MT5 mengukur order dalam **lot** (1 lot EURUSD = 100.000 EUR); live mandate gate memberi harga lot melalui hook USD connector, dan guard `max_order_volume` / `max_order_notional_usd` milik connector berlaku pada demo maupun live serta fail-closed jika notional tidak dapat dihitung. Pada akun hedging (default Exness), order berlawanan **membuka posisi hedge** — tutup berdasarkan ticket (berikan position ticket ke `trading_cancel_order`) agar fill terikat pada posisi itu dan hanya dapat mengurangi eksposur. Jalur rollback / halt: penghentian darurat memblokir order live baru, sedangkan pembatalan tetap tersedia dan ditulis ke audit log. Batas mandat berdenominasi USD; mata uang akun non-USD tetap dimargin oleh broker dalam mata uangnya sendiri.

Loader data market `mt5` — kepala fallback chain forex — memakai `mt5.json` yang sama. Tanpa file tersebut, loader attach secara read-only ke terminal terakhir yang sudah login.

---

## 🔌 Connector Public API eToro

Terhubung ke [Public API eToro](https://builders.etoro.com/) untuk akun demo dan real melalui pasangan API key (`x-api-key` + `x-user-key`). Environment demo dan real dipisahkan secara struktural: demo key hanya dapat mengakses path API `/demo`.

Konfigurasikan `~/.vibe-trading/etoro.json` (buat sendiri; `chmod 600` jika didukung):

```json
{
  "api_key": "YOUR_PUBLIC_API_KEY",
  "user_key": "YOUR_USER_KEY",
  "profile": "paper"
}
```

Atau atur `ETORO_API_KEY` dan `ETORO_USER_KEY` di `~/.vibe-trading/.env`.

Lalu:

```bash
vibe-trading connector use etoro-paper-sdk
vibe-trading connector check
vibe-trading connector account
vibe-trading connector positions
vibe-trading connector quote BTC
```

| Profil | Akun | Order |
|---------|---------|--------|
| `etoro-paper-sdk` | demo | read-only |
| `etoro-live-sdk-readonly` | real | read-only |
| `etoro-paper-trade` | demo | penempatan langsung pada path demo |
| `etoro-live-trade` | real | dibatasi mandat + penghentian darurat |

Pencarian simbol menggunakan search `internalSymbolFull` eToro (mis. `BTC` → instrument id `100000`). Gunakan tool agent `etoro_search_instruments` untuk me-resolve ticker sebelum trading.

Batas keamanan: demo dan real dipisahkan berdasarkan path dan terikat pada key (`paper_guard: path_separated_key_bound`). Aksi live yang meningkatkan risiko (open dan copy-start/increase) memerlukan mandat terotorisasi, state halt yang clear, dan akun USD yang terverifikasi untuk enforcement copy-notional. Penutupan posisi penuh/parsial yang tervalidasi, pembatalan open order, dan penutupan copy tetap tersedia ketika halted dan semuanya dicatat di audit log. Membatalkan pending close atau mengedit stop posisi hanya tersedia di paper: jalur live fail-closed karena operasi tersebut dapat meningkatkan eksposur atau memindahkan margin tambahan tanpa data API yang cukup untuk mengukur incremental USD risk. Nilai copy berdenominasi mata uang akun eToro, dan setiap copy start/adjust memerlukan reference id URL-safe 1–35 karakter yang diberikan caller untuk polling. Tool write khusus eToro (`etoro_close_position`, `etoro_copy_*`, dll.) hanya tersedia sebagai agent tool — tidak diekspos lewat MCP atau CLI. Rollback: revert commit connector atau nonaktifkan profil; halt memblokir aksi live baru yang meningkatkan risiko.

---

## 🔌 Memuat Tool dari Server MCP Eksternal (Mode MCP Client)

> **Arah ini kebalikan dari Plugin MCP di atas.**
> Plugin MCP memungkinkan agent *lain* memanggil tool Vibe-Trading.
> Bagian ini memungkinkan agent bawaan Vibe-Trading memanggil tool dari server MCP eksternal *Anda*.

### Mulai cepat

Buat `~/.vibe-trading/agent.json`:

```json
{
  "mcpServers": {
    "my-server": {
      "command": "uvx",
      "args": ["my-mcp-server"]
    }
  }
}
```

Jalankan perintah CLI apa pun — tool dari server eksternal biasa otomatis disuntikkan ke registry agent setelah tool lokal:

```bash
vibe-trading run "use my-server to do X"
```

### Probe read-only MCP resmi IBKR

Vibe-Trading dapat terhubung langsung ke endpoint MCP remote resmi Interactive Brokers
dalam mode read-only. Tambahkan ini ke `~/.vibe-trading/agent.json`:

```json
{
  "mcpServers": {
    "ibkr": {
      "type": "streamableHttp",
      "url": "https://api.ibkr.com/v1/api/mcp-public",
      "auth": {
        "type": "oauth",
        "scopes": ["mcp.read"],
        "clientName": "Vibe-Trading",
        "cacheDir": "~/.vibe-trading/live/ibkr/oauth"
      },
      "enabledTools": ["*"]
    }
  }
}
```

Lalu mulai flow OAuth di browser:

```bash
vibe-trading connector authorize ibkr-live-official-mcp-readonly
```

Wildcard hanya diterima untuk probe `mcp.read` IBKR. Otorisasi profil ini
mengonfirmasi akses ke read scope resmi IBKR; call generik `trading_account`
dan `trading_positions` tetap dinonaktifkan sampai IBKR memublikasikan nama tool read
yang stabil dan dapat dipetakan Vibe-Trading dengan aman. Config yang menambahkan `mcp.write` harus
mem-pin allowlist tool eksplisit dan tetap melewati live order guard.

Jika IBKR memberikan OAuth client yang sudah diregistrasikan, tambahkan `clientId` dan `clientSecret`
di dalam `auth`.

### Connector trading: jalur tercepat

Bagi pengguna yang tidak dapat menunggu approval OAuth client IBKR, hubungkan ke sesi TWS atau IB Gateway lokal. Kredensial tetap berada di aplikasi desktop IBKR; Vibe-Trading hanya terhubung ke `127.0.0.1` dan mengeksposnya sebagai profil connector.
TWS or IB Gateway session. Credentials stay inside IBKR's desktop app; Vibe-
Trading only connects to `127.0.0.1` and exposes it as a connector profile.

Instal SDK opsional:

```bash
pip install "vibe-trading-ai[ibkr]"
```

Buka TWS paper trading atau IB Gateway paper, aktifkan client API socket, lalu jalankan:

```bash
vibe-trading connector list
vibe-trading connector use ibkr-paper-local
vibe-trading connector configure ibkr-paper-local --yes
vibe-trading connector check
vibe-trading connector account
vibe-trading connector positions
vibe-trading connector orders
vibe-trading connector quote AAPL
vibe-trading connector history AAPL --duration "30 D" --bar-size "1 day"
```

Port lokal default:

| App | Paper | Live read-only |
|-----|-------|----------------|
| TWS | `7497` | `7496` |
| IB Gateway | `4002` | `4001` |

Agent mengekspos tool connector-scoped bernama `trading_connections`,
`trading_select_connection`, `trading_check`, `trading_account`,
`trading_positions`, `trading_orders`, `trading_quote`, dan `trading_history`.
Tool MCP raw dari live broker tidak didaftarkan langsung sebagai `mcp_<broker>_*`.
Tidak ada tool penempatan order IBKR yang didaftarkan.

### 🔐 Mode TAP — isolasi kredensial penuh & write yang disetujui manusia

**Opt-in, nonaktif secara default.** Jika variable `TAP_*` di bawah tidak diatur,
connector berperilaku seperti sebelumnya (SDK broker langsung) — tidak ada perubahan.

[TAP](https://tap.human.tech) (Tool Authorization Protocol) adalah proxy kredensial:
agent tidak pernah memegang secret API broker mentah, dan write yang berdampak
dibatasi oleh **persetujuan manusia**. Dengan mode TAP aktif, **setiap** call Alpaca — penempatan order,
cancel, dan read (account/positions/orders/quote/bars) — dikirim
ke endpoint `/forward` proxy TAP, bukan SDK broker; TAP menyuntikkan
key asli di sisi server lalu meneruskan request upstream.

- Proses agent **tidak memegang key Alpaca sama sekali** — bahkan tidak memerlukan
  `alpaca-py` — karena seluruh egress melewati TAP. Secret
  direferensikan berdasarkan nama (`<CREDENTIAL:alpaca.key_id>`) dan TAP menggantikannya.
- **Write diblokir sampai ada persetujuan manusia.** Order atau cancel tidak dapat mencapai broker
  tanpa persetujuan manusia; bahkan prompt-injected "buy now" akan ditahan, dan
  penolakan berarti request tidak pernah mencapai Alpaca. Order membawa
  `client_order_id` deterministik, sehingga retry saat approval race dideduplikasi dan tidak
  membuat order ganda.
- **Read disetujui otomatis.** Account/positions/orders/quote/bars adalah GET yang TAP
  teruskan tanpa langkah manusia — ini adalah *isolasi* kredensial (tidak ada key di
  proses), bukan gate, sehingga friksi tambahannya nyaris nol.
- `allowed_hosts` pada kredensial TAP mengikat ke mana key dapat dikirim, sehingga
  target yang dimanipulasi ditolak (403) sebelum injection.

**Aktifkan:**

1. Di dashboard TAP, buat kredensial **multi-secret** bernama `alpaca`
   yang berisi pasangan key Alpaca Anda sebagai field `key_id` dan `secret_key`, ditetapkan ke
   agent Anda, dengan allowed host `paper-api.alpaca.markets` (atau host live
   `api.alpaca.markets`) **dan** `data.alpaca.markets` (host data market yang digunakan
   oleh quote/bars). Gunakan **kredensial TAP terpisah untuk paper dan live** (mis.
   `alpaca-paper` / `alpaca-live`, dipilih melalui `TAP_ALPACA_CREDENTIAL`), masing-masing
   dengan `allowed_hosts` terikat ke API host sendiri — TAP kemudian secara struktural
   menolak mengirim paper key ke live host dan sebaliknya, menjaga
   pemisahan paper/live tetap tegas end-to-end.
2. Tambahkan ke `agent/.env`:

| Variable | Wajib | Deskripsi |
|----------|:--------:|-------------|
| `TAP_PROXY_URL` | Ya | Base URL proxy TAP (mis. `https://proxy.tap.human.tech`) |
| `TAP_AGENT_KEY` | Ya | API key agent TAP Anda (secret) |
| `TAP_ALPACA_CREDENTIAL` | Tidak | Nama kredensial TAP untuk Alpaca (default `alpaca`) |
| `TAP_APPROVAL_TIMEOUT` | Tidak | Detik menunggu keputusan manusia (default `300`) |

Saat write dibuat, setujui atau tolak melalui channel TAP Anda (Telegram /
dashboard). Order/cancel yang disetujui diteruskan ke Alpaca; yang ditolak atau
timeout mengembalikan error dan **tidak pernah dikirim**.

> **Limitasi yang diketahui — approval race.** Jika manusia menyetujui tepat di batas
> `TAP_APPROVAL_TIMEOUT`, TAP dapat meneruskan order sementara polling
> sudah berhenti: gate kemudian melaporkan error walau order mencapai
> broker, dan counter `max_trades_per_day` kurang satu. `client_order_id`
> deterministik mencegah retry membuat order ganda;
> jika Anda bergantung pada batas trade-per-hari yang ketat, periksa open order setelah error
> timeout TAP sebelum retry.

**Scope:** mencakup **penempatan order, cancel, dan lima read** Alpaca — seluruh
egress connector, sehingga proses tidak memegang key pada jalur apa pun. Broker
bertanda tangan HMAC (Binance/OKX) adalah follow-up (client-side signing tidak cocok dengan injection
egress murni). Hook bersifat aditif — berada di dalam connector Alpaca dan
tidak mengubah live mandate gate.

### Referensi config

| Field | Tipe | Default | Deskripsi |
|-------|------|---------|-------------|
| `type` | string | diinfer untuk stdio; wajib untuk HTTP | Hilangkan untuk stdio, atau atur `sse` / `streamableHttp` untuk server berbasis URL. |
| `command` | string | wajib untuk stdio | Executable yang dijalankan untuk server stdio. Tidak valid untuk server `sse` / `streamableHttp`. |
| `args` | array | `[]` | Argumen command-line khusus server stdio. |
| `env` | object | `{}` | Environment variable tambahan yang digabungkan ke env subprocess khusus server stdio. |
| `url` | string | wajib untuk `sse` / `streamableHttp` | URL endpoint remote SSE / streamable HTTP. Tidak digunakan untuk server stdio. |
| `headers` | object | `{}` | Header HTTP tambahan khusus server `sse` / `streamableHttp`. |
| `toolTimeout` | number | `30` | Timeout per tool call dalam detik |
| `initTimeout` | number | tidak diatur (`max(toolTimeout, 30)`) | Timeout inisialisasi MCP / otorisasi OAuth dalam detik. Gunakan untuk otorisasi browser lambat tanpa memperlebar timeout tool call biasa. |
| `enabledTools` | array | `["*"]` | Allowlist tool. Gunakan `["*"]` untuk mengekspos semua tool dari server |

Lokasi file config: `~/.vibe-trading/agent.json` (JSON atau YAML).

Untuk transport berbasis URL, `type` wajib. Agent tidak lagi menebak antara SSE dan streamable HTTP dari suffix URL.

### Override per sesi (API)

Saat membuat sesi melalui API, Anda dapat memberikan `mcpServers` di dalam `session.config` untuk memperluas atau override config global hanya untuk sesi tersebut:

```json
{
  "config": {
    "mcpServers": {
      "research-server": {
        "command": "uvx",
        "args": ["research-mcp"],
        "enabledTools": ["search", "fetch"]
      }
    }
  }
}
```

### Penamaan tool

Tool remote biasa diekspos dengan nama stabil: `mcp_<server>_<tool>`.
Server MCP live-broker tetap berada di balik surface connector `trading_*`.

Jika dua nama server menghasilkan prefix lokal ASCII-safe yang sama (mis. `foo-bar` dan `foo_bar` sama-sama menjadi `foo_bar`), suffix hash deterministik ditambahkan pada segmen server agar nama tetap unik. Operator menerima warning:

```
WARNING: Configured MCP server 'foo-bar' collides with another server after local name
normalization. Using local tool prefix 'mcp_foo_bar_<hash>_<tool>' to keep generated
tool names unique. Rename the server in agent config if you want a different prefix.
```

### Batas v1

| Batas | Detail |
|-------|--------|
| Transport | stdio, SSE, dan streamable HTTP |
| Eksekusi | hanya serial — tool MCP tidak pernah masuk jalur parallel read-only |
| Surface | hanya tool (resource dan prompt dikecualikan pada v1) |
| Hot reload | tidak didukung — restart proses untuk mengambil perubahan config |
| Jalur Swarm | tool MCP tidak tersedia di dalam registry Swarm worker pada v1 |

---

## 📁 Struktur Proyek

<details>
<summary><b>Klik untuk memperluas</b></summary>

```
Vibe-Trading/
├── agent/                          # Backend (Python)
│   ├── cli/                        # CLI package — interactive TUI + subcommands
│   ├── api_server.py               # FastAPI server — runs, sessions, upload, swarm, SSE
│   ├── mcp_server.py               # MCP server — 74 tools for OpenClaw / Claude Desktop
│   │
│   ├── src/
│   │   ├── agent/                  # ReAct agent core
│   │   │   ├── loop.py             #   5-layer compression + read/write tool batching
│   │   │   ├── context.py          #   system prompt + auto-recall from persistent memory
│   │   │   ├── skills.py           #   skill loader (90 bundled + user-created via CRUD)
│   │   │   ├── tools.py            #   tool base class + registry
│   │   │   ├── memory.py           #   lightweight workspace state per run
│   │   │   ├── frontmatter.py      #   shared YAML frontmatter parser
│   │   │   └── trace.py            #   execution trace writer
│   │   │
│   │   ├── memory/                 # Cross-session persistent memory
│   │   │   └── persistent.py       #   file-based memory (~/.vibe-trading/memory/)
│   │   │
│   │   ├── tools/                  # 110 auto-discovered agent tools
│   │   │   ├── backtest_tool.py    #   run backtests
│   │   │   ├── remember_tool.py    #   cross-session memory (save/recall/forget)
│   │   │   ├── skill_writer_tool.py #  skill CRUD (save/patch/delete/file)
│   │   │   ├── session_search_tool.py # FTS5 cross-session search
│   │   │   ├── swarm_tool.py       #   launch swarm teams
│   │   │   ├── web_search_tool.py  #   DuckDuckGo web search
│   │   │   └── ...                 #   bash, file I/O, factor analysis, options, alpha browser + bench, etc.
│   │   │
│   │   ├── factors/                # Alpha Zoo — 462 alphas across 5 families
│   │   │   ├── base.py             #   19 operators (rank/scale/ts_*/delta/decay_linear/safe_div/vwap)
│   │   │   ├── registry.py         #   AST-only metadata load + lazy compute + sanity gates
│   │   │   ├── bench_runner.py     #   IC + alive/reversed/dead categorisation
│   │   │   └── zoo/                #   qlib158 (154) + alpha101 (101) + gtja191 (191) + academic (12) + fundamental (4)
│   │   │
│   │   ├── api/                    # FastAPI route modules
│   │   │   └── alpha_routes.py     #   /alpha/list, /alpha/{id}, /alpha/bench, SSE stream
│   │   │
│   │   ├── skills/                 # 90 finance skills in 9 categories (SKILL.md each)
│   │   ├── swarm/                  # Swarm DAG execution engine
│   │   │   └── presets/            #   30 swarm preset YAML definitions
│   │   ├── session/                # Multi-turn chat + FTS5 session search
│   │   └── providers/              # LLM provider abstraction
│   │
│   └── backtest/                   # Backtest engines
│       ├── engines/                #   9 engines + composite cross-market engine + options_portfolio
│       ├── loaders/                #   28 sources: tushare, okx, nobitex, wallex, binance, yfinance, akshare, baostock, tencent, mootdx, ccxt, futu, pykrx, local, eastmoney, sina, stooq, yahoo, finnhub, alphavantage, tiingo, fmp, longbridge, mt5, qveris, india_broker, tickerall, gildata
│       │   ├── base.py             #   DataLoader Protocol
│       │   └── registry.py         #   Registry + auto-fallback chains
│       └── optimizers/             #   MVO, equal vol, max div, risk parity
│
├── frontend/                       # Web UI (React 19 + Vite + TypeScript)
│   └── src/
│       ├── pages/                  #   Home, Agent, AlphaZoo, RunDetail, Compare, Correlation, Settings
│       ├── components/             #   chat, charts, layout
│       └── stores/                 #   Zustand state management
│
├── Dockerfile                      # Multi-stage build
├── docker-compose.yml              # One-command deploy
├── pyproject.toml                  # Package config + CLI entrypoint
├── tools/                          # Repo-level CI helpers
│   └── ci_grep_gates.sh            # rejects yaml.load / trademark / per-stock-data leaks
└── LICENSE                         # MIT
```

</details>

---

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
  </tr>
</table>

---

<a id="-roadmap"></a>
## 🗺 Roadmap

> Kami merilis dalam beberapa fase. Item dipindahkan ke [Issues](https://github.com/HKUDS/Vibe-Trading/issues) saat pengerjaan dimulai.

| Fase | Fitur | Status |
|-------|---------|--------|
| **Trust Layer** | Run card reproducible dibuat dan ditampilkan di Run Detail; v1 menambahkan tool trace dan citation | v0 Dirilis |
| **Hypothesis Registry** | Hipotesis riset persisten dengan status lifecycle, sumber data, skill, link run-card, dan catatan invalidasi | Backend MVP Dirilis |
| **Research Autopilot** | Loop riset manual-first: hipotesis → backtest deterministik → laporan bukti | Fase 1–3 Dirilis |
| **Data Bridge** | Bawa data sendiri: connector CSV/Parquet/SQL lokal dengan schema mapping | Loader lokal Dirilis |
| **Options Lab** | Vol surface, dashboard Greeks, explorer payoff/scenario | Tool analitik payoff/scenario **Dirilis**; surface/dashboard Direncanakan |
| **Portfolio Studio** | Risk x-ray, constraint, optimizer turnover-aware, catatan rebalance | Optimizer turnover-aware **Dirilis 0.1.11**; sisanya Direncanakan |
| **Alpha Zoo** | 462 alpha siap pakai (Qlib 158 + Kakushadze 101 + GTJA 191 + akademik + fundamental) dengan bench satu baris, integrasi agent, dan Web UI | **Dirilis 0.1.8**, diperluas hingga 0.1.12 |
| **Strategy Development Manager** | Daftarkan paper / riset broker sebagai faktor & strategi dengan store persisten + lifecycle decay IC/Sharpe otomatis | **Dirilis 0.1.11** |
| **Correlation Regime** | Timeline regime edge-density + hysteresis di `/correlation` — deteksi saat market menyatu menjadi satu blok | **Dirilis 0.1.12** |
| **Research Delivery** | Brief terjadwal dan sesi riset live melalui Slack / Telegram / channel IM bergaya email | Scheduler + IM Runtime Dirilis |
| **Community** | Skill, preset, dan strategy card yang dapat dibagikan | Eksplorasi |

---

<a id="contributing"></a>
## Kontribusi

Kami menyambut kontribusi! Lihat [CONTRIBUTING.md](CONTRIBUTING.md) untuk panduan.

**Good first issues** diberi label [`good first issue`](https://github.com/HKUDS/Vibe-Trading/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) — pilih satu dan mulai.

Ingin berkontribusi lebih besar? Lihat [Roadmap](#-roadmap) di atas dan buka issue untuk berdiskusi sebelum mulai.

---

## Kontributor

Terima kasih kepada semua orang yang telah berkontribusi pada Vibe-Trading!

Kontributor dan kredit siklus v0.1.14 terbaru:

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

<details>
<summary>v0.1.12 cycle contributors</summary>

- @santhreal — a 30-PR correctness sweep: strict-JSON / finite-number hardening across metrics, factors, pattern, and options (#764/#765/#766/#767/#739/#740/#744), loader correctness (#761 yahoo 1m bars), and session / journal robustness (#762/#763/#768/#769/#770)
- @xkam7ar — broad reliability across packaging, web, scheduler, swarm, and CLI (#584), cancellation before the first AgentLoop iteration (#641, closes #638), QVeris session budget + atomic credit accounting (#685/#686), CI / OOS gates (#630/#632), and journal month-filter / side-parse fixes (#626/#628)
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
<summary>v0.1.11 cycle contributors</summary>

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
- @warren618 / Haozhe Wu — the fundamental factor layer (PIT-safe SEC panels), the QVeris premium track, the IM channel runtime, India-equity integration review, CN search fallbacks, and release integration

</details>

<details>
<summary>v0.1.10 cycle contributors</summary>

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

---

## Disclaimer

Vibe-Trading adalah software riset dan trading. Ini bukan saran investasi, tidak menyimpan dana, dan tidak menjalankan execution venue. Trading melalui channel broker yang Anda otorisasi secara eksplisit (mis. Robinhood Agentic Trading) hanya terjadi dalam batas yang Anda tetapkan dan dapat dihentikan kapan saja. Kapabilitas broker-trading ini masih eksperimental dan belum kami verifikasi terhadap akun broker nyata — gunakan dengan risiko Anda sendiri. Kinerja masa lalu tidak menjamin hasil di masa depan.

## Lisensi

Lisensi MIT — lihat [LICENSE](LICENSE)

---

<p align="center">
  ⭐ Jika <b>Vibe-Trading</b> membantu riset Anda, satu star membantu lebih banyak orang menemukannya.
</p>

---

<p align="center">
  Terima kasih telah mengunjungi <b>Vibe-Trading</b> ✨
</p>
<p align="center">
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.Vibe-Trading&style=flat" alt="pengunjung"/>
</p>

