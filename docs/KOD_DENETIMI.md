# LucidLectorPDF — Kod Denetimi

**Tarih:** 20 Ağustos 2026 · **Sürüm:** 1.1.0 · **Kapsam:** `main.py`, `pdf_reader/` (4.450 satır), `tools/`, build dosyaları

---

## 0. Yapılan temizlik

Depo 772 MB'tan 178 MB'a indi. Silinenler: `dist/AkinelPDF-v0.1…v0.4.exe`, `dist/AkinelPDF.exe`, 20 adet `dist/RCX*.tmp`, `build/AkinelPDF/`, `build/LuciLector/`, `AkinelPDF.spec`, `LuciLector.spec`. Korunanlar: `dist/LucidLectorPDF.exe`, `build/LucidLectorPDF/`, `LucidLectorPDF.spec`.

`.pycache_tmp/` (908 KB) dokunulmadı — istenirse silinebilir, ayrıca `.gitignore`'a eklenmeli.

---

## 1. Hatalar

Aşağıdakiler önem sırasına göre. "Kritik" = veri kaybı veya kullanıcının gördüğü bozulma.

> **§1.1 ve §1.2 düzeltildi** (20 Ağustos 2026). Ayrıntı için bölüm 8'e bakın. Diğer maddeler açık.

### 1.1 ✅ ÇÖZÜLDÜ — KRİTİK — Bölünmüş görünümde yedi özellik yanlış panele gidiyor

`main_window.py` sınıfın tamamında `_active_view` (aktif panel) yönlendirmesi kurulmuş, ama yedi yerde doğrudan `self._view` (birincil panel) sabitlenmiş kalmış. Ctrl+\ ile ikinci panel açılıp orada çalışılınca bu özellikler sessizce yanlış panelde çalışır:

| Satır | Kod | Sonuç |
|---|---|---|
| 272 | `_act_paragraph.toggled.connect(self._view.set_paragraph_mode)` | Ctrl+P ikinci panelde hiç çalışmaz |
| 286, 734 | `_act_dual.toggled.connect(self._view.set_dual_view)` | Ctrl+2 ikinci panelde çalışmaz |
| 450–452 | `_search.next/prev/closed → self._view` | Arama gezinmesi hep birinci panelde |
| 877–880 | `_run_search` → `self._view.doc.search(...)` | Ctrl+F ikinci panelin belgesinde aramaz |
| 846 | `self._view.rotate(delta)` | Döndürme birinci paneli döndürür, **kirli bayrağı ikinci panele yazar** (847) → yanlış dosya için kaydet sorusu |
| 462–463 | `sentence_hovered → self._view.show_hover_highlight` | Çeviri panelinden PDF'e hover vurgusu ikinci panelde yok (ters yön 789–794'te bağlı — asimetrik) |
| 894–895 | `_show_translation` → `self._view.clear_hover_highlight()` / `set_translation_context()` | İkinci panelde çeviri yapılınca cümle bağlamı birinci panele kuruluyor |

**Düzeltme:** hepsini `self._active_view`'a çevirin. Sinyal bağlantıları için doğrudan bağlamak yerine ara metot kullanın:

```python
# _wire() içinde
self._search.next_requested.connect(lambda: self._active_view.search_next())
self._search.prev_requested.connect(lambda: self._active_view.search_prev())
self._search.closed.connect(lambda: self._active_view.clear_search())
self._act_paragraph.toggled.connect(lambda on: self._active_view.set_paragraph_mode(on))
```

`_rotate_pages` ve `_run_search` içindeki `self._view.doc` kontrollerini de `self._active_view.doc` yapın.

### 1.2 ✅ ÇÖZÜLDÜ — KRİTİK — Render hatası sayfayı gri bırakıyor ve yeniden denenmiyor

`pdf_view.py:58-77` — `_PageRenderTask.run()` herhangi bir istisnada sinyal **yaymadan** sessizce çıkıyor. `_pending_renders` kümesinden o sayfa yalnızca `_on_page_ready` içinde (485) siliniyor. Yani render bir kez başarısız olursa:

1. `_pending_renders` içinde sayfa asılı kalır,
2. `_ensure_page_rendered` (457) her çağrıda erken döner,
3. sayfa yeniden denenmez — kullanıcı gri bir dikdörtgen görür, hata mesajı yoktur.

Kilitlenme mutlak değil: `clear()` (321) ve `_rebuild()` (349) kümeyi temizliyor, dolayısıyla yakınlaştırma, döndürme veya görünüm değişimi durumu sıfırlar. Ama aynı yakınlaştırma seviyesinde kaydırıp durduğunuz sürece sayfa kalıcı olarak gri kalır ve neden olduğuna dair hiçbir işaret yoktur.

Bozuk sayfa, ağ sürücüsünün kopması, dosyanın taşınması, bellek yetersizliği hep bu duruma yol açar.

**Düzeltme:** başarısızlık sinyali ekleyin ve `_pending_renders`'ı `finally` ile temizleyin:

```python
class _RenderSignals(QObject):
    done = pyqtSignal(int, object, int)     # page_index, QImage, generation
    failed = pyqtSignal(int, int, str)      # page_index, generation, error
```

```python
def run(self) -> None:
    doc = None
    try:
        ...
        self._signals.done.emit(self._page_index, img, self._generation)
    except Exception as e:
        self._signals.failed.emit(self._page_index, self._generation, str(e))
    finally:
        if doc is not None:
            try: doc.close()
            except Exception: pass
```

`failed` slotu `_pending_renders.discard(page_index)` yapmalı ki sonraki kaydırmada yeniden denensin.

### 1.3 YÜKSEK — Her cümle geçişinde tüm belge taranıyor

`pdf_view.py:559-592` `show_hover_highlight()` ve `603-622` `set_translation_context()`, `PdfDocument.search()` çağırıyor. `search()` (`pdf_document.py:174-184`) **belgedeki her sayfayı** dolaşır ve bunu GUI iş parçacığında yapar.

- `show_hover_highlight`: çeviri panelinde imleç yeni bir cümleye geçtiğinde 1 tam belge taraması (fare hareketi başına değil — `sentence_hovered` sinyali tetikliyor). Sonuç boşsa bir tane daha (fallback, 575).
- `set_translation_context`: bir paragraf çevrildiğinde, paragraftaki 8 karakterden uzun **her cümle için** 1–2 tam belge taraması. 20 cümlelik bir paragraf → 500 sayfalık PDF'te 20.000'e varan sayfa taraması, tek seferde, arayüz donmuş halde. Asıl darboğaz burası.

**Düzeltme:** aramayı görünür sayfa civarına daraltın:

```python
def search_pages(self, query: str, pages: Iterable[int]) -> dict[int, list[fitz.Rect]]:
    out = {}
    for i in pages:
        rects = self.doc[i].search_for(query, quads=False)
        if rects:
            out[i] = rects
    return out
```

Çağrı tarafında `self._page_indices_near_viewport(RENDER_KEEP_VIEWPORTS)` sonucunu geçin. Hover vurgusu zaten yalnızca görünür alanda anlamlı. `set_translation_context` için ayrıca sonucu cümle bazında önbelleğe alın.

### 1.4 YÜKSEK — Çeviri ve render aynı iş parçacığı havuzunu paylaşıyor

`pdf_view.py:292` ve `translator.py:72` — ikisi de `QThreadPool.globalInstance()`. Havuzun sınırı `idealThreadCount` (tipik 8). Google Translate isteklerinin zaman aşımı yok; ağ yavaşladığında birkaç asılı çeviri havuzu doldurur ve **sayfa render'ı tamamen durur** — kullanıcı gri sayfalar görür, nedenini anlamaz.

**Düzeltme:** `PdfView` için özel havuz:

```python
self._render_pool = QThreadPool()
self._render_pool.setMaxThreadCount(max(2, QThread.idealThreadCount() - 1))
```

Ayrıca `GoogleTranslator(..., timeout=...)` desteklemiyorsa `_Worker.run` içine `requests` seviyesinde zaman aşımı veya `QTimer` tabanlı iptal ekleyin.

### 1.5 ORTA — Geri al/ileri al diğer panele yansımıyor

`_add_annotation` (941) `self._rerender_page()` kullanıyor — aynı dosyayı gösteren diğer paneli de tazeliyor. Ama `_undo` (973) ve `_redo` (989) doğrudan `self._active_view.rerender_page(pi)` çağırıyor. Aynı PDF iki panelde açıkken geri alma yaptığınızda diğer panelde vurgu ekranda kalmaya devam eder.

**Düzeltme:** ikisinde de `self._rerender_page(pi)` kullanın.

### 1.6 ORTA — Şifreli PDF için anlamlı hata yok

`pdf_document.py:41` — `fitz.open()` şifreli belgede istisna atmaz; `doc.needs_pass` True döner. Kimlik doğrulanmadan sayfa erişimi PyMuPDF içinde istisnaya düşer, bu istisna da §1.2'deki sessiz `except` tarafından yutulur. Sonuç: kullanıcı gri sayfalardan oluşan bir belge görür ve dosyanın parola korumalı olduğunu asla öğrenmez.

**Düzeltme:**

```python
self.doc = fitz.open(self.path)
if self.doc.needs_pass:
    raise ValueError("Bu PDF parola korumalı.")
```

İdeali: parola sorma diyaloğu ve `doc.authenticate(pwd)`.

### 1.7 ORTA — `close()` sonrası nesne kullanılabilir durumda

`pdf_document.py:47-50` — `close()` `self.doc = None` yapıyor ama `page_count`, `search`, `words` gibi metotlar kontrol etmiyor. Kapatılmış belgede çağrı `AttributeError: 'NoneType' object has no attribute ...` verir. Şu an bu yola girilmiyor ama kırılgan.

Ayrıca uygulama kapanırken hiçbir `PdfDocument.close()` çağrılmıyor — `closeEvent` (1118) yalnızca kaydetme soruyor. Dosya tanıtıcıları süreç bitene kadar açık kalıyor.

### 1.8 DÜŞÜK — Yer imi seçiminde gizli erken çıkış

`bookmark_panel.py:183-189` — liste `_collect` ile pre-order DFS olarak toplanıyor ve `elif item_page > page: break` ile çıkılıyor. Düzgün bir TOC'de pre-order sırası sayfa numarasıyla birlikte monoton arttığı için pratikte sorun çıkmaz; ancak sıra bozuk bir TOC'de (üretici araçların hatalı çıktıları) ilk büyük değerde döngü kırılır ve daha sonraki doğru başlık atlanır. Gizli, patlamaya hazır bir varsayım.

**Düzeltme:** `break` yerine tüm listeyi dolaşıp `item_page <= page` olanların sonuncusunu alın; ya da listeyi `sort(key=lambda t: t[0])` ile sıralayın.

### 1.9 DÜŞÜK — Yön tuşları yatay kaydırmayı gasp ediyor

`pdf_view.py:1009-1016` — `←`/`→` koşulsuz olarak `go_prev`/`go_next` çağırıyor. Yakınlaştırılmış bir sayfada yatay kaydırma yapmak imkânsız hale geliyor.

**Düzeltme:** yalnızca sayfa yatayda viewport'a sığıyorsa sayfa değiştirin, aksi halde `super().keyPressEvent(event)`.

### 1.10 DÜŞÜK — Çift bağlantı ve gereksiz tetikleme

`_act_dual.toggled` hem `self._view.set_dual_view`'a (286) hem de `_set_view_mode`'a (378) bağlı; `_set_view_mode` de içeride `set_dual_view` çağırıyor (734). Yani her geçişte iki kez çağrılıyor. `set_dual_view` başındaki erken dönüş sayesinde zararsız ama kırılgan — 286'daki bağlantı silinmeli.

### 1.11 DÜŞÜK — `RecentFiles.list()` her menü açılışında diske gidiyor

`recent_files.py:17-23` — `list()` her çağrıldığında 10 yola kadar `Path(p).exists()` (kontrol satır 21'de). Ağ sürücüsü kopmuşsa "Dosya" menüsünü açmak arayüzü saniyelerce dondurur. Varlık kontrolünü tembelleştirin veya açılışta bir kez yapın.

---

## 2. Ölü kod ve tekrarlar

**`load_shared()` ve `_owns_doc` tamamen ölü.** `pdf_view.py:307-316` — `load_shared` hiçbir yerden çağrılmıyor; bölünmüş görünüm `_toggle_split` (819) içinde ikinci panel için **bağımsız** bir `PdfDocument` açıyor. Buna bağlı `_owns_doc` bayrağı ve `clear()` içindeki koşullu kapatma mantığı (340-343) da gereksiz. Yaklaşık 15 satır ve bir kavramsal karmaşıklık katmanı silinebilir.

**Göz filtresi renk sözlüğü iki kez yazılmış.** `main_window.py:712-721` ve `797-806` — birebir aynı 8 satır. Modül seviyesinde sabit yapın:

```python
_EYE_COLORS: dict[str, QColor] = {
    "hafif": QColor(255, 210, 140, 30),
    ...
}
```

**`import fitz` iki kez.** `pdf_view.py:6` modül seviyesinde, `61` yine `run()` içinde `import fitz as _fitz`. İçerideki gereksiz.

**Modül ortasında import.** `translation_popup.py:21` ve `pdf_view.py:190-192` — importlar sınıf tanımlarından sonra geliyor. PEP 8 ihlali, okumayı zorlaştırıyor, dairesel bağımlılığı gizliyor.

**Sızan özel isim.** `pdf_view.py:192` — `from .translation_popup import _sentence_boundaries`. Cümle bölme mantığı bir UI panelinin özel fonksiyonu olmamalı; `pdf_reader/text_utils.py` gibi bağımsız bir modüle taşınmalı (`_sentence_boundaries`, `_sentence_at`, `_sentence_index_of`, `_nth_sentence` birlikte). Bu ayrıca test yazmayı kolaylaştırır.

**Kullanılmayan fonksiyon.** `translation_popup.py:67` `_nth_sentence` hiçbir yerden çağrılmıyor.

**Kullanılmayan alanlar.** `pdf_view.py:34` `_RenderSignals.done` imzasında `generation` taşınmıyor (lambda ile kapatılıyor) — sinyale eklenip lambda kaldırılabilir. `bookmark_panel.py:206` `set_eye_filter` boş gövde ("API simetrisi için") — çağrılmıyorsa silin.

**`main.py` docstring'i eski adı taşıyor:** `"""Entry point for AkinelPDF."""` → `LucidLectorPDF`.

---

## 3. Yerelleştirme boşlukları

i18n altyapısı sağlam: 6 dilin **90 anahtarı da eksiksiz** (doğrulandı, hiçbirinde eksik/fazla yok). Ancak iki yer atlanmış:

`search_bar.py:27` `"Ara…"`, `59` `f"{count} sonuç"` / `"bulunamadı"` sabit Türkçe. `SearchBar`'ın `set_locale()` metodu yok. Üç anahtar ekleyin: `search_placeholder`, `search_count`, `search_none`.

Daha önemlisi bir tasarım sorunu: **arayüz dili ile çeviri hedef dili aynı açılır menüye bağlı.** `_on_language_changed` (574) → `_apply_locale(code)` hem `self._locale`'i hem de `_translator.set_target_language`'i ayarlıyor. Yani "İngilizceye çevir" seçen bir Türk kullanıcının tüm menüleri İngilizce oluyor. Akademik kullanımda en yaygın senaryo tam da budur (Türkçe arayüz + İngilizce/Almanca kaynak çevirisi). İkisi ayrılmalı: araç çubuğunda hedef dil, Görünüm menüsünde ayrı bir "Arayüz Dili" alt menüsü.

---

## 4. Depo hijyeni

**Satır sonu kaosu.** `git diff` şu an 861 satır ekleme + 861 satır silme gösteriyor; `git diff --ignore-cr-at-eol` ise **hiçbir şey** gösteriyor. Yani `i18n.py` ve `pdf_document.py`'de tek bir gerçek değişiklik yok — tamamı CRLF/LF dalgalanması. `pdf_document.py` dosyası içinde bile karışık satır sonları var. `.gitattributes` yok.

**Düzeltme:** depoya `.gitattributes` ekleyin ve dosyaları normalize edin:

```
* text=auto eol=lf
*.bat text eol=crlf
*.png binary
*.ico binary
*.pdf binary
```

```bash
git add --renormalize .
git commit -m "chore: normalize line endings via .gitattributes"
```

**`.gitignore` eksikleri:** `.pycache_tmp/`, `*.pyc.[0-9]*` (PyInstaller'ın bıraktığı numaralı pyc artıkları), `dist/RCX*.tmp`.

**Test yok, CI yok, linter yapılandırması yok.** Saf fonksiyonlar test yazmaya çok uygun: `_sentence_boundaries`, `_sentence_at`, `_chunks`, `merged_paragraphs` birleştirme sezgiseli, `PageLayout` koordinat dönüşümleri (`_pdf_rect_to_scene`). Bunlar Qt gerektirmez. `pyproject.toml` + `ruff` + `pytest` + basit bir GitHub Actions iş akışı bir saatlik iş, karşılığı büyük.

---

## 5. Mimari sadeleştirme

**`main_window.py` 1.175 satır ve dört iş yapıyor:** UI kurulumu, panel durumu yönetimi, açıklama/geri alma mantığı, dosya kaydetme. Üçe bölünebilir:

- `ui_builder.py` — `_build_menu` + `_build_toolbar` + `_build_status` (yaklaşık 300 satır saf UI kurulumu, mantık içermiyor)
- `annotation_controller.py` — `_add_annotation`, `_undo`, `_redo`, `_create_annot`, renk yardımcıları, geri al/ileri al yığınları
- `main_window.py` — kalan pencere düzeyi mantık

**Panel durumu `id(view)` ile sözlüklerde tutuluyor** (`_panel_paths`, `_panel_dirty`, `_undo_stacks`, `_redo_stacks` — dört ayrı sözlük, hepsi `id()` anahtarlı). `id()` bir nesne silinip yenisi aynı adreste doğduğunda çakışabilir. Ayrıca dört sözlüğü senkron tutmak `_toggle_split` içinde sekiz satır tekrar üretiyor. Temiz alternatif: her panelin durumunu tutan küçük bir veri sınıfı, `PdfView`'a doğrudan bağlı:

```python
@dataclass
class PanelState:
    path: Path | None = None
    dirty: bool = False
    undo: list = field(default_factory=list)
    redo: list = field(default_factory=list)

# PdfView.__init__ içinde:
self.state = PanelState()
```

Böylece `self._active_view.state.dirty` yeterli olur; dört sözlük, dört property ve tüm `pop`/`setdefault` bakımı silinir. `_current_path` / `_document_dirty` property'leri (51-73) tamamen kaldırılabilir.

**Geri alma yığını el yapımı sözlüklerden oluşuyor.** Qt'nin `QUndoStack` + `QUndoCommand` sınıfları tam bu iş için var; menü eylemlerinin etkinleştirilmesini, komut metinlerini ("Vurgu ekle" gibi) ve birleştirmeyi bedava veriyor. `_update_undo_actions` ve elle yığın yönetimi silinir.

**`_rebuild()` her yakınlaştırma adımında tüm sahneyi yıkıyor** (`set_zoom` → `_rebuild`). Tüm pixmap'ler atılıyor ve yeniden render ediliyor; yakınlaştırma tuşuna hızlı basınca iş parçacığı havuzu çöpe giden görevlerle doluyor. Alternatif: sahneyi sabit tutup `QGraphicsView.scale()` kullanmak, yalnızca yakınlaştırma yerleştikten sonra (300 ms debounce) yüksek çözünürlükte yeniden render etmek. Kullanıcı anında geri bildirim alır, CPU çok daha az çalışır.

**`_refresh_paragraph_markers` her kaydırmada tüm işaretçileri yok edip yeniden yaratıyor** (`_update_visible_pages` → 540). Görünür sayfa kümesi değişmediyse hiç dokunmamak yeterli; sayfa bazında işaretçi önbelleği tutun.

---

## 6. Geliştirme önerileri

Akademik okuma odağını güçlendirecek, mevcut mimariye uyan öneriler — kabaca değer/maliyet sırasıyla:

**Vurgu dışa aktarma.** Belgedeki tüm vurgu ve altı çizili metinleri sayfa numarasıyla birlikte Markdown/CSV/BibTeX notu olarak dışa aktarma. `PdfDocument` zaten `page.annots()` ile geziyor; metin çıkarma için `page.get_textbox(annot.rect)` yeterli. Akademik iş akışının en çok istenen özelliği ve burada neredeyse bedava.

**Son okunan sayfayı hatırlama.** Dosya yolu → sayfa numarası eşlemesi `QSettings`'te. `RecentFiles` altyapısı zaten var. Çok küçük iş, günlük kullanımda büyük fark.

**Arayüz dilini çeviri dilinden ayırma.** Bölüm 3'te açıklandı.

**Alternatif çeviri motoru.** Google tek nokta arıza; rate-limit yiyor, çevrimdışı çalışmıyor. `deep-translator` zaten DeepL, MyMemory, Libre desteğine sahip — bir açılır menü ve `_Worker.run` içinde motor seçimi yeterli. Çevrimdışı için `argos-translate` düşünülebilir.

**Kelime sözlüğü modu.** Kelimeye çift tıklayınca küçük bir baloncukta anlamı. Seçim altyapısı (`_find_nearest_word`) hazır; tek kelimelik çeviri isteği zaten destekleniyor.

**Sayfa küçük resim paneli.** Sol tarafta, yer imi paneliyle sekmeli. Tembel render altyapısı (`_PageRenderTask`) düşük `zoom` ile aynen kullanılabilir.

**Serbest not / yorum açıklaması.** Şu an yalnızca vurgu ve altı çizme var. PyMuPDF `add_text_annot` destekliyor; notlar aranabilir bir listede toplanabilir.

**Taranmış PDF için OCR.** PyMuPDF `page.get_textpage_ocr()` ile Tesseract'a bağlanıyor. Metin katmanı olmayan PDF'lerde şu an seçim, arama ve çeviri tamamen çalışmıyor — kullanıcıya en azından "bu belgede metin katmanı yok" uyarısı verilmeli.

**Gerçek karanlık mod.** Mevcut göz filtreleri sayfanın üzerine yarı saydam renk basıyor; beyaz zemin hâlâ parlak. Gerçek ters çevirme için render sonrası `QImage.invertPixels()` veya PyMuPDF'in `pixmap.invert_irect()` kullanılabilir.

---

## 7. Öncelikli iş listesi

1. ~~Bölünmüş görünümdeki yedi `self._view` → `self._active_view` düzeltmesi (§1.1)~~ ✅
2. ~~Render hatasında `_pending_renders` temizliği + hata sinyali (§1.2)~~ ✅
3. ~~Hover aramasını görünür sayfalarla sınırlama (§1.3)~~ ✅
4. ~~Render için ayrı `QThreadPool` (§1.4)~~ ✅
5. ~~`.gitattributes`~~ ✅ — `git add --renormalize .` **sizin çalıştırmanız gerekiyor**
6. ~~Ölü kod temizliği (§2)~~ ✅
7. ~~`text_utils.py` ayrıştırması + ilk pytest testleri (§2, §4)~~ ✅
8. `PanelState` veri sınıfı ile dört sözlüğün birleştirilmesi (§5)
9. Arayüz dili / çeviri dili ayrımı (§3)
10. Çeviri panelinin kaynak paneli takip etmesi (§8, aşağıda)
11. Ctrl+F'in büyük belgelerde arayüzü dondurması (§1.3'ün ikizi, hâlâ açık)
12. Vurgu dışa aktarma özelliği (§6)

Ayrıca §1.5, §1.6, §1.7 ve §1.8 de bu turlarda kapandı. Açık kalanlar: §1.9 (yön tuşları), §1.10 (çözüldü), §1.11 (`RecentFiles` disk erişimi), §3 (arayüz dili), §5 (mimari).

---

## 8. Uygulanan düzeltmeler — 20 Ağustos 2026

### §1.1 — Panel yönlendirmesi

`main_window.py` içinde yedi yer `self._active_view`'a taşındı: paragraf modu (272), arama gezinmesi (450–452), hover vurgu sinyalleri (462–463), `_set_view_mode` (734), `_rotate_pages` (846), `_run_search` (877), `_show_translation` (894). Sinyal bağlantılarında doğrudan metot referansı yerine lambda kullanıldı ki bağlantı kurulduğu andaki panele değil, tetiklendiği andaki aktif panele gitsin.

`_act_dual.toggled` üzerindeki çift bağlantı (§1.10) da bu sırada kaldırıldı — `_set_view_mode` zaten `_build_toolbar` içinde bağlı olduğundan menüdeki ikinci bağlantı her geçişte `set_dual_view`'ın iki kez çağrılmasına yol açıyordu.

Düzeltmenin ortaya çıkardığı bir yan durum için yeni `_sync_view_mode_actions()` eklendi: ikili görünüm ve paragraf modu artık aktif panele uygulandığından, panel değiştirildiğinde onay kutuları da yeni panelin gerçek durumunu yansıtmalı. Aksi halde işaretli görünen bir kutu kapalı bir panele karşılık gelirdi.

Geriye kalan `self._view.` kullanımları kasıtlı: her panelin kendi sinyallerini bağladığı satırlar (458–485) ve panel bazında durum uygulayan satırlar (517, 733, 759, 870). Bunlar aktif panele değil, ilgili panele ait olmalı.

### §1.2 — Render hata yönetimi

`_RenderSignals` artık `generation`'ı sinyalde taşıyor (`done = pyqtSignal(int, object, int)`) ve yeni bir `failed` sinyali var. `_PageRenderTask.run()` istisnayı yutmak yerine `failed` yayıyor, `doc.close()` de `finally` bloğuna alındı. Şifreli belge için açık kontrol eklendi (`doc.needs_pass` → §1.6 kısmen kapandı).

Görev başına bir `_RenderSignals` yaratmak yerine `PdfView` artık ömür boyu tek bir örnek tutuyor (`self._render_signals`, `PdfView`'a ait, yani ana iş parçacığında). Eski kod her görev için yeni bir QObject yaratıp onu `task._sig_keepalive` ile canlı tutmaya çalışıyordu; QRunnable otomatik silindiğinde bu nesne kuyruğa alınmış çağrı çalışmadan çöpe gidebiliyor ve sonuç sessizce düşebiliyordu. Bağlantılar artık `self`'in bağlı metotlarına kurulduğu için Qt otomatik olarak kuyruklu bağlantı seçiyor — lambda ile bu garanti değildi.

Yeni `_on_page_failed` slotu sayfayı `_pending_renders`'tan çıkarıyor, `_failed_renders` sözlüğüne kaydediyor ve `render_failed` sinyalini yayıyor. `_ensure_page_rendered` başarısız sayfayı yeniden denemiyor (aksi halde her kaydırma tikinde havuzu bozuk görevlerle doldururdu); kayıt `clear()` ve `_rebuild()` içinde temizlendiğinden yakınlaştırma veya görünüm değişimi doğal bir yeniden deneme noktası oluşturuyor.

Kullanıcıya iki geri bildirim eklendi: başarısız sayfanın yer tutucusu gri yerine koyu kırmızıya boyanıyor ve hata mesajı araç ipucu olarak veriliyor; ayrıca `MainWindow._on_render_failed` durum çubuğunda mesaj gösteriyor. Bunun için altı dile `status_render_fail` anahtarı eklendi (91 anahtar, altı dilde de eksiksiz).

### İkinci tur — bağımsız incelemede çıkan sorunlar

İlk turdan sonra değişiklikler bağımsız olarak gözden geçirildi ve dördü gerçek olmak üzere şu sorunlar bulunup düzeltildi. Üçü ilk turda benim eklediğim kodun kendi hatasıydı.

**`_RenderSignals` view'a parent'lanmıştı** (regresyon). Bölünmüş panel kapatılırken `deleteLater()` çocuğu da yok eder; havuzda hâlâ koşan bir görev bu nesneye referans tuttuğu için `emit` `RuntimeError` fırlatırdı. Bu hata `except` dalına düşer, oradaki `failed.emit` aynı hatayı tekrar fırlatır ve `run()` dışına taşardı — PyQt yakalanmamış istisnada `qFatal()` çağırdığı için sonuç çökmeydi. Nesne artık parent'sız: Python referansı onu ayakta tutuyor, Qt ise view yok edilince bağlantıları kendisi düşürdüğü için geç gelen emit sessizce yutuluyor. Ayrıca `except` dalındaki `emit` kendi `try` sarmalına alındı.

**Arama vurguları yetim kalıyordu** (regresyon). `_search.closed` yalnızca aktif paneli temizliyordu; A panelinde arayıp B'ye tıklayıp çubuğu kapatan kullanıcının A panelindeki vurguları kalıcı olarak ekranda kalıyordu — `_rebuild` `_search_rects` doluyken overlay'leri yeniden çizdiği için yakınlaştırma da temizlemiyordu. Yeni `_clear_all_searches()` tüm panelleri temizliyor.

**Başarısız sayfa kalıcı olarak kırmızı kalıyordu** (ilk turdaki tasarım hatam). `_failed_renders` yalnızca `clear()`/`_rebuild()` ile temizlendiğinden geçici bir hata kalıcılaşıyordu — örneğin `save_incremental` dosyayı yerinde yeniden yazarken aynı dosyayı açmaya çalışan bir render görevi Windows'ta paylaşım ihlali alır. Artık üç denemelik bir bütçe var (`MAX_RENDER_ATTEMPTS`), denemeler arasında 400 ms bekleniyor ve kullanıcı yalnızca bütçe tükendiğinde uyarılıyor. Bütçe üç yerde sıfırlanıyor: sayfa görünürlük penceresinden çıkınca, `rerender_page` ile açıkça tazelenince, ve her yeniden kurulumda.

> İlk yazdığım sıfırlama `_unload_page` içindeydi ve **hiç çalışmıyordu**: o döngü yalnızca `_rendered_pages` üzerinde dönüyor, başarısız bir sayfa ise oraya hiç girmiyor. Sıfırlama `_update_visible_pages`'e taşındı. Benzer şekilde ilk hâlde denemeler yalnızca kullanıcı kaydırdığında tetikleniyordu; artık `QTimer.singleShot` ile kendiliğinden zamanlanıyor.

**Kapanışta koşan render görevleri.** `closeEvent` ne generation'ı ilerletiyor ne de havuzu bekliyordu; kapanış sırasında hâlâ koşan bir görev, yorumlayıcı sonlanırken emit etmeye çalışabilirdi. Artık kaydetme sorularından sonra her panelde `clear()` çağrılıyor (bu aynı zamanda §1.7'deki açık kalan dosya tanıtıcılarını da kapatıyor) ve `waitForDone(3000)` ile havuz bekleniyor.

**Şifreli PDF kontrolü yanlış katmandaydı.** İlk turda kontrolü render görevine koymuştum, ama oraya hiç ulaşılmıyordu: `PdfDocument.__init__` şifreli dosyayı sorunsuz açıyor, sonra `_rebuild()` → `page_size()` zincirinde yakalanmamış bir istisna patlıyordu. Kontrol `PdfDocument.__init__`'e taşındı; `open_path`'in mevcut `try/except` bloğu artık düzgün bir hata diyaloğu gösteriyor. **§1.6 tamamen kapandı.**

Ek olarak: `failed` sinyalinin argüman sırası `done` ile hizalandı (`page, payload, generation`) — önceki `(int, int, str)` imzasında ilk iki argüman aynı tipte olduğu için yer değiştirmeleri hiçbir denetim yakalamazdı. Kırmızı yer tutucunun araç ipucu da sabit Türkçe metin yerine i18n'den geliyor.

**Doğrulama:** tüm modüller derleniyor; i18n anahtar kümeleri altı dilde birebir eşit (91 anahtar); `_RenderSignals` imzaları, `run()` içindeki iki `emit` yolu, sinyal/slot argüman uyumu, `MAX_RENDER_ATTEMPTS` ve `RENDER_RETRY_DELAY_MS` tanım/kullanımı ile `QTimer`/`QThreadPool` importları AST ile teyit edildi.

---

## 9. Üçüncü tur — §1.3, §1.4, §2, §4

### §1.3 — Hover araması artık sayfa bazlı ve tembel

`PdfDocument.search_pages(query, pages)` eklendi; `search()` onu tüm sayfalarla çağıran ince bir sarmalayıcıya indi. Ctrl+F hâlâ tüm belgeyi tarıyor — orada doğrusu bu.

`show_hover_highlight` artık yalnızca görünüm penceresi çevresindeki sayfalarda arıyor. Daha önemlisi `set_translation_context` tamamen yeniden yazıldı: eskiden çeviri gelir gelmez her cümle için 1–2 tam belge taraması yapılıyordu. Artık yalnızca cümleler saklanıyor, dikdörtgenler `_sentence_rects_for_page()` ile **imleç o sayfaya ilk girdiğinde** hesaplanıp önbelleğe alınıyor. 500 sayfalık bir belgede 20 cümlelik paragraf çevirisi 20.000 sayfa taramasından, gezilen sayfa başına ~40 aramaya indi. Önbellek yeni belge, yeni çeviri ve döndürmede geçersiz kılınıyor; yakınlaştırma ve ikili görünüm geçersiz kılMAmalı, çünkü dikdörtgenler PDF koordinatında tutuluyor ve ölçekleme çizim anında yapılıyor.

### §1.4 — Render için ayrı havuz

Sayfa render'ı artık `QThreadPool.globalInstance()` kullanmıyor. Çevirmen orada kalmaya devam ediyor; ağ çağrılarının zaman aşımı olmadığı için birkaç asılı çeviri render'ı tamamen durduruyordu. Havuz modül düzeyinde ve **tüm panellerce paylaşılıyor** — panel başına havuz, bölünmüş görünümde CPU'yu iki kat fazla iş parçacığıyla yükleyecekti. Yeni `PdfView.shutdown()` generation'ı ilerletiyor, kuyruğu boşaltıyor ve bekliyor; `_toggle_split` kapatma dalı ile `closeEvent` bunu çağırıyor.

### §2, §4 — Temizlik

`load_shared()` ve `_owns_doc` silindi (`_toggle_split` zaten bağımsız belge açıyordu, dolayısıyla paylaşım kavramı hiç kullanılmıyordu). Göz filtresi renkleri `EYE_FILTER_COLORS` modül sabitine indi. `_panels()` yardımcısı dört yerdeki panel döngüsünü tekilleştirdi. Cümle yardımcıları `text_utils.py`'ye taşındı — böylece `pdf_view`'in bir UI panelinin özel adını (`_sentence_boundaries`) içe aktarması son buldu — ve modül ortasındaki importlar dosya başına alındı. `_nth_sentence`, `clear_translation_context`, `bookmark_panel.set_eye_filter`, `QPainterPath`, `QGraphicsItemGroup`, `import os` ve eski `AkinelPDF` docstring'i kaldırıldı. `.gitattributes` eklendi, `.gitignore`'a eksik kurallar girildi.

**§1.8 de kapatıldı:** yer imi seçimindeki erken `break` kaldırıldı, en derin uygun madde `best_page` takibiyle seçiliyor.

`_rerender_page`'in diğer panele aynalaması kaldırıldı: paneller ayrı `PdfDocument` açtığı için diğer panelin belleğindeki belgede o açıklama yok, aynalama yalnızca aynı sayfayı boşuna yeniden çiziyordu.

### Bu turda bağımsız incelemenin yakaladığı gerilemeler

**Fare hareketi başına tüm sayfa listesi taranıyordu.** `_sentence_at_scene_point`'i `_scene_to_page` üzerine kurmuştum; tek görünümde `_pages` tüm belgeyi içerdiği için bu, 3000 sayfalık bir PDF'te saniyede yüzlerce kez 3000 elemanlık döngü demekti — eski koddan daha kötü. Yeni `_visible_page_at()` yalnızca görünür sayfalara bakıyor.

**Aynı cümle iki kez aranıyordu.** Hover, dikdörtgenler zaten `_sentence_rects_for_page` önbelleğinde dururken `show_hover_highlight` çağırıp aramayı baştan yapıyordu. Yeni `_paint_hover_rects()` önbellekteki dikdörtgenlerden doğrudan çiziyor.

**`clear()` `_hover_items` ve `_active_paragraph_marker`'ı temizlemiyordu** — `_rebuild()` temizliyordu, ama `clear()` tek başına çağrıldığında (split kapatma, uygulama kapanışı) ölü C++ sarmalayıcıları listede kalıyordu.

**Cümle sınırları çok karakterli ayırıcılarda bitişik değildi.** Bu HEAD'den devralınan bir hataydı ama ilk yazdığım docstring ve test yanlış bir garanti belgeliyordu. `(start, m.start() + 1)` yalnızca **tek** boşluk karakterini yutuyor, oysa `start = m.end()` tüm ayırıcıyı atlıyordu; arada CRLF, çift boşluk veya boş satır varsa boşluk oluşuyor ve o ofsete denk gelen hover, tek cümle yerine **tüm paragrafı** vurguluyordu. PDF metin katmanlarında bu ayırıcılar çok yaygın. `(start, m.end())` ile düzeltildi; testler artık beş ayırıcı biçimini de kapsıyor. Eski uygulamayla karşılaştırmalı olarak doğrulandı: çift boşluk, CRLF ve boş satır senaryolarının her birinde eski kod bir ofseti yanlış eşliyordu, yenisi hiçbirini.

**Üç farklı "çok kısa cümle" eşiği** (6 / 8 / 10) tek bir `MIN_SENTENCE_LENGTH` sabitinde birleştirildi; 8–9 karakterlik bir cümle PDF'ten hover edilebilirken panelden edilemiyordu.

Ayrıca split kapatılırken yer imi paneli kapanan panelin içindekiler tablosunu göstermeye devam ediyordu — artık birincil panele dönüyor.

### Doğrulama

`tests/test_text_utils.py` eklendi: **37 test, hepsi geçiyor.** Qt veya PyMuPDF gerektirmiyor, `python -m pytest` ile çalışıyor. Tüm modüller derleniyor.

> Not: sandbox'ın dosya bağlaması bu oturumda dosya boyutlarını önbelleğe aldığı için `py_compile` ve `pytest` doğrudan çalıştırılamadı; doğrulama, dokunulmayan kuyruklar geri eklenerek kopyalar üzerinde yapıldı. Değişiklikleri kendi ortamınızda bir kez çalıştırmanız yerinde olur.

### Hâlâ açık olan, bu turda düzeltilmeyenler

Çeviri paneli tek ve global, paneller ise ayrı — bu ikisi arasında üç senaryo tutarsız kalıyor: çeviri gelmeden panel değiştirilirse bağlam yeni panele kurulur; hover girişi bir panele, çıkışı diğerine gidebilir; farklı dosya açık bir panelde hover araması boşa çalışır. Düzgün çözüm `translate_requested`'ın kaynak paneli taşıması, yani sinyal imzası değişikliği — ayrı bir iş olarak bırakıldı.

`_sync_view_mode_actions` içindeki `blockSignals`, QAction'ın `changed()` sinyalini de bloke ediyor. `_act_dual` ve `_act_paragraph` şu an yalnızca menüde olduğu için sorun çıkmıyor (QMenu onay durumunu boyama anında okur), ama bu action'lardan biri ileride araç çubuğuna eklenirse buton görseli güncellenmeden kalır.
