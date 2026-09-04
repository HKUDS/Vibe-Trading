<p align="center">
  <a href="README.md">English</a> | <a href="README_zh.md">中文</a> | <a href="README_ja.md">日本語</a> | <a href="README_ko.md">한국어</a> | <a href="README_ar.md">العربية</a> | <b>Español</b>
</p>

<p align="center">
  <img src="assets/icon.png" width="120" alt="Vibe-Trading Logo"/>
</p>

<h1 align="center">Vibe-Trading: Tu Agente de Trading Personal</h1>

<p align="center">
  <b>Un Solo Comando para Dotar a tu Agente de Capacidades Integrales de Trading</b>
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
  <a href="https://vibetrading.wiki/">Sitio web</a> &nbsp;&middot;&nbsp;
  <a href="https://vibetrading.wiki/docs/">Documentación</a> &nbsp;&middot;&nbsp;
  <a href="#-news">News</a> &nbsp;&middot;&nbsp;
  <a href="#-key-features">Features</a> &nbsp;&middot;&nbsp;
  <a href="#-shadow-account">Shadow Account</a> &nbsp;&middot;&nbsp;
  <a href="#-demo">Demo</a> &nbsp;&middot;&nbsp;
  <a href="#-quick-start">Quick Start</a> &nbsp;&middot;&nbsp;
  <a href="#-examples">Examples</a> &nbsp;&middot;&nbsp;
  <a href="#-api-server">API / MCP</a> &nbsp;&middot;&nbsp;
  <a href="#-roadmap">Roadmap</a> &nbsp;&middot;&nbsp;
  <a href="#contributing">Contributing</a>
</p>

<p align="center">
  <a href="#-quick-start"><img src="assets/pip-install.svg" height="45" alt="pip install vibe-trading-ai"></a>
</p>

---

## 📰 News

> ⚠️ **Advertencia de seguridad:** la cuenta de X `VibeTrading_HKU`, el proyecto de Virtuals `101845` y el contrato de token `0x640BDBF77b6447E8b7DB7894cED84BD1c40571f4` no son activos oficiales de Vibe-Trading. Nunca hemos lanzado ni respaldado ningún token o memecoin. No compres, conectes una wallet ni firmes nada. [Detalles](SECURITY.md#official-channels--impersonation).

- **2026-09-04** 🩺 **Todas las ejecuciones con Claude 5 fallaban en la primera petición, y una posición suspendida se valoraba de nuevo a lo que pagaste por ella**: con el SDK actual de Anthropic, `langchain-anthropic` traslada `temperature` a `extra_body`, y nuestra autorreparación solo quitaba la clave de primer nivel, así que el reintento reenviaba exactamente el campo que la API acababa de rechazar y toda ejecución con `claude-sonnet-5` / `claude-opus-5` moría en la primera llamada ([#1330](https://github.com/HKUDS/Vibe-Trading/pull/1330), cierra [#1329](https://github.com/HKUDS/Vibe-Trading/issues/1329)). En los backtests, una posición mantenida más allá del límite de relleno hacia adelante se revaloraba a su precio de entrada: la curva de capital mostraba una caída sin ningún evento de mercado detrás, y el dimensionado del rebalanceo trabajaba sobre esa marca fantasma. Ahora una suspensión de cualquier duración se valora al último cierre negociado, mientras que las ejecuciones de órdenes siguen rechazando un precio obsoleto ([#1332](https://github.com/HKUDS/Vibe-Trading/pull/1332), cierra [#1318](https://github.com/HKUDS/Vibe-Trading/issues/1318)). **Corregido:** tres formas en que un ajuste en el momento de confirmar podía ampliar el mandato que aprobaste — un número escrito como texto se saltaba la comprobación numérica, `True` pasaba como número y la lista blanca de instrumentos no tenía comparación alguna. Además, solo efectivo (cash-only) es el suelo del eje de apalancamiento y no un tipo inválido, así que el mandato más conservador sigue siendo confirmable ([#1285](https://github.com/HKUDS/Vibe-Trading/pull/1285)). El reloj de tiempo transcurrido sobrevive a cambiar de página, recargar y reabrir una sesión desde el historial ([#1340](https://github.com/HKUDS/Vibe-Trading/pull/1340), cierra [#1339](https://github.com/HKUDS/Vibe-Trading/issues/1339)), y se han parcheado los siete avisos de seguridad npm abiertos en los archivos de bloqueo del frontend y del escritorio. ¡Gracias [@averatec0773](https://github.com/averatec0773), [@he-yufeng](https://github.com/he-yufeng) y [@Jackzigen](https://github.com/Jackzigen)!

- **2026-09-03** 📡 **Una fuente de datos que nunca responde, y cifras con fecha que no podían probarse**: stooq entrega a los clientes que no son navegadores una página de prueba de trabajo en JavaScript — HTTP 200 con cuerpo HTML — que el loader interpretaba como «sin datos», de modo que la posición 2 de la cadena de renta variable estadounidense era peso muerto en cada consulta y no quedaba nada en el registro de ejecución. Ahora se reconoce como no disponible, con un aviso único que indica cómo reordenar o descartar la fuente ([#1342](https://github.com/HKUDS/Vibe-Trading/pull/1342), cierra [#1315](https://github.com/HKUDS/Vibe-Trading/issues/1315)). Por otro lado, un resultado de herramienta genérica que llevaba a la vez un precio y su fecha perdía la fecha al entrar en el libro de evidencias, así que una afirmación fechada no tenía evidencia que pudiera corresponderle y se rechazaba una respuesta correcta; ahora las marcas de tiempo se conservan y la fecha propia de una fila prevalece sobre la heredada ([#1333](https://github.com/HKUDS/Vibe-Trading/pull/1333)). **Corregido:** los envoltorios MCP para la evidencia y el estado de un objetivo exigían un identificador que las herramientas registradas documentan como opcional, de modo que un cliente que quería decir «el objetivo actual» solo recibía un error de validación ([#1331](https://github.com/HKUDS/Vibe-Trading/pull/1331)); el adaptador de Codex descartaba los recuentos de tokens que informa el proveedor y dejaba la contabilidad de uso en una estimación por caracteres ([#1334](https://github.com/HKUDS/Vibe-Trading/pull/1334)). **Nuevo:** la ruta MCP por stdio del swarm gana cobertura con un subproceso real en lugar de una nota que decía que no estaba probada ([#1335](https://github.com/HKUDS/Vibe-Trading/pull/1335)). ¡Gracias [@he-yufeng](https://github.com/he-yufeng) y [@Shizoqua](https://github.com/Shizoqua)!

- **2026-09-02** 💵 **Los dos últimos loaders que contabilizaban los dividendos como pérdidas, y una fuente explícita que respondía en nombre de otra**: FMP y Tiingo seguían sirviendo OHLC sin ajustar mientras el resto de la cadena servía precios ajustados — el mismo hueco del ex-dividendo leído como una caída real, cerrado para Yahoo el 08-31 y ahora cerrado para ambos ([#1320](https://github.com/HKUDS/Vibe-Trading/pull/1320), cierra [#1296](https://github.com/HKUDS/Vibe-Trading/issues/1296)). En el mismo cambio se corrigieron sus filas en la tabla de calibre de precio: un marco ajustado no debe llevar el sello `raw`, o el aviso de calibres mezclados añadido en [#1317](https://github.com/HKUDS/Vibe-Trading/pull/1317) estaría comprobando una etiqueta en vez de los datos. FMP también pasó al endpoint Stable, y un `source="fmp"` explícito ahora falla de forma audible en lugar de devolver las cifras de otra fuente bajo el nombre de FMP ([#1276](https://github.com/HKUDS/Vibe-Trading/pull/1276), cierra [#1270](https://github.com/HKUDS/Vibe-Trading/issues/1270)). **Corregido:** un ticker entre paréntesis de ancho completo — `公司名（代码）价格` — quedaba separado de su propia cifra, así que la puerta de símbolos sin fuente nunca veía los dos juntos ([#1326](https://github.com/HKUDS/Vibe-Trading/pull/1326), cierra [#1260](https://github.com/HKUDS/Vibe-Trading/issues/1260)); cada enlace `references/` de las skills incluidas se resuelve ahora al mismo archivo para el agente y para quien lo pulse en GitHub ([#1328](https://github.com/HKUDS/Vibe-Trading/pull/1328)). **Nuevo:** el portugués de Brasil se suma a la interfaz como octavo idioma ([#1327](https://github.com/HKUDS/Vibe-Trading/pull/1327)). ¡Gracias [@lorenzozanee](https://github.com/lorenzozanee), [@thisisjun786](https://github.com/thisisjun786), [@cgycorey](https://github.com/cgycorey), [@jw232](https://github.com/jw232), [@ethanstoner](https://github.com/ethanstoner) y [@nandofmike](https://github.com/nandofmike)!
<details>
<summary>Noticias anteriores</summary>

- **2026-09-01** 🎯 **Los backtests de opciones se ejecutaban al precio del que la propia señal se había calculado, y una venta en descubierto podía vender una prima que jamás podría cubrir**: una señal fechada en T se valoraba con el cierre y la IV de ese mismo T — una ventaja fantasma en todo backtest de opciones, no solo en los adversarios. Ahora las señales se ejecutan en la barra siguiente, y las patas cortas depositan margen al estilo CBOE contrastado con el poder de compra ([#1299](https://github.com/HKUDS/Vibe-Trading/pull/1299), [#1306](https://github.com/HKUDS/Vibe-Trading/pull/1306)). **Corregido:** la financiación de perpetuos se liquidaba una vez al día en barras diarias frente al modelo de 3 veces al día del propio motor ([#1307](https://github.com/HKUDS/Vibe-Trading/pull/1307)); una posición corta 1x quedaba totalmente exenta de liquidación ([#1298](https://github.com/HKUDS/Vibe-Trading/pull/1298)); las ejecuciones compuestas perdían el T+1 de India y dejaban pasar todas las bandas de límite de precio ([#1309](https://github.com/HKUDS/Vibe-Trading/pull/1309)). **Nuevo:** cada marco servido indica su calibre de precio — ajustado, sin ajustar u honestamente desconocido — y una ejecución que mezcla calibres lo advierte ([#1317](https://github.com/HKUDS/Vibe-Trading/pull/1317), cierra [#1301](https://github.com/HKUDS/Vibe-Trading/issues/1301)). ¡Gracias [@he-yufeng](https://github.com/he-yufeng), [@cgycorey](https://github.com/cgycorey), [@lorenzozanee](https://github.com/lorenzozanee) y [@guestccc](https://github.com/guestccc)!
- **2026-08-31** 🧮 **Yahoo contabilizaba cada dividendo como una pérdida, y el recuento de rebalanceos que veías no tenía nada que ver con las ejecuciones**: ambas rutas de Yahoo servían OHLC sin ajustar por dividendos mientras el resto de la cadena servía precios ajustados, de modo que cada hueco ex-dividendo se leía como una caída real en cualquier backtest de renta variable estadounidense que ganara Yahoo. Ahora el OHLC se escala al `adjclose` de Yahoo y la ruta de yfinance pide la serie ajustada; el volumen sigue siendo bruto en ambas ([#1287](https://github.com/HKUDS/Vibe-Trading/pull/1287)). Medir la cadena para verificarlo sacó a la luz algo que conviene decir con claridad: **sina y longbridge siguen sirviendo precios totalmente sin ajustar**, así que la fuente en la que caigas todavía cambia el calibre del precio — esa brecha se rastrea ahora en [#1301](https://github.com/HKUDS/Vibe-Trading/issues/1301). Aparte, `rebalance_count` contaba *cambios* de peso objetivo, no ejecuciones: una estrategia SPY/BND con objetivo constante reportaba un rebalanceo frente a 1.269 operaciones. Solicitado y ejecutado son ahora métricas separadas, las de ejecución derivadas de registros de fills inmutables ([#1281](https://github.com/HKUDS/Vibe-Trading/pull/1281), cierra [#1275](https://github.com/HKUDS/Vibe-Trading/issues/1275)). **Nuevo:** `rebalance_mask` ejecuta rebalanceo parcial según un calendario o fechas explícitas en lugar de en cada barra ([#1277](https://github.com/HKUDS/Vibe-Trading/pull/1277), cierra [#1273](https://github.com/HKUDS/Vibe-Trading/issues/1273)); el informe HTML de alpha bench ya incluye la divulgación de sesgo de supervivencia que el JSON ya tenía, nombrando la fuente de constituyentes y su fecha de corte ([#1289](https://github.com/HKUDS/Vibe-Trading/pull/1289)). **Corregido:** un símbolo sin resolver ya no deja tirado al resto de su lote — la cadena reintenta solo los que faltan y la procedencia nombra la fuente de la que vino realmente cada símbolo ([#1288](https://github.com/HKUDS/Vibe-Trading/pull/1288)); un barrido de parada podía marcar un episodio que nunca barrió, y dos finalizaciones concurrentes podían perder el registro de la otra ([#1254](https://github.com/HKUDS/Vibe-Trading/pull/1254)); una conexión Futu OpenD operativa se mostraba como no disponible porque su informe de salud omitía `connection_state`; el actualizador de escritorio leía un sondeo de proceso con permiso denegado como "backend terminado" ([#1284](https://github.com/HKUDS/Vibe-Trading/pull/1284)); y una sesión enviada a segundo plano a mitad de turno mantenía su indicador en la barra lateral durante toda la vida de la pestaña ([#1257](https://github.com/HKUDS/Vibe-Trading/pull/1257), cierra [#1256](https://github.com/HKUDS/Vibe-Trading/issues/1256)). ¡Gracias [@he-yufeng](https://github.com/he-yufeng), [@cgycorey](https://github.com/cgycorey), [@thisisjun786](https://github.com/thisisjun786), [@bonyohana](https://github.com/bonyohana), [@lorenzozanee](https://github.com/lorenzozanee), y [@iagop03](https://github.com/iagop03)!
- **2026-08-30** 🇬🇧 **Las acciones de LSE llegan sin convertir peniques en libras, y los triggers live dejan de activarse con el mercado cerrado**: los símbolos `.L` funcionan ahora de extremo a extremo mediante el fallback de datos de mercado Yahoo → yfinance → local, perfiles de acciones y estados financieros, consumidores del diario de operaciones y Shadow, y backtests liquidados en GBP. El loader trata `.L` solo como marcador de mercado: los precios declarados en GBp/p se dividen por 100, GBP pasa sin cambios y USD, otras divisas o una divisa desconocida se rechazan antes de la capa contable estática en GBP. La procedencia de conversión por símbolo sobrevive a los ciclos de caché y se incrementó su versión para impedir que vuelvan entradas antiguas inseguras; la ejecución británica también usa acciones enteras y `slippage_uk` ([#1206](https://github.com/HKUDS/Vibe-Trading/pull/1206), cierra [#1205](https://github.com/HKUDS/Vibe-Trading/issues/1205)). **Corregido:** los market-triggered live ticks se detienen antes de leer el bróker cuando todos los mercados asociados están cerrados, mientras los canales solo por intervalo y por eventos quedan fuera de esta puerta ([#1253](https://github.com/HKUDS/Vibe-Trading/pull/1253)); Run Detail permite desplazarse, recorta prompts largos y vuelve a plegarlos al cambiar de run ([#1258](https://github.com/HKUDS/Vibe-Trading/pull/1258)); los runs que no son backtests van a Studio en vez de un dashboard vacío, y un array vacío de artefactos de operaciones ya no oculta un `trade_log` con datos ([#1259](https://github.com/HKUDS/Vibe-Trading/pull/1259)). ¡Gracias [@cgycorey](https://github.com/cgycorey), [@he-yufeng](https://github.com/he-yufeng) y [@iagop03](https://github.com/iagop03)!
- **2026-08-29** 🛑 **Un interruptor de emergencia que se saltó su propia acción, y un par cripto que resolvía a otra moneda**: cuando fallaban las lecturas del bróker en un canal detenido —el adaptador devuelve un sobre de error en lugar de lanzar una excepción, y el barrido lo recorría como si fuera una lista de órdenes—, el barrido se marcaba igualmente como disparado. La cancelación y el cierre de posiciones que el interruptor existe para ejecutar se omitían en silencio en ese episodio, y nada lo reintentaba. Ahora solo se bloquea después de haber intentado realmente una escritura en el bróker, reclama cada episodio de parada en exclusiva para que dos ejecutores no dupliquen un cierre, y ya no interpreta como aceptado un rechazo del bróker envuelto en un éxito de la capa de transporte ([#1244](https://github.com/HKUDS/Vibe-Trading/pull/1244)). Aparte, pedir `ETH-USDT` devolvía `AETHUSDT-USD` —Aave Ethereum USDT, un activo distinto— porque la búsqueda de símbolos nunca cubrió los pares de exchange y ganaba la cadena más parecida de Yahoo. Los pares exactos se resuelven ahora contra los catálogos de los exchanges, que son públicos y no requieren cuenta de bróker ([#1242](https://github.com/HKUDS/Vibe-Trading/pull/1242), cierra [#1234](https://github.com/HKUDS/Vibe-Trading/issues/1234)). **Nuevo:** los conectores integrados publican un contrato de alta legible por máquina, de modo que `vibe-trading connector setup` y el centro de conexiones de Cartera usan un único flujo genérico, con los secretos guardados por conexión en el llavero del sistema operativo ([#1250](https://github.com/HKUDS/Vibe-Trading/pull/1250)). **Corregido:** los reintentos de streaming escalan y respetan `Retry-After` ([#1208](https://github.com/HKUDS/Vibe-Trading/issues/1208)); una pata cuyo objetivo se redondea por debajo de un lote se informa en lugar de operar cero veces sin avisar ([#1235](https://github.com/HKUDS/Vibe-Trading/issues/1235)); y un índice de referencia explícito se mide sobre la ventana evaluada, no sobre la descargada, de modo que el límite de calentamiento de ayer ya no compara dos periodos distintos. ¡Gracias [@cgycorey](https://github.com/cgycorey), [@pengpengyi92](https://github.com/pengpengyi92), [@lorenzozanee](https://github.com/lorenzozanee), [@goatyyc](https://github.com/goatyyc), [@ethanstoner](https://github.com/ethanstoner), [@QG8000](https://github.com/QG8000) y [@turtle696966969696](https://github.com/turtle696966969696)!
- **2026-08-28** 📏 **Backtests que reventaban, y backtests que calificaban en silencio un año que nunca pediste**: en v0.1.14 todo backtest multi-mercado moría — el runner pasa deliberadamente `bars_per_year=None` para una cesta que abarca varios mercados, y la nueva radiografía de riesgo le aplicaba `math.sqrt`. Otros dos consumidores tenían el mismo hueco; los cuatro resuelven ahora `None` mediante un único factor derivado del período ([#1239](https://github.com/HKUDS/Vibe-Trading/pull/1239), closes [#1237](https://github.com/HKUDS/Vibe-Trading/issues/1237)). El más silencioso: una estrategia de lookback largo necesita barras *anteriores* al período que pediste, así que el agente retrasaba `start_date` un año para alimentar la MA200 — y luego calificaba ese año. Una ejecución presentada como diez años reportaba once, con las operaciones, el CAGR y el benchmark del año extra incluidos, sin error alguno y con métricas coherentes entre sí. Ahora `warmup_bars` (o `evaluation_start_date`) separa la ventana de datos de la ventana de evaluación: las barras de calentamiento ceban los indicadores y no llegan a nada más ([#1240](https://github.com/HKUDS/Vibe-Trading/issues/1240)). **Nuevo:** `quantlib` incorpora la valoración con volatilidad estocástica de Heston (1993), Paridad de Riesgo Jerárquica, cópulas gaussianas y arquimedianas, estimadores de microestructura (VPIN, Roll, Amihud, Kyle) y griegas de barrera por diferencias finitas — 306 funciones probadas en 23 módulos ([#1195](https://github.com/HKUDS/Vibe-Trading/pull/1195)–[#1198](https://github.com/HKUDS/Vibe-Trading/pull/1198), [#1203](https://github.com/HKUDS/Vibe-Trading/pull/1203)). **Corregido:** ocho enlaces de referencia de skills apuntaban a rutas que `read_file` no puede abrir, por lo que esos documentos fallaban en silencio al cargarse. ¡Gracias [@cgycorey](https://github.com/cgycorey), [@santhreal](https://github.com/santhreal), [@turtle696966969696](https://github.com/turtle696966969696) y [@wanderkiller](https://github.com/wanderkiller)!
- **2026-08-27** 🛑 **El barrido del kill-switch sobrevive a los reinicios y deja de confiar en una conexión de bróker inestable**: durante un halt, el barrido de cancelación y cierre de posiciones contaba cualquier respuesta del bróker como éxito — pero el adaptador MCP convierte una llamada fallida en un sobre `{"status": "error"}`, de modo que una desconexión producía un rastro de auditoría de apariencia correcta mientras la orden pendiente seguía viva; los sobres de error ahora fallan cerrado en ambas fases ([#1232](https://github.com/HKUDS/Vibe-Trading/pull/1232)). El pestillo de "disparo único" del barrido además vivía solo en memoria: un reinicio con las órdenes de cierre aún en vuelo repetía el barrido entero — una orden a mercado nueva por posición, suficiente para convertir una cuenta larga en neta corta; el pestillo ahora se persiste junto al centinela HALT y queda ligado a ese episodio de halt, así que limpiar y volver a disparar lo rearma ([#1233](https://github.com/HKUDS/Vibe-Trading/pull/1233)). **Nuevo:** el orden de respaldo de las fuentes de datos de cada mercado es visible y reordenable en *Settings → Data Source Priority* — aplicación en caliente, persistido por mercado (`MARKET_DATA_ORDER_*`), y estrictamente una reordenación: añadir o quitar fuentes se rechaza, y sin override los valores por defecto quedan intactos ([#1231](https://github.com/HKUDS/Vibe-Trading/pull/1231)); los resultados de conciliación de Binance USD-M se registran como artefactos de evidencia de deriva a prueba de manipulación — JSON estricto, fallo cerrado ante instantáneas incompletas o no soportadas, sin superficie de órdenes ([#1230](https://github.com/HKUDS/Vibe-Trading/pull/1230), hacia [#1030](https://github.com/HKUDS/Vibe-Trading/issues/1030)). ¡Gracias [@he-yufeng](https://github.com/he-yufeng), [@sambazhu](https://github.com/sambazhu) y [@honginp](https://github.com/honginp)!
- **2026-08-26** ♻️ **Una orden Alpaca en vivo que pierde la respuesta del bróker deja de ser un misterio, y los backtests de oro dejan de ser sin fricción**: la puerta de órdenes registra de forma duradera la propiedad de cada envío antes de escribir al bróker, recupera el desenlace solo por el `client_order_id` exacto, atribuye las ejecuciones contra el delta de posición con signo y dispara el HALT ante cualquier contradicción — la recuperación jamás reenvía ([#1213](https://github.com/HKUDS/Vibe-Trading/pull/1213), [#1221](https://github.com/HKUDS/Vibe-Trading/pull/1221), [#1222](https://github.com/HKUDS/Vibe-Trading/pull/1222)). **Corregido:** los metales usaban las convenciones FX de pip y lote, dejando el spread del oro ~1.460× más barato y redondeando a cero las posiciones bajo 1.000 oz ([#1226](https://github.com/HKUDS/Vibe-Trading/pull/1226)); las posiciones HKD de Futu se valoraban como USD, sobrestimadas por el tipo USD/HKD ([#1228](https://github.com/HKUDS/Vibe-Trading/pull/1228)); Shadow Account leía claves de métricas que el runner nunca emite y cada backtest exitoso reportaba PnL = 0.00 ([#1217](https://github.com/HKUDS/Vibe-Trading/pull/1217)); las llamadas LLM en streaming nunca pedían usage, infrarreportando los tokens de salida del swarm ~18–36× ([#1225](https://github.com/HKUDS/Vibe-Trading/pull/1225)). **Nuevo:** snapshots de cuenta Binance USD-M de solo lectura (opt-in) — solo dos lecturas firmadas en lista de permitidos, sin superficie de órdenes ([#1229](https://github.com/HKUDS/Vibe-Trading/pull/1229), hacia [#1030](https://github.com/HKUDS/Vibe-Trading/issues/1030)); las reconexiones OAuth de la cartera corren en un subproceso acotado que no puede colgar el proceso web ni retener el puerto de callback ([#1211](https://github.com/HKUDS/Vibe-Trading/pull/1211)). ¡Gracias [@Elfsa-Miranda](https://github.com/Elfsa-Miranda), [@P1Piyush](https://github.com/P1Piyush), [@JaxonHu1024](https://github.com/JaxonHu1024), [@he-yufeng](https://github.com/he-yufeng), [@honginp](https://github.com/honginp) y [@goatyyc](https://github.com/goatyyc)!
- **2026-08-25** 🛡️ **Cerrados dos fail-open en las puertas de trading en vivo, y el purged CV deja de borrar el entrenamiento entre bloques de test**: Un corto de Alpaca se contabilizaba como exposición *positiva* (`qty` es magnitud y la dirección va en `side`), así que vender más aflojaba `max_total_exposure_usd` — la cantidad ahora lleva signo en las rutas TAP JSON y SDK directa ([#1209](https://github.com/HKUDS/Vibe-Trading/pull/1209)); las lecturas de OKX/Futu aplanaban una llamada API rechazada en «libro vacío, `status: ok`», dejando a la puerta de mandato evaluar límites contra nada — ahora devuelven el sobre de error con el que la puerta falla cerrada ([#1212](https://github.com/HKUDS/Vibe-Trading/pull/1212)). Ambos son la Fase 0 de la hoja de ruta de auditoría en [#1207](https://github.com/HKUDS/Vibe-Trading/issues/1207). **Corregido:** el purged CV combinatorio trataba bloques de test no contiguos como un solo tramo y purgaba todo el entrenamiento entre ellos; ahora cada segmento purga por separado y un fold vaciado lanza un error ([#1204](https://github.com/HKUDS/Vibe-Trading/pull/1204)); las funciones de riesgo de crédito rechazan entradas NaN/inf en lugar de devolver puntuaciones NaN o un veredicto de «zona gris» ([#1215](https://github.com/HKUDS/Vibe-Trading/pull/1215), cierra [#1214](https://github.com/HKUDS/Vibe-Trading/issues/1214)). **Nuevo:** los reintentos de los workers del swarm usan retroceso equal-jitter acotado ([#1210](https://github.com/HKUDS/Vibe-Trading/pull/1210), hacia [#1208](https://github.com/HKUDS/Vibe-Trading/issues/1208)); y `vibe-trading --swarm-retry <run_id>` / `/swarm retry` relanza una ejecución fallida, conservando las tareas completadas con `--resume` ([#1194](https://github.com/HKUDS/Vibe-Trading/pull/1194)). ¡Gracias [@he-yufeng](https://github.com/he-yufeng), [@santhreal](https://github.com/santhreal), [@Robin1987China](https://github.com/Robin1987China), [@pengpengyi92](https://github.com/pengpengyi92) y [@SiMinus](https://github.com/SiMinus)!
- **2026-08-24** 🔗 **El MCP oficial de IBKR pasa de «listar herramientas» a ser una fuente de cartera de solo lectura que funciona, y la programación gana una herramienta de agente que no puede actuar sola**: [#1178](https://github.com/HKUDS/Vibe-Trading/pull/1178) corrigió la URL, pero la pasarela de IBKR seguía rechazando el registro de cliente OAuth estándar de FastMCP antes del inicio de sesión. Un proveedor OAuth específico de IBKR — cabeceras de perfil de navegador, `token_endpoint_auth_method: none`, puerto de callback estable y recuperación de registros obsoletos, aplicado solo cuando el host MCP es `api.ibkr.com` — completa la autorización ([#1186](https://github.com/HKUDS/Vibe-Trading/pull/1186)), y las herramientas `get_account_summary` / `get_account_positions`, verificadas con una cuenta real, respaldan ahora las lecturas genéricas de cuenta/posiciones, con lo que `ibkr-live-official-mcp-readonly` es una fuente elegible para `/portfolio` ([#1190](https://github.com/HKUDS/Vibe-Trading/pull/1190), cierra [#1126](https://github.com/HKUDS/Vibe-Trading/issues/1126)). **Nuevo:** el agente ve exactamente una herramienta de programación, `scheduled_research` — sus `propose_create`/`propose_cancel` nunca tocan el almacén de jobs hasta que confirmas en la superficie en la que estás (tarjeta web, `y/N` en la CLI, o una respuesta exacta `confirm`/`确认` en IM), los destinos de entrega son referencias opacas configuradas por el operador que nunca exponen un chat/user id crudo, y un job que supera su `end_at` expira en lugar de volver a dispararse ([#1187](https://github.com/HKUDS/Vibe-Trading/pull/1187)). **Corregido:** los motores de comps y de tres estados ahora rechazan entradas no finitas en cada punto donde entran a la aritmética — una métrica NaN de un comparable se *incluía* en la distribución de múltiplos y arrastraba la mediana a NaN, y `abs(nan) > tolerance` es `False`, así que un balance NaN pasaba la comprobación dura ([#1184](https://github.com/HKUDS/Vibe-Trading/pull/1184), cierra [#1183](https://github.com/HKUDS/Vibe-Trading/issues/1183)); `get_market_data` valida codes, fechas, source e interval antes de quemar la cadena de fallback de loaders en una llamada malformada, y su enum de sources dejó de rechazar en silencio seis loaders registrados ([#1185](https://github.com/HKUDS/Vibe-Trading/pull/1185)); el login QR de Feishu ahora persiste las credenciales que solo recibe una vez — de forma atómica y con permisos solo del propietario ([#1188](https://github.com/HKUDS/Vibe-Trading/pull/1188)); la fórmula del estadístico de orden del VaR histórico en la doc de la skill risk-analysis coincide ahora con el código ([#1189](https://github.com/HKUDS/Vibe-Trading/pull/1189)). ¡Gracias [@sykuang](https://github.com/sykuang), [@goatyyc](https://github.com/goatyyc), [@AirHua-byte](https://github.com/AirHua-byte), [@Robin1987China](https://github.com/Robin1987China), [@cgycorey](https://github.com/cgycorey) y [@youngjincho02-arch](https://github.com/youngjincho02-arch)!
- **2026-08-23** 🔌 **La semilla MCP de IBKR apuntaba a la URL equivocada, y cerrar un adaptador LLM los cerraba todos**: La semilla del perfil oficial de IBKR MCP de solo lectura, el README y `SKILL.md` apuntaban a `https://api.ibkr.com/v1/api/mcp`; la propia página de integración con IA de IBKR publica `https://api.ibkr.com/v1/api/mcp-public`, y ahora la semilla, los seis README y `SKILL.md` la usan. Vuelve a ejecutar `vibe-trading connector configure ibkr-live-official-mcp-readonly --yes` si tu `agent.json` aún conserva la URL antigua. El paso de registro del cliente OAuth que la pasarela de IBKR rechaza sigue abierto en [#1126](https://github.com/HKUDS/Vibe-Trading/issues/1126) ([#1178](https://github.com/HKUDS/Vibe-Trading/pull/1178)). **Corregido:** `ChatLLM.close()` cerraba los clientes HTTPX en caché de todo el proceso de LangChain, así que una sola llamada terminada de generación de título o de visión de imágenes dejaba todas las peticiones posteriores fallando con "client has been closed" hasta reiniciar — ahora solo se cierran los transportes creados por el propio Vibe-Trading ([#1182](https://github.com/HKUDS/Vibe-Trading/pull/1182)); un reinicio del servicio a mitad de respuesta descartaba el texto ya transmitido y dejaba el intento en *running* para siempre — ahora las respuestas parciales se guardan como checkpoints y se reconcilian en el siguiente arranque como una entrada *interrupted* explícita ([#1180](https://github.com/HKUDS/Vibe-Trading/pull/1180)). **Nuevo:** el chat web adjunta hasta cinco archivos por turno mediante el selector, arrastrar y soltar o pegar desde el portapapeles ([#1179](https://github.com/HKUDS/Vibe-Trading/pull/1179)). ¡Gracias [@c020627](https://github.com/c020627) y [@AirHua-byte](https://github.com/AirHua-byte)!
- **2026-08-22** 💼 **Una página de Cartera: tus posiciones en todos los brókers, en solo lectura**: Elige perfiles de conector de solo lectura (instancias de conexión sobre `account.read` + `positions.read`; el perfil oficial MCP de IBKR aún no es elegible) y la nueva página `/portfolio` los agrega en instantáneas inmutables con procedencia por fuente, valoración en USD/CNY, exportación CSV y un gráfico histórico. Una fuente que no logra actualizarse se reporta como **error y queda excluida de los totales** — nunca se arrastra la caché anterior — y la instantánea se marca incompleta. La herramienta de agente `portfolio_summary` devuelve `risk_xray_args` que alimentan al `portfolio_risk_xray` existente, y `vibe-trading portfolio show|refresh|sources` imprime la misma instantánea en la terminal. Los conectores de solo lectura que escribas tú viven en `~/.vibe-trading/connectors/` (un manifiesto que declare cualquier capacidad de escritura se rechaza; los secretos van al llavero del sistema vía el extra `[keyring]`), y nada en esta ruta puede colocar una orden ([#1072](https://github.com/HKUDS/Vibe-Trading/pull/1072), hacia [#1171](https://github.com/HKUDS/Vibe-Trading/issues/1171)). **Corregido:** trece factores del Alpha Zoo rellenaban hacia delante un cierre faltante antes de calcular retornos, convirtiendo un hueco de datos en un «retorno del 0 %» finito — el hueco ahora se mantiene `NaN` ([#1172](https://github.com/HKUDS/Vibe-Trading/pull/1172)); clientes MCP independientes en un mismo servidor http/sse compartían una única sesión de objetivo de investigación de reserva ([#1173](https://github.com/HKUDS/Vibe-Trading/pull/1173)); la recolección de basura y la compresión de memoria dejaban filas FTS obsoletas y sidecars de relaciones huérfanos ([#1174](https://github.com/HKUDS/Vibe-Trading/pull/1174)); `cancel_run()` nunca llegaba a un worker swarm que ya transmitía — la parada ahora interrumpe el flujo, omite las llamadas de ese turno y queda como tarea *cancelada* ([#1175](https://github.com/HKUDS/Vibe-Trading/pull/1175)); `get_research_reports` por MCP descartaba `beginTime`/`endTime` ([#1176](https://github.com/HKUDS/Vibe-Trading/pull/1176)); `get_options_chain` respondía a un vencimiento de otro ciclo con `ok: true` y los contratos de otra fecha ([#1177](https://github.com/HKUDS/Vibe-Trading/pull/1177)). ¡Gracias [@goatyyc](https://github.com/goatyyc), [@Shizoqua](https://github.com/Shizoqua) y [@cgycorey](https://github.com/cgycorey)!
- **2026-08-21** ⏱️ **Ejecuciones colgadas para siempre**: El tiempo límite de `bash` mataba el shell pero no a los nietos que retenían sus descriptores de tubería, así que una ejecución quedaba «en ejecución» más de 20 minutos. Ahora los comandos se lanzan en su propio grupo de procesos y el tiempo límite mata el árbol completo, un vigilante de estancamiento termina una ejecución que no avanza, y la compactación dejó de descartar los registros de verificación del propio modelo ([#1169](https://github.com/HKUDS/Vibe-Trading/pull/1169)). **Corregido:** el histórico de Tencent de varios años se truncaba en silencio a 500 barras ([#1154](https://github.com/HKUDS/Vibe-Trading/pull/1154)). **Nuevo:** las ejecuciones swarm reproducen solo su subgrafo fallido ([#1158](https://github.com/HKUDS/Vibe-Trading/pull/1158), cierra [#1157](https://github.com/HKUDS/Vibe-Trading/issues/1157)); Market Watch muestra el último veredicto de cada monitor en la lista ([#1156](https://github.com/HKUDS/Vibe-Trading/pull/1156), cierra [#943](https://github.com/HKUDS/Vibe-Trading/issues/943)); `quantlib` alcanza 286 funciones probadas ([#1159](https://github.com/HKUDS/Vibe-Trading/pull/1159)–[#1168](https://github.com/HKUDS/Vibe-Trading/pull/1168)). ¡Gracias [@wiliao](https://github.com/wiliao), [@cgycorey](https://github.com/cgycorey), [@he-yufeng](https://github.com/he-yufeng), [@BigFishEmily](https://github.com/BigFishEmily), [@santhreal](https://github.com/santhreal), [@SiMinus](https://github.com/SiMinus) y [@alinv0](https://github.com/alinv0)!
- **2026-08-20** 🚀 **Se lanza v0.1.14** ([Notas de la versión](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.14), `pip install -U vibe-trading-ai`): 272 commits y 74 pull requests fusionados desde 0.1.13. **El titular es que un backtest terminado ya es algo que se puede leer, y no una carpeta de CSV.** Run Detail gana cuatro pestañas — **Investigación de factores** (serie diaria de IC con su línea media, estadísticas de IC, curvas de equity por quintiles y una matriz de correlación de IC que no existía en ninguna parte), **Posiciones** (tarta/treemap de pesos con deslizador de fechas, barras de exposición neta por sector y área de evolución de pesos — la tarta es composición **bruta** y las barras son **netas**, así que un par largo/corto en un mismo sector se anula en las barras mientras ambas patas siguen visibles en la tarta), **Tearsheet** (mapa de calor de rentabilidades mensuales, barras anuales y las 5 mayores caídas anotadas sobre la curva de equity) y un **panel de investigación** interactivo con KPIs, equity relativa al índice, Sharpe móvil y el libro de operaciones completo. Las cuatro leen artefactos que la ejecución ya escribe: ninguna canalización de datos nueva. La nueva página **Options Lab** añade un diagrama de pagos al vencimiento, una matriz de escenarios spot×IV, las griegas de la cartera y una cadena de opciones en vivo, calculadas con el mismo motor fijado por tests que usan las herramientas MCP. **Instalación:** los Mac Intel vuelven a poder hacer `pip install vibe-trading-ai` — `smartmoneyconcepts` arrastraba `llvmlite`, que desde 0.46 no publica wheel para macOS x86_64, de modo que toda instalación en Intel se convertía en una compilación desde fuente con CMake; ahora es el extra opcional `[smc]` y el tope obsoleto `<3.14` desaparece ([#1035](https://github.com/HKUDS/Vibe-Trading/discussions/1035)). **Novedades:** **descubrimiento de estrategias con puerta de evidencia** sobre el Alpha Zoo y el almacén SDM, con ruta de población, frescura calculada en lectura (`fresh`/`aging`/`stale`) y filas obsoletas que salen fail-closed de las recomendaciones por defecto; investigación programada que **se entrega sola** a través de una bandeja de salida con lease y que persiste el veredicto de cada monitor para la lista de Market Watch; siete endpoints de solo lectura de **Futu**; **Vietnam (HOSE)** como mercado de backtest; **conciliación de cuenta USD-M** offline; los proveedores **Novita AI** y **GitHub Copilot**; una fuente de datos **MetaTrader 5** alojada; los idiomas **español** y **alemán**; y MCP crece a 74 herramientas. **Corrección de errores:** la suite de tests dejó de escaparse hacia tu raíz de configuración real, donde cada ejecución completa venía añadiendo registros `order_rejected` sintéticos al libro de auditoría encadenado por hash; `build_registry()` ya no devuelve en silencio una lista de herramientas incompleta; `xirr` sobrevive al subdesbordamiento del descuento a largo plazo y el DCF rechaza entradas no finitas en lugar de devolver un valor por acción negativo; los símbolos `.VN` dejaron de ejecutarse bajo reglas de acciones A chinas; el archivo de backtest dejó de mezclar los artefactos de dos ejecuciones; y una amplia pasada de grounding terminó con una clase de rechazos falsos sobre fechas, listas ordenadas, constantes de identidad en fórmulas de tasas y líneas de orden leídas como cotizaciones. Gracias @Shizoqua, @shadowinlife, @pengpengyi92, @cgycorey, @ofeksh-tr, @lorenzozanee, @AndyLongest, @zzz607, @wiliao, @jay79-boop, @Robin1987China, @Echoandelementwebsites, @zhiwuyazhe-fjr, @x-lambda, @sykuang, @straun-repo, @nstavros, @ngoanpv, @miguelangelo78, @lukiod, @jax-novita, @honginp, @he-yufeng, @fixXxerTech, @er-s-an, @daviddaco1, @birdxs, @QCYTSN, @549236606-oss y @1psconstructor.
- **2026-08-19** 🔌 **Ejecuciones congeladas, una conexión filtrada por tarea y Macs Intel que no podían instalar**: un proveedor que se quedaba en silencio congelaba la ejecución indefinidamente; el nuevo `VIBE_TRADING_LLM_TIMEOUT_SECONDS` (300s por defecto) acota la llamada, y el marcado de tool-call nunca se publica como respuesta final ([#1105](https://github.com/HKUDS/Vibe-Trading/pull/1105)). Cada tarea del swarm filtraba una conexión HTTP del pool ([#1145](https://github.com/HKUDS/Vibe-Trading/pull/1145), cierra [#1141](https://github.com/HKUDS/Vibe-Trading/issues/1141)). También corregido: el fallo de `vibe-trading show <run_id>` ([#1147](https://github.com/HKUDS/Vibe-Trading/pull/1147), cierra [#1146](https://github.com/HKUDS/Vibe-Trading/issues/1146)), la sobrescritura de entregas en curso ([#1140](https://github.com/HKUDS/Vibe-Trading/pull/1140)), la pérdida de evidencia de validación del backtest ([#1139](https://github.com/HKUDS/Vibe-Trading/pull/1139)), la paginación MCP ([#1137](https://github.com/HKUDS/Vibe-Trading/pull/1137), [#1138](https://github.com/HKUDS/Vibe-Trading/pull/1138)) y los valores no finitos en mercados de predicción ([#1136](https://github.com/HKUDS/Vibe-Trading/pull/1136)). **Nuevo:** siete endpoints de solo lectura de Futu ([#1135](https://github.com/HKUDS/Vibe-Trading/pull/1135)) y un chip explícito `Inferred` en los títulos de estrategia inferidos ([#1134](https://github.com/HKUDS/Vibe-Trading/pull/1134)). **Instalación:** `smartmoneyconcepts` pasa a ser el extra `[smc]` — el `llvmlite` que arrastraba no publica wheel para macOS x86_64, así que cada instalación en un Mac Intel se convertía en una compilación desde fuente con cmake ([#1035](https://github.com/HKUDS/Vibe-Trading/discussions/1035)); el tope `<3.14` desaparece con él. Gracias [@wiliao](https://github.com/wiliao), [@cgycorey](https://github.com/cgycorey), [@Shizoqua](https://github.com/Shizoqua), [@Echoandelementwebsites](https://github.com/Echoandelementwebsites), [@549236606-oss](https://github.com/549236606-oss) y [@fixXxerTech](https://github.com/fixXxerTech).
- **2026-08-18** 🈶 **Los informes correctos dejaron de rechazarse, y los backtests dejaron de operar ruido**: `\b` reconoce Unicode, así que `最` cuenta como carácter de palabra y `(2026-07-14最低)` no tenía frontera después del día: la fecha sobrevivía al enmascarado y `2026`, `7` y `14` llegaban a la verificación OHLC como precios que ningún rango observado puede contener ([#1132](https://github.com/HKUDS/Vibe-Trading/pull/1132), cierra [#1122](https://github.com/HKUDS/Vibe-Trading/issues/1122)). Con él se fueron otros cuatro rechazos de la misma familia: una fecha de sesión con guion (`08-10(一)`), un nivel expresado como rango que dejaba `-20` detrás, una línea GTC (`100 @ $3.50`) leída como dos cotizaciones observadas, y una celda de fecha con formato de informe que no coincidía con ninguna fila de evidencia. **Backtests:** `position_adjustment="hold"` descartaba en silencio un cambio de tamaño solicitado, y `"rebalance"` no tenía banda de deriva alguna: medido, un movimiento diario del 0,01 % volvía a fijar la posición en 19 de 30 barras, de modo que una estrategia con su propio `rebalance_freq` operaba igualmente en cada barra. Las solicitudes descartadas ahora se informan, y `rebalance_tolerance` es la banda que los profesionales describen como "rebalancear cuando los pesos se muevan más de X"; su valor por defecto `0.0` deja intacta cualquier ejecución existente. Además, diecinueve alfas alpha101 neutralizadas por industria se omitían en cada bench de SP500 por falta de una etiqueta de sector que ya estaba en la tabla de la que provienen los constituyentes. **Novedades:** un monitor de Market Watch puede enviar su informe a un canal de mensajería cuando la ejecución termina, a través de un outbox persistido que un reinicio no puede perder y que un barrido concurrente no puede duplicar ([#942](https://github.com/HKUDS/Vibe-Trading/issues/942)); **el alemán es el séptimo idioma de la interfaz** ([#1117](https://github.com/HKUDS/Vibe-Trading/pull/1117)); `run_dcf` rechaza entradas no finitas en lugar de devolver un precio por acción negativo y verosímil ([#1121](https://github.com/HKUDS/Vibe-Trading/pull/1121), cierra [#1120](https://github.com/HKUDS/Vibe-Trading/issues/1120)); la respuesta de `get_market_data` en MCP incluye el `_provenance` que su propio docstring prometía ([#1131](https://github.com/HKUDS/Vibe-Trading/pull/1131)); un módulo de herramientas que falla al importarse se nombra en vez de reducir el registro en silencio ([#1129](https://github.com/HKUDS/Vibe-Trading/pull/1129), cierra [#1124](https://github.com/HKUDS/Vibe-Trading/issues/1124)); y la conciliación de cuenta USD-M sin conexión compara el estado de riesgo local con una observación del exchange sin abrir ninguna conexión ([#1106](https://github.com/HKUDS/Vibe-Trading/pull/1106)). **También:** importar `backtest.runner` ya no carga un `.env` en el proceso, algo que volvía poco fiable una ejecución local de toda la suite en cualquier máquina que tuviera uno ([#1123](https://github.com/HKUDS/Vibe-Trading/issues/1123)). Gracias [@Robin1987China](https://github.com/Robin1987China), [@newgo](https://github.com/newgo), [@er-s-an](https://github.com/er-s-an), [@Shizoqua](https://github.com/Shizoqua), [@1psconstructor](https://github.com/1psconstructor), [@honginp](https://github.com/honginp), [@cgycorey](https://github.com/cgycorey), [@alinv0](https://github.com/alinv0) y [@jelech](https://github.com/jelech).
- **2026-08-17** 🔒 **La suite de pruebas dejó de escribir en tu raíz de configuración real, incluido el libro de auditoría en vivo**: Ejecutar la propia suite del proyecto añadía registros `order_rejected` fabricados a `~/.vibe-trading/live/audit.jsonl`, un libro solo-de-adición encadenado por hash cuyo valor completo consiste en que sus entradas no se pueden fabricar; en Windows dejaba además un archivo de cadena corrupto. `conftest.py` no tenía ningún aislamiento de la raíz de configuración, así que cualquier módulo que fijara `Path.home() / ".vibe-trading"` en tiempo de importación resolvía contra el home real en **cualquier** plataforma: Windows era peor solo porque allí `Path.home()` lee `%USERPROFILE%` e ignora `$HOME`, dejando inerte el modismo de aislamiento que la suite venía usando. Ahora el home se redirige antes de la recolección, el sandbox posee una sola perilla para que el aislamiento por prueba siga ganando, y el final de la sesión afirma que los libros reales son idénticos byte a byte en lugar de solo comprobar que la redirección estaba instalada ([#1118](https://github.com/HKUDS/Vibe-Trading/pull/1118), cierra [#1116](https://github.com/HKUDS/Vibe-Trading/issues/1116)). Además: `xirr` y `money_weighted_return` lanzaban `ZeroDivisionError` en horizontes de más de ~51 años, donde el factor de descuento se desborda a cero — exactamente los flujos largos e irregulares para los que existe XIRR ([#1119](https://github.com/HKUDS/Vibe-Trading/pull/1119)); y un backtest archivado en una ejecución activa se fusionaba con los artefactos del anterior, de modo que un solo informe podía describir dos backtests distintos mientras `/runs/{id}` listaba los restos como propios ([#1094](https://github.com/HKUDS/Vibe-Trading/issues/1094)). Gracias a [@lorenzozanee](https://github.com/lorenzozanee), [@straun-repo](https://github.com/straun-repo) y [@pengpengyi92](https://github.com/pengpengyi92)!
- **2026-08-16** 🔧 **Las ejecuciones con Anthropic ya no mueren en las rutas de recuperación, y la búsqueda de símbolos deja de reportar resultados vacíos como si fueran correctos**: Los mensajes `system` que las rutas de recuperación añadían a mitad de conversación los rechaza la API de Anthropic, matando la ejecución; el direccionamiento de recuperación viaja ahora como mensajes de usuario con etiquetas `<system>` en línea ([#1112](https://github.com/HKUDS/Vibe-Trading/pull/1112), cierra [#1109](https://github.com/HKUDS/Vibe-Trading/issues/1109)). `search_symbol` devolvía cero candidatos para consultas ticker+nombre mientras ambas fuentes reportaban `ok`, así que la identidad nunca se bloqueaba y todas las herramientas de datos rechazaban la petición; la vía de Yahoo marca ahora esas consultas como `skipped` en vez de un `ok` engañoso ([#1114](https://github.com/HKUDS/Vibe-Trading/pull/1114), cierra [#1108](https://github.com/HKUDS/Vibe-Trading/issues/1108)). Además: `LANGCHAIN_REASONING_EFFORT` ya se aplica en la rama de Anthropic mediante una lista de modelos permitida ([#1115](https://github.com/HKUDS/Vibe-Trading/pull/1115)); el cargador de Tencent se recupera de `CERTIFICATE_VERIFY_FAILED` con el paquete CA de certifi ([#1113](https://github.com/HKUDS/Vibe-Trading/pull/1113)); la derivación `revenue - cogs` del beneficio bruto deja de ser código muerto ([#1111](https://github.com/HKUDS/Vibe-Trading/pull/1111)); y los trabajadores del swarm recortan con el helper compartido, así que el subagente siempre ve el aviso de recorte ([#1110](https://github.com/HKUDS/Vibe-Trading/pull/1110)). ¡Gracias a [@lorenzozanee](https://github.com/lorenzozanee), [@straun-repo](https://github.com/straun-repo), [@x-lambda](https://github.com/x-lambda), [@cgycorey](https://github.com/cgycorey) y [@Shizoqua](https://github.com/Shizoqua)!
- **2026-08-15** 🛡️ **Actualizaciones de escritorio más seguras, empaquetado fiable en Windows e investigación factorial en Run Detail**: El límite del updater inactivo conserva ahora la evidencia de los procesos propios para reintentar la limpieza, comprueba listeners TCP en vez de HTTP health, reserva el recovery journal de forma atómica, vincula Authenticode y los hashes a los mismos bytes preparados y vuelve a verificarlos justo antes del lanzamiento ([#1101](https://github.com/HKUDS/Vibe-Trading/pull/1101)). El empaquetado de Windows gestiona descargas de Electron acotadas y verificadas por checksum, y extrae el asset GTK fijado como datos mediante 7-Zip en vez de ejecutar su instalador antiguo e inestable; la CI nativa de Windows cubre códigos de salida, timeouts, ensamblado del runtime, NSIS y arranque del paquete ([#1104](https://github.com/HKUDS/Vibe-Trading/pull/1104), cierra [#1093](https://github.com/HKUDS/Vibe-Trading/issues/1093)). Run Detail incorpora series y estadísticas de IC, quantile equity y correlación de IC, con recorrido acotado de artifacts y valores JSON finitos ([#1099](https://github.com/HKUDS/Vibe-Trading/pull/1099), cierra [#1100](https://github.com/HKUDS/Vibe-Trading/issues/1100)); los universal hash locks también se verifican de forma nativa en Linux, macOS ARM64 y Windows ([#1102](https://github.com/HKUDS/Vibe-Trading/pull/1102), cierra [#1089](https://github.com/HKUDS/Vibe-Trading/issues/1089)). ¡Gracias a [@QCYTSN](https://github.com/QCYTSN) y [@shadowinlife](https://github.com/shadowinlife)!
- **2026-08-14** ⚙️ **Un ajuste de razonamiento que no hacía nada, y ejecuciones que se detenían cuando aún podían recuperarse**: `LANGCHAIN_REASONING_EFFORT` era silenciosamente inocuo en casi todos los proveedores — solo OpenAI directo llegaba a recibirlo, así que poner `high` en DeepSeek no cambiaba nada y no lo advertía en ninguna parte. Ahora el ajuste llega a ambos transportes mediante el campo propio de cada adaptador: Chat Completions por defecto, y la API de Responses cuando `LANGCHAIN_USE_RESPONSES_API=true`. Los proveedores que reciben un `reasoning_effort` de primer nivel son una **lista de permitidos verificada**, no "todo lo que habla el formato de OpenAI" — un endpoint que valida su cuerpo de petición con rigor rechaza la clave desconocida y hace fallar la llamada entera, así que el coste de equivocarse es cada petición, no un ajuste que no surte efecto ([#1025](https://github.com/HKUDS/Vibe-Trading/pull/1025)). La verificación de evidencia tampoco devuelve ya "confirma y continúa" mientras siga disponible una recuperación determinista de solo lectura: un instrumento sin resolver ahora impulsa `search_symbol` → `get_market_data` con su propio presupuesto acotado en vez de agotar las iteraciones y cerrarse en fallo ([#1092](https://github.com/HKUDS/Vibe-Trading/pull/1092), cierra [#1081](https://github.com/HKUDS/Vibe-Trading/issues/1081)). **Novedades:** una página **Options Lab** — diagrama de resultado multipata, matriz de escenarios precio × volatilidad implícita, griegas de la cartera y cadena de opciones en vivo, calculado por la herramienta de payoff existente y `quantlib` en lugar de una segunda implementación de las fórmulas ([#1096](https://github.com/HKUDS/Vibe-Trading/pull/1096)); una pestaña **tearsheet** de backtest con mapa de calor de rentabilidad mensual, rentabilidad anual y las N mayores caídas ([#1091](https://github.com/HKUDS/Vibe-Trading/pull/1091)); **tickerall** como la 25.ª fuente de datos de mercado — barras de forex y metales de MetaTrader 5 alojado, sin terminal local en ningún sistema operativo, solo bajo petición explícita para que una clave de bróker nunca sea un destino de repliegue silencioso, y una ventana histórica truncada es un error en vez de una serie corta sin avisar ([#968](https://github.com/HKUDS/Vibe-Trading/pull/968), cierra [#897](https://github.com/HKUDS/Vibe-Trading/issues/897)); y **Novita AI** junto con **GitHub Copilot** como proveedores integrados ([#1059](https://github.com/HKUDS/Vibe-Trading/pull/1059), [#990](https://github.com/HKUDS/Vibe-Trading/pull/990)). eToro incorpora la exploración por clase de activo según el tipo de instrumento, y la operativa de copia ahora rechaza una cuenta demo con un motivo explícito en lugar de fallar de forma opaca ([#1070](https://github.com/HKUDS/Vibe-Trading/pull/1070)). Gracias a [@cgycorey](https://github.com/cgycorey), [@Shizoqua](https://github.com/Shizoqua), [@shadowinlife](https://github.com/shadowinlife), [@miguelangelo78](https://github.com/miguelangelo78), [@jax-novita](https://github.com/jax-novita), [@sykuang](https://github.com/sykuang), y [@ofeksh-tr](https://github.com/ofeksh-tr).
- **2026-08-13** 🎯 **Los informes de backtest muestran la cartera que realmente se ejecutó**: `positions.csv` contenía los pesos *objetivo* del optimizador, así que un informe podía declarar una exposición del 80% mientras el redondeo de lotes, las comisiones o una orden bloqueada dejaban la cartera cerca del 20% — y esos mismos objetivos alimentaban las métricas de peso invertido y la radiografía de riesgo. Las ejecuciones van ahora a `positions.csv` y las solicitudes a `target_positions.csv` ([#1082](https://github.com/HKUDS/Vibe-Trading/pull/1082)). Run Detail incorpora un **panel de investigación** en `?view=dashboard` ([#1084](https://github.com/HKUDS/Vibe-Trading/pull/1084)), y **el español es el sexto idioma de la interfaz** ([#1087](https://github.com/HKUDS/Vibe-Trading/pull/1087)). Además: `get_research_reports` devolvía HTTP 400 para todos los símbolos de acciones A ([#1077](https://github.com/HKUDS/Vibe-Trading/pull/1077)); las cotizaciones de IBKR separan el nivel solicitado del aplicado ([#1075](https://github.com/HKUDS/Vibe-Trading/pull/1075)); `.env.partial` se escribe de forma atómica ([#1086](https://github.com/HKUDS/Vibe-Trading/pull/1086)); el flujo de Docker fija las actions a commits y bloquea por hash los SDK de canales ([#1088](https://github.com/HKUDS/Vibe-Trading/pull/1088)); y la puerta de grounding deja de leer escalones de soporte/resistencia y máximos históricos como precios observados ([#1060](https://github.com/HKUDS/Vibe-Trading/pull/1060)). Gracias [@AndyLongest](https://github.com/AndyLongest), [@daviddaco1](https://github.com/daviddaco1), [@zzz607](https://github.com/zzz607), [@jay79-boop](https://github.com/jay79-boop), [@lukiod](https://github.com/lukiod), [@birdxs](https://github.com/birdxs) y [@wiliao](https://github.com/wiliao).
- **2026-08-12** 📏 **El volumen de acciones A ya no se dispara ×100 cuando cambia la fuente de fallback**: cinco fuentes de la cadena de fallback de acciones A informaban en lotes de mercado (board lots) mientras que BaoStock informaba en acciones individuales, y como la procedencia (provenance) del dato servido no llevaba unidad, un fallback podía reescalar silenciosamente cualquier señal basada en volumen. Los loaders ahora declaran las unidades de volumen por mercado, la procedencia expone la unidad de la fuente que realmente sirvió cada símbolo, BaoStock convierte acciones a lotes de mercado en el límite del loader, la caché v4 evita que reaparezcan entradas previas a la corrección, y una regresión de datos en vivo entre fuentes exige que los valores de días cerrados coincidan dentro de un 1% ([#1065](https://github.com/HKUDS/Vibe-Trading/pull/1065), [#1067](https://github.com/HKUDS/Vibe-Trading/pull/1067), cierra [#1062](https://github.com/HKUDS/Vibe-Trading/issues/1062)). El paquete de diez PR de corrección también le da a eToro un estado de runtime completo y una interfaz conectada al SDK en cinco idiomas ([#1051](https://github.com/HKUDS/Vibe-Trading/pull/1051)); hace que el DELETE de una ejecución programada devuelva un 204 realmente vacío ([#1068](https://github.com/HKUDS/Vibe-Trading/pull/1068)); renderiza en la CLI el payload de cuenta del SDK directo de Alpaca ([#1073](https://github.com/HKUDS/Vibe-Trading/pull/1073)); normaliza las raíces de Ollama a `/v1` en el límite de credenciales usado por el constructor de modelo real ([#1074](https://github.com/HKUDS/Vibe-Trading/pull/1074)); convierte el EOF de stdin de OAuth de Docker Codex en una guía de TTY procesable ([#1054](https://github.com/HKUDS/Vibe-Trading/pull/1054), cierra [#1050](https://github.com/HKUDS/Vibe-Trading/issues/1050)); evita que los marcadores de lista ordenada de Markdown como `1.` se conviertan en afirmaciones numéricas no soportadas ([#1063](https://github.com/HKUDS/Vibe-Trading/pull/1063)); hace que las consultas de memoria de dos caracteres como `GE` se comporten igual con o sin FTS5 ([#1071](https://github.com/HKUDS/Vibe-Trading/pull/1071)); y calcula el precio de opciones europeas de volatilidad cero a partir del valor intrínseco forward descontado, restableciendo la lógica del lado del ejercicio y la paridad put-call ([#1066](https://github.com/HKUDS/Vibe-Trading/pull/1066)). Gracias [@shadowinlife](https://github.com/shadowinlife), [@ofeksh-tr](https://github.com/ofeksh-tr), [@zhiwuyazhe-fjr](https://github.com/zhiwuyazhe-fjr), [@zzz607](https://github.com/zzz607), [@pengpengyi92](https://github.com/pengpengyi92), y [@Shizoqua](https://github.com/Shizoqua).
- **2026-08-11** 🧠 **La compactación deja de descartar contenido de la conversación, y un reintento de swarm ya no puede borrar su propia ejecución**: la autocompactación recortaba el historial serializado en un límite estricto de 80.000 caracteres antes de resumir, así que todo lo que quedaba después de ese corte no llegaba ni a la llamada de resumen ni a la cola preservada — desaparecía sin lanzar ningún error, en contra de la propia garantía de «cero pérdida de información» de la función, y el corte caía en medio de un objeto, de modo que el resumidor recibía un JSON inválido. El historial ahora se empaqueta respetando los límites de mensaje y se pliega fragmento a fragmento mediante la plantilla iterativa existente; un único mensaje demasiado grande para un fragmento se convierte en fragmentos etiquetados en lugar de truncarse, y una respuesta vacía del modelo ya no borra el resumen acumulado hasta ese momento (cierra [#1055](https://github.com/HKUDS/Vibe-Trading/issues/1055)). La nueva limpieza de artefactos en el reintento ejecutaba `shutil.rmtree` sobre `run_dir/artifacts/<agent_id>`, donde `agent_id` llega sin validar desde un preset y los presets de usuario se cargan desde `~/.vibe-trading/swarm/presets/`, de modo que un id `..` se resolvía como el propio directorio de la ejecución — ahora la ruta se rechaza a menos que sea un único segmento seguro que resuelva dentro del directorio de artefactos de esa ejecución. Además, `technical_indicators` RSI pasa a la convención Wilder-EWM que su propio docstring ya afirmaba, donde una media móvil simple puede desplazar una lectura a través del límite 30/70 ([#1056](https://github.com/HKUDS/Vibe-Trading/pull/1056)); `excess_return` se vuelve a derivar a partir del total de benchmark corregido para que ambos campos dejen de contradecirse dentro de un mismo diccionario de métricas ([#1058](https://github.com/HKUDS/Vibe-Trading/pull/1058)); la validación de entregables de swarm rechaza sobres de herramientas en bruto con claves `ok`/`success` presentados como análisis ([#1052](https://github.com/HKUDS/Vibe-Trading/pull/1052)); un worker reintentado ya no hereda el `report.md` del intento fallido ([#1053](https://github.com/HKUDS/Vibe-Trading/pull/1053)); y los prompts de worker se reordenan para que los bloques invariantes del agente formen un único prefijo apto para caché ([#1057](https://github.com/HKUDS/Vibe-Trading/pull/1057)). Gracias [@Shizoqua](https://github.com/Shizoqua) y [@Echoandelementwebsites](https://github.com/Echoandelementwebsites).
- **2026-08-10** 🚀 **Se lanza v0.1.13** ([Notas de la versión](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.13), `pip install -U vibe-trading-ai`): 408 commits y 162 pull requests fusionados desde 0.1.12 — la mayor versión hasta ahora. **El titular es una corrección, no una función: la puerta de identidad deja de rechazar respuestas para las que ya tenía la evidencia.** Una pregunta bien formada podía pasar minutos haciendo llamadas reales a herramientas y luego devolver *"no se puede confirmar de forma segura la identidad del instrumento ni la evidencia de precio"*. Las causas: `.SS` y `.SH` se trataban como instrumentos distintos, así que **todo ticker de Shanghái quedaba permanentemente ambiguo**; una consulta secundaria fallida podía degradar una identidad ya bloqueada; el HTTP 400 de Yahoo en cada consulta CJK se registraba como un *fallo* de la fuente en lugar de "no listado aquí"; una lista blanca fija por herramienta bloqueaba 11 de las 17 grafías de argumento documentadas; las respuestas en chino se rechazaban por escribir `雅虎` o `元` en lugar del nombre ASCII del loader; y un separador de miles dividía `¥1,309.22` de modo que `1` se comparaba contra el rango observado. Las preguntas conceptuales y los informes comparativos tampoco quedan ya en un callejón sin salida. Una cotización fuera de la evidencia OHLC registrada sigue rechazándose. **Novedades:** `src/quantlib` — 249 funciones probadas en 17 módulos (opciones, bonos, crédito, econometría, VaR/CVaR/EVT, atribución, estudios de eventos, CV purgada) accesibles desde la CLI, la Web UI, la REST API y MCP mediante la herramienta de solo lectura `quantlib_call`, de modo que las skills importan matemática financiera en lugar de llevar fórmulas en markdown; un **motor de valoración** (`run_dcf` / `run_comps` / tres estados financieros) cuya única regla es que un input faltante hace que un modelo NO SEA EJECUTABLE en lugar de asignarle un valor por defecto silenciosamente; una **columna vertebral de entidad + flujos de caja irregulares** (XIRR / MOIC / DPI / TVPI, TWR / Modified Dietz vía `cashflow_performance`) mantenida deliberadamente en paralelo a los motores de barras; **gobernanza en cada ejecución** — un manifiesto hash sobre el prompt, las skills, el registro de herramientas y las versiones de paquetes, más un libro de auditoría encadenado por hash y con fsync, donde incluso una edición auto-rehasheada se detecta un registro después; cuatro herramientas de datos de solo lectura sobre fuentes públicas gratuitas (SEC **13F** con diferencias trimestre a trimestre, **ETF look-through** donde un tracker del CSI-300 se resuelve en 342 posiciones que cubren el 98.66% de los activos netos en lugar del top diez trimestral, **mercados de predicción** como probabilidad implícita etiquetada, y **arXiv/OpenAlex** con afirmaciones ancladas a la fuente); seis comandos institucionales (`/comps` `/dcf` `/attrib` `/memo` `/earnings` `/screen`); lentes de inversor como skill independiente; cinco guiones de investigación programada; un **shell de escritorio Electron** con empaquetado de Windows anclado por checksum y `safeStorage`; **eToro** como decimotercer conector de broker; **Corea (KRX)** como noveno motor de backtest; un **puente a OpenBB Workspace**; acciones canadienses de punta a punta; y `sentiment`, `technical_indicators`, `options_payoff`, `orderbook_depth`, ModelScope y `vibe-trading update`. **Corrección de errores:** los períodos de la SEC se indexan por su intervalo `(start, end)` — las cifras anuales venían devolviendo un único trimestre, una subestimación de 4.2×; los precios de acciones A de Tushare están ajustados por eventos corporativos, donde una rentabilidad bruta a través de una fecha ex-dividendo se desviaba hasta 47 puntos porcentuales; `bar_returns` ya no registra una suspensión de cotización como un movimiento del 0%; la anualización cubre las 24 fuentes de datos; se cierra un hueco de sandbox donde el código generado podía importar la capa de broker o alcanzar `socket`/`subprocess` a través de un binding renombrado; y los backtests compuestos en múltiples divisas se rechazan en lugar de sumarse en una sola curva de equity. Gracias @santhreal, @shadowinlife, @Robin1987China, @he-yufeng, @QCYTSN, @Shizoqua, @honginp, @cgycorey, @wiliao, @ngoanpv, @x-lambda, @ofeksh-tr, @00EVA, @zwrong, @yrk111222, @su322, @hhj123123, @dineeshd, @sambazhu, @ddy4633, @tyj147454413-cmd, @y85998607, @JungHoonGhae, @shugaoye, @TSENGCHIENFENG, @darkknight4563, @MuggleJinx, @klmtseng, @ebujinovch, @g0rdonL, @AmirF194, @Echoandelementwebsites, @yagnikpipaliya, @dvirarad y @1anter.

- **2026-08-09** 🪟 **Empaquetado seguro para Windows, mercados de Canadá, ModelScope y Alpha Zoo sobre MCP**: el empaquetado de escritorio para Windows ahora ensambla un runtime embebido de Python 3.12 anclado por checksum y rutas de revisión/firma NSIS x64, además de `safeStorage` de Electron para un conjunto de credenciales en lista blanca. El renderer puede establecer o borrar secretos pero nunca leerlos; la configuración en texto plano se migra una sola vez; los valores descifrados solo llegan al backend propietario; y tanto las builds de revisión sin firmar como las firmadas fallan de forma cerrada ante un estado de firma incorrecto. Este PR no publicó ningún artefacto de instalador ([#1015](https://github.com/HKUDS/Vibe-Trading/pull/1015)). Las acciones canadienses ahora funcionan de punta a punta: los símbolos `.TO`/`.V` se clasifican en CAD, se enrutan a través de Yahoo → yfinance → fallback local, se ejecutan bajo las reglas GlobalEquity específicas de Canadá, se comparan contra `XIC.TO`, y se rechaza la agregación en múltiples divisas. Los backtests históricos estrictos USD-M también pueden optar por `position_adjustment=rebalance` preservando el colateral, el funding, las comisiones, el P&L realizado, el comportamiento de liquidación y la evidencia inmutable de ejecuciones a través de aumentos y reducciones ([#1024](https://github.com/HKUDS/Vibe-Trading/pull/1024), [#1019](https://github.com/HKUDS/Vibe-Trading/pull/1019), cierra [#952](https://github.com/HKUDS/Vibe-Trading/issues/952)). ModelScope se une a los proveedores integrados a través de su endpoint oficial de inferencia alojada compatible con OpenAI, con `Qwen/Qwen3.5-27B` como valor por defecto ([#1011](https://github.com/HKUDS/Vibe-Trading/pull/1011)); el nuevo `vibe-trading update` distingue instalaciones por wheel de checkouts editables/desde fuente, instala exactamente la versión que verificó y comprueba metadatos actualizados sin hacer downgrade ([#1020](https://github.com/HKUDS/Vibe-Trading/pull/1020)); y `alpha_zoo` junto con `alpha_bench` acotado ya llegan a MCP (64 herramientas), con límites de horizonte/resultado/ruta de salida y creación segura de informes ([#979](https://github.com/HKUDS/Vibe-Trading/pull/979)). Las actualizaciones verificadas de los locks de Python y frontend también actualizan dependencias agrupadas, `postcss` y `akshare` ([#1021](https://github.com/HKUDS/Vibe-Trading/pull/1021), [#1023](https://github.com/HKUDS/Vibe-Trading/pull/1023), [#1026](https://github.com/HKUDS/Vibe-Trading/pull/1026), [#1027](https://github.com/HKUDS/Vibe-Trading/pull/1027)). Gracias [@QCYTSN](https://github.com/QCYTSN), [@wiliao](https://github.com/wiliao), [@honginp](https://github.com/honginp), [@yrk111222](https://github.com/yrk111222), [@zwrong](https://github.com/zwrong), y [@cgycorey](https://github.com/cgycorey).
- **2026-08-08** 🧱 **Shell de escritorio, eToro, rebalanceo atómico y una amplia pasada de fiabilidad**: un host Electron centrado en la fuente ahora gestiona el ciclo de vida del backend existente — puerto loopback aleatorio, secreto por lanzamiento, recuperación de arranque en cinco idiomas y limpieza de procesos propios — mientras que eToro se incorpora con perfiles demo/real separados por ruta; las acciones en vivo que incrementan el riesgo siguen sujetas a mandato y auditadas, y las superficies de capacidades de la API se autentican bajo un CSP forzado ([#923](https://github.com/HKUDS/Vibe-Trading/pull/923), [#989](https://github.com/HKUDS/Vibe-Trading/pull/989), [#961](https://github.com/HKUDS/Vibe-Trading/pull/961)). Los backtests ganan rebalanceo atómico opcional en la misma dirección con evidencia inmutable de ejecuciones; Shadow divide los mercados mixtos por divisa de liquidación sin inventar agregación de FX y respeta la raíz de runtime configurada; los indicadores usan historial consecutivo sin muestrear; el drawdown con equity negativo y las cuentas cruzadas insolventes vacías se gestionan correctamente ([#951](https://github.com/HKUDS/Vibe-Trading/pull/951), [#997](https://github.com/HKUDS/Vibe-Trading/pull/997), [#1017](https://github.com/HKUDS/Vibe-Trading/pull/1017), [#1005](https://github.com/HKUDS/Vibe-Trading/pull/1005), [#958](https://github.com/HKUDS/Vibe-Trading/pull/958), [#959](https://github.com/HKUDS/Vibe-Trading/pull/959)). El OAuth de OpenAI Codex obtiene un almacén de credenciales sincronizado independiente y una recuperación 401 de un solo uso; la exclusión de proxy cubre clientes síncronos y asíncronos; las ejecuciones en sandbox conservan su raíz canónica; la investigación programada aísla registros malformados y corrige la validación de zona horaria de los intervalos; las solicitudes en minúscula `4h` devuelven barras de cuatro horas reales ([#1014](https://github.com/HKUDS/Vibe-Trading/pull/1014), [#995](https://github.com/HKUDS/Vibe-Trading/pull/995), [#1012](https://github.com/HKUDS/Vibe-Trading/pull/1012), [#1003](https://github.com/HKUDS/Vibe-Trading/pull/1003), [#1004](https://github.com/HKUDS/Vibe-Trading/pull/1004), [#1013](https://github.com/HKUDS/Vibe-Trading/pull/1013)). Las respuestas de QQ conservan los IDs de mensaje de origen, los slugs largos de modelo siguen siendo legibles, y el agente se detiene cuando la evidencia es suficiente ([#1008](https://github.com/HKUDS/Vibe-Trading/pull/1008), [#1006](https://github.com/HKUDS/Vibe-Trading/pull/1006), [#1010](https://github.com/HKUDS/Vibe-Trading/pull/1010)). Gracias [@QCYTSN](https://github.com/QCYTSN), [@Shizoqua](https://github.com/Shizoqua), [@ngoanpv](https://github.com/ngoanpv), [@hhj123123](https://github.com/hhj123123), [@su322](https://github.com/su322), [@Robin1987China](https://github.com/Robin1987China), [@shadowinlife](https://github.com/shadowinlife), [@dineeshd](https://github.com/dineeshd), [@honginp](https://github.com/honginp), [@santhreal](https://github.com/santhreal), [@00EVA](https://github.com/00EVA), [@x-lambda](https://github.com/x-lambda), [@ofeksh-tr](https://github.com/ofeksh-tr).
- **2026-08-07** 🛡️ **Menos rechazos falsos, un hueco de sandbox cerrado, QVeris en MCP**: la puerta de fundamentación (grounding) deja de rechazar respuestas bien formadas sobre números que nunca fueron precios — puntuaciones de confianza, lecturas de indicadores, ventanas de media móvil, fechas sin año como `8/5`, rangos porcentuales, y los propios niveles de disparo de un plan de trading (`close ≥ 6.45` es una condición, no una cotización) — mientras que una cotización fuera de la evidencia OHLC registrada sigue rechazándose, y una tabla de precios fechada `08-05` ahora coincide con su evidencia en lugar de que todas las celdas vuelvan como no disponibles ([#1001](https://github.com/HKUDS/Vibe-Trading/issues/1001), [#983](https://github.com/HKUDS/Vibe-Trading/issues/983)). **Sandbox:** el código de estrategia generado ya no puede importar la capa de broker, ni alcanzar `socket`/`subprocess`/`os.system`/`ctypes` a través de un binding renombrado — ambos se aceptaban antes, y `src.quantlib` sigue pudiendo importarse. **QVeris** discovery/inspect/execute se incorporan a la superficie de MCP (62 herramientas), con la cotización de coste leída desde el marketplace en lugar de confiar en la que envía el llamador ([#976](https://github.com/HKUDS/Vibe-Trading/pull/976), cierra [#964](https://github.com/HKUDS/Vibe-Trading/issues/964), gracias [@shadowinlife](https://github.com/HKUDS/Vibe-Trading/shadowinlife)). Además, se repara el enrutamiento de fallback de datos de mercado de HK con una nueva fuente Tencent HK, el crypto de yfinance se enruta al motor de cripto, las entradas de memoria se escriben y recuperan con su sufijo `.md`, los argumentos list/dict de MCP toleran clientes que envían JSON como string, y los artefactos de Portfolio Studio se muestran en el detalle de la ejecución ([#1000](https://github.com/HKUDS/Vibe-Trading/pull/1000), [#970](https://github.com/HKUDS/Vibe-Trading/pull/970), [#984](https://github.com/HKUDS/Vibe-Trading/pull/984), [#993](https://github.com/HKUDS/Vibe-Trading/pull/993), [#980](https://github.com/HKUDS/Vibe-Trading/pull/980), [#982](https://github.com/HKUDS/Vibe-Trading/pull/982), [#966](https://github.com/HKUDS/Vibe-Trading/pull/966), [#973](https://github.com/HKUDS/Vibe-Trading/pull/973), gracias [@he-yufeng](https://github.com/HKUDS/Vibe-Trading/he-yufeng), [@ngoanpv](https://github.com/HKUDS/Vibe-Trading/ngoanpv), [@sambazhu](https://github.com/HKUDS/Vibe-Trading/sambazhu)).
- **2026-08-06** 🧮 **Una capa de matemática financiera probada + motor de valoración + flujos de caja irregulares + gobernanza integrada**: `src/quantlib` sustituye las fórmulas que vivían como markdown dentro de las skills por una implementación probada de cada una — opciones, bonos, crédito, econometría, VaR/CVaR/EVT, atribución, estudios de eventos, control de pruebas múltiples, validación cruzada purgada — 265 funciones, accesibles desde la CLI, la Web UI, la REST API y MCP mediante la nueva herramienta de solo lectura `quantlib_call`. Un motor de valoración (`run_dcf` / `run_comps` / tres estados financieros) se niega a ejecutarse si falta un input en lugar de asignarle un valor por defecto silenciosamente, y una nueva columna vertebral de entidad + flujo de caja admite NAVs, capital calls y cupones (XIRR/MOIC/DPI/TVPI y TWR/Modified Dietz vía `cashflow_performance`; coste de impacto L2 de cripto vía `orderbook_depth`). Cada ejecución ahora escribe un manifiesto hash, el libro de auditoría está encadenado por hash de modo que la manipulación es detectable, y los 30 presets de swarm fueron reauditados — un entregable que ninguna herramienta concedida puede calcular ahora se declara como tal en lugar de inventarse.
- **2026-08-05** 🔭 **Tenencias institucionales, ETF look-through, mercados de predicción, papers de investigación**: cuatro herramientas de datos de solo lectura, todas sobre fuentes públicas gratuitas — libros SEC 13F con diferencias de posición trimestre a trimestre; componentes de ETF en distintos mercados (un tracker del CSI-300 se resuelve en 342 posiciones que cubren el 98.7% de los activos netos, no el top diez trimestral); contratos de eventos como probabilidad implícita etiquetada; y búsqueda en arXiv/OpenAlex que marca lo que una fuente no afirma en lugar de inferirlo. Además, cinco plantillas de investigación programada, seis comandos institucionales (`/comps` `/dcf` `/attrib` `/memo` `/earnings` `/screen`), lentes de inversor como skill independiente, y un núcleo de agente que rastrea cada número hasta la herramienta que lo produjo.
- **2026-08-04** 🔧 **Pasada de corrección: fundamentales, precios de acciones A, resultados sobredimensionados**: los períodos de reporte de la SEC ahora se indexan por su intervalo `(start, end)` — un 10-Q presenta el trimestre real y el marco año-hasta-la-fecha bajo la misma fecha de cierre y período fiscal, así que `period="annual"` venía devolviendo un único trimestre para AAPL FY2018–2020 (una subestimación de 4.2×) y cada ranura de Q4 fiscal en una serie trimestral llevaba la cifra del año completo; `get_fundamentals("AAPL.US")` ya no responde `ok:true` con un panel completamente nulo. Los precios de acciones A de Tushare ahora están ajustados por eventos corporativos tanto en el factor bench como en los backtests — una rentabilidad bruta de cierre a cierre a través de una fecha ex-dividendo se desviaba hasta 47 puntos porcentuales (300750.SZ, 2023-04-26) — y el benchmark del CSI300 enmascara cada fecha según su composición de índice vigente en ese momento (point-in-time). Los backtests compuestos entre mercados rechazan un conjunto de códigos en múltiples divisas en lugar de sumar CNY, USD y KRW en una sola curva de equity; las patas de opciones se marcan a la volatilidad con la que se abrieron, eliminando un P&L de día cero fabricado de hasta +93% de la prima; los resultados de herramientas sobredimensionados se paginan por registro completo con un total explícito en lugar de cortarse en medio del JSON; y `calc_metrics` reporta el tracking error y la beta contra el benchmark.
- **2026-08-03** ⏰ **Investigación programada con reconocimiento de zona horaria + desbloqueo del cribado de acciones**: los trabajos programados ahora aceptan un `timezone` IANA opcional y evalúan el cron según el reloj de esa zona, de modo que una cadencia sobrevive al horario de verano — se omite un hueco de adelanto de reloj y un instante ambiguo de retraso de reloj se ejecuta una sola vez — mientras que los campos de cron ganan listas separadas por comas y rangos (`1,3-5`), los trabajos sin zona horaria mantienen la semántica UTC, y la web UI gana una página **Programadas** en los cinco idiomas donde antes no había ninguna superficie de programación ([#954](https://github.com/HKUDS/Vibe-Trading/pull/954), cierra [#953](https://github.com/HKUDS/Vibe-Trading/issues/953), gracias [@ngoanpv](https://github.com/ngoanpv)). Una solicitud de cribado ya no llega a un callejón sin salida: una lista corta de muchos candidatos cuenta como una respuesta en lugar de una resolución estancada y se retira una vez que se bloquea un candidato, y la validación de precios deja de leer dígitos de ticker, fechas localizadas, cantidades de acciones y costes de posición como precios cotizados — aunque sigue rechazando cualquier cotización fuera de la evidencia OHLC registrada (cierra [#955](https://github.com/HKUDS/Vibe-Trading/issues/955)). La memoria del agente también obtiene coincidencia exacta por ancla de índice y un límite de resultados respetado ([#956](https://github.com/HKUDS/Vibe-Trading/pull/956), [#957](https://github.com/HKUDS/Vibe-Trading/pull/957), gracias [@santhreal](https://github.com/santhreal)).
- **2026-08-02** 🧠 **Descubrimiento de modelos en vivo, identidad de runtime veraz, y una actualización de dependencias verificada**: Settings ahora descubre a demanda los modelos del proveedor configurado con códigos de advertencia estables y controles en cinco idiomas, mientras que cada respuesta registra y recarga la identidad inmutable de proveedor/modelo/razonamiento que realmente la sirvió — que se limpia de forma segura cuando cambian las sesiones ([#924](https://github.com/HKUDS/Vibe-Trading/pull/924), gracias [@QCYTSN](https://github.com/QCYTSN)). Nueve actualizaciones de Python ancladas por hash más `jsdom`/`postcss` también se incorporaron con imports de versión exacta, 330 tests focalizados, el build de producción, 373 tests de frontend, el CI completo de `main`, y el Dependency Graph en verde ([#949](https://github.com/HKUDS/Vibe-Trading/pull/949), [#948](https://github.com/HKUDS/Vibe-Trading/pull/948)); el salto disruptivo a MCP 2.0 permanece sin fusionar a la espera de una migración completa de lock/runtime ([#950](https://github.com/HKUDS/Vibe-Trading/pull/950)).
- **2026-08-01** 🧮 **Analítica de estrategias de opciones + sentimiento de mercado + investigación auditable USD-M**: un nuevo flujo de payoff de opciones calcula analíticamente los extremos de P&L al vencimiento, los breakevens exactos — incluyendo intervalos continuos de P&L cero —, las comisiones de entrada alineadas con el motor, y escenarios de spot × IV a través de Agent y MCP ([#946](https://github.com/HKUDS/Vibe-Trading/pull/946), reconstruido a partir de [#883](https://github.com/HKUDS/Vibe-Trading/pull/883), gracias @he-yufeng). La herramienta de solo lectura `sentiment` puntúa texto arbitrario localmente y recupera el Fear & Greed Index de cripto sin necesitar API key ([#939](https://github.com/HKUDS/Vibe-Trading/pull/939), gracias @Robin1987China). Los backtests estrictos USD-M ahora persisten eventos ordenados de ejecución, funding, riesgo y liquidación además de un resumen de fidelidad, a la vez que rechazan intervalos 100× no soportados ([#936](https://github.com/HKUDS/Vibe-Trading/pull/936), gracias @honginp). Las mejoras de fiabilidad también garantizan que la resolución de símbolo y venue preceda a las llamadas de datos de mercado, que los precios cotizados finales se verifiquen contra la evidencia OHLC registrada, que la investigación programada reintente fallos transitorios, y que los resultados anidados de MCP se serialicen correctamente.
- **2026-07-31** 🔧 **Ciclo de vida de liquidación USD-M + indicadores técnicos + directorios de estado por usuario**: el modo opcional `perpetual_strict` liquida el funding histórico antes de las ejecuciones y ejecuta los incumplimientos de margen aislado/cruzado como liquidaciones reales ([#903](https://github.com/HKUDS/Vibe-Trading/pull/903), gracias @honginp). Una herramienta de solo lectura `technical_indicators` calcula RSI/MACD/Bollinger/SMA/EMA a través de los loaders existentes ([#921](https://github.com/HKUDS/Vibe-Trading/pull/921), refs [#920](https://github.com/HKUDS/Vibe-Trading/issues/920), gracias @Robin1987China). Las sesiones, ejecuciones, ejecuciones de swarm y subidas ahora residen bajo `~/.vibe-trading` (reubicable vía `VIBE_TRADING_HOME`) con una migración automática de una sola vez ([#925](https://github.com/HKUDS/Vibe-Trading/pull/925), cierra [#904](https://github.com/HKUDS/Vibe-Trading/issues/904), gracias @MuggleJinx). Además, un lote de diez correcciones — `.SS` de Yahoo clasificado como acción A, códigos de acciones A en formato simple/con prefijo, pares de cripto delimitados por barra, guardas de `nan`/`inf` ([#919](https://github.com/HKUDS/Vibe-Trading/pull/919), [#926](https://github.com/HKUDS/Vibe-Trading/pull/926)–[#935](https://github.com/HKUDS/Vibe-Trading/pull/935), gracias @santhreal).
- **2026-07-30** 🎨 **Web UI reconstruida + mercado de Corea (KRX) + un puente a OpenBB Workspace**: la web UI recibe su renovación de minimalismo guiado — sin parpadeo en el primer frame, un objeto de actividad duradero por turno con un susurro de razonamiento en vivo y un rastro de herramientas resistente a recargas, títulos de sesión escritos por el LLM, paridad completa en cinco idiomas. **La renta variable de Corea (KRX: KOSPI/KOSDAQ)** se convierte en el noveno motor de backtest — banda de ±30% en tiempo de ejecución, solo largo, impuesto de transacción del 0.20% de 2026, loader opcional `pykrx` ([#693](https://github.com/HKUDS/Vibe-Trading/pull/693), gracias @JungHoonGhae) — más un **puente a OpenBB Workspace** ([#817](https://github.com/HKUDS/Vibe-Trading/pull/817), gracias @shugaoye) y una herramienta de solo lectura de **snapshot de Taiwán** ([#848](https://github.com/HKUDS/Vibe-Trading/pull/848), gracias @TSENGCHIENFENG). Corrección: las bandas de precio diarias se evalúan **en el momento de la ejecución**, no a partir del cierre de la barra de decisión; una sesión ejecuta un intento a la vez (HTTP 409) y una detención por parte del usuario es su propio estado terminal ([#676](https://github.com/HKUDS/Vibe-Trading/pull/676), gracias @tyj147454413-cmd). Además, trazas duraderas ([#662](https://github.com/HKUDS/Vibe-Trading/pull/662)), resultados de herramientas con secretos depurados ([#675](https://github.com/HKUDS/Vibe-Trading/pull/675)), argumentos de herramientas con fallo cerrado ([#913](https://github.com/HKUDS/Vibe-Trading/pull/913)/[#911](https://github.com/HKUDS/Vibe-Trading/pull/911), gracias @santhreal), `reasoning_effort` directo de OpenAI ([#755](https://github.com/HKUDS/Vibe-Trading/pull/755), gracias @1anter), y guardas numéricas a través del risk x-ray / edge density / motor de opciones ([#909](https://github.com/HKUDS/Vibe-Trading/pull/909)/[#908](https://github.com/HKUDS/Vibe-Trading/pull/908)/[#907](https://github.com/HKUDS/Vibe-Trading/pull/907)).
- **2026-07-29** 🔧 **Retornos seguros ante gaps + modelado de riesgo de liquidación + un risk x-ray en cada ejecución**: `bar_returns` ya no borra el movimiento real a través de una suspensión de cotización más larga que la ventana de forward-fill — el movimiento de reanudación se registraba silenciosamente como 0, subestimando la volatilidad e inflando el Sharpe — y un precio previo `inf` ya no puede leerse como un limpio −100% ([#895](https://github.com/HKUDS/Vibe-Trading/pull/895), gracias @darkknight4563). La anualización ahora cubre **las 24 fuentes de datos** en todos los intervalos, con un test de cobertura que hace fallar el CI cuando un loader llega sin entradas ([#891](https://github.com/HKUDS/Vibe-Trading/pull/891), cierra [#884](https://github.com/HKUDS/Vibe-Trading/issues/884), gracias @Robin1987China). La investigación de perpetuos USD-M gana una evaluación determinista de **liquidación de margen aislado y cruzado** ([#889](https://github.com/HKUDS/Vibe-Trading/pull/889), gracias @honginp), y cada backtest de portafolio ahora emite **artefactos de risk x-ray** (`risk_xray.json`/`.md`) con métricas principales de concentración/volatilidad/drawdown ([#900](https://github.com/HKUDS/Vibe-Trading/pull/900), gracias @he-yufeng). La CLI `connector` ahora carga `~/.vibe-trading/.env`, así que las credenciales de broker con origen en variables de entorno vuelven a resolverse ([#902](https://github.com/HKUDS/Vibe-Trading/pull/902), cierra [#901](https://github.com/HKUDS/Vibe-Trading/issues/901), gracias @MuggleJinx). Además, divisiones de mensajes de canal que preservan la sangría y parseo de frontmatter de skills al final del archivo (EOF) ([#867](https://github.com/HKUDS/Vibe-Trading/pull/867)/[#861](https://github.com/HKUDS/Vibe-Trading/pull/861), gracias @santhreal).

- **2026-07-28** 🔧 **Desbloqueo de los modelos Claude de próxima generación + retornos seguros ante el signo**: los modelos Claude que dejan obsoleto el campo `temperature` (opus-4-7, opus-5, sonnet-5) ya funcionan — el adaptador descarta el campo cuando la API lo rechaza, reintenta una vez, y recuerda el modelo, así que no se necesita un parche por cada lanzamiento ([#890](https://github.com/HKUDS/Vibe-Trading/pull/890), cierra [#856](https://github.com/HKUDS/Vibe-Trading/issues/856), gracias @yagnikpipaliya). El `vibe-trading run` no interactivo ahora inyecta un id de sesión de host: las herramientas de objetivo de investigación antes fallaban en cada llamada mientras la ejecución seguía reportando éxito ([#885](https://github.com/HKUDS/Vibe-Trading/issues/885)). Los retornos de comprar y mantener (buy-and-hold) son seguros ante el signo — un cierre previo cercano a cero ya no hace explotar el benchmark compuesto, y un cierre exactamente cero ya no produce `inf`/`nan` ([#872](https://github.com/HKUDS/Vibe-Trading/issues/872), gracias @darkknight4563). El frontend pasa a **Node 22 + React Router 8**, resolviendo un aviso de severidad alta.
- **2026-07-27** 🔧 **Integridad de la correlación + reparación de exportación a vn.py 4.0 + un lote de codificación**: la matriz de correlación móvil ya no rellena hacia adelante (forward-fill) los cierres faltantes — una sesión suspendida se puntuaba como un retorno fabricado del 0% frente al movimiento real del par, distorsionando la matriz ([#873](https://github.com/HKUDS/Vibe-Trading/pull/873), gracias @ddy4633). La skill de **exportación a vn.py** se repara para el layout de vn.py 4.x, donde `vnpy.app.cta_strategy` ya no existe upstream — las plantillas ahora importan desde `vnpy_ctastrategy` ([#869](https://github.com/HKUDS/Vibe-Trading/pull/869), gracias @y85998607). Además, un lote de seis correcciones: decodificación de BOM UTF-16 en el lector de documentos y en los CSV de diario de operaciones, símbolos de divisa eliminados antes de la coerción numérica, símbolos con estilo `BTCUSDT` inferidos como cripto, intervalos en minúscula `1h`/`1d` anualizados correctamente, y caracteres CJK preservados en los slugs de directorio de skills ([#862](https://github.com/HKUDS/Vibe-Trading/pull/862), [#863](https://github.com/HKUDS/Vibe-Trading/pull/863), [#864](https://github.com/HKUDS/Vibe-Trading/pull/864), [#865](https://github.com/HKUDS/Vibe-Trading/pull/865), [#866](https://github.com/HKUDS/Vibe-Trading/pull/866), [#868](https://github.com/HKUDS/Vibe-Trading/pull/868), gracias @santhreal).
- **2026-07-26** 🔒 **Lock de dependencias + transparencia del universo**: la instalación anclada por hash de Docker vuelve a funcionar, con una nueva comprobación de lock en el CI ([#858](https://github.com/HKUDS/Vibe-Trading/pull/858), cierra [#847](https://github.com/HKUDS/Vibe-Trading/issues/847)). `alpha bench` ahora revela las fuentes, los recuentos, los fallbacks degradados y el sesgo de supervivencia del CSI300/SP500 ([#859](https://github.com/HKUDS/Vibe-Trading/pull/859), cierra [#845](https://github.com/HKUDS/Vibe-Trading/issues/845)). También se actualizaron las Actions y cinco dependencias del frontend ([#850](https://github.com/HKUDS/Vibe-Trading/pull/850)–[#852](https://github.com/HKUDS/Vibe-Trading/pull/852)).
- **2026-07-25** 🔧 **Realismo de perpetuos + corrección de un crash de MCP + un lote de correcciones**: los perpetuos USD-M ganan **contratos de estado de margen** ([#798](https://github.com/HKUDS/Vibe-Trading/pull/798), gracias @honginp) y el motor ahora consume **tasas de funding históricas** en lugar de obtenerlas e ignorarlas ([#819](https://github.com/HKUDS/Vibe-Trading/pull/819), gracias @g0rdonL). Los resultados de dataclass de MCP ya no fallan por un falso `Circular reference detected` ([#849](https://github.com/HKUDS/Vibe-Trading/pull/849), gracias @Echoandelementwebsites), y la CLI/HTML de `alpha bench` propagan la divulgación de supervivencia `_meta` ([#841](https://github.com/HKUDS/Vibe-Trading/pull/841), cierra [#797](https://github.com/HKUDS/Vibe-Trading/issues/797), gracias @AmirF194). Además, 12 correcciones a través de diarios, conectores y canales ([#799](https://github.com/HKUDS/Vibe-Trading/pull/799)–[#810](https://github.com/HKUDS/Vibe-Trading/pull/810), gracias @santhreal), y una etiqueta de cuenta real en los balances de la CLI ([#843](https://github.com/HKUDS/Vibe-Trading/pull/843), cierra [#846](https://github.com/HKUDS/Vibe-Trading/issues/846), gracias @Robin1987China).
- **2026-07-24** 🔀 **Memory Tier 2, restricciones componibles del optimizador + una pasada de manejo de intervalos**: la memoria persistente gana **organización estructural Tier 2** ([#815](https://github.com/HKUDS/Vibe-Trading/pull/815), gracias @shadowinlife), y los optimizadores de backtest aceptan **restricciones de peso componibles** ([#818](https://github.com/HKUDS/Vibe-Trading/pull/818), gracias @he-yufeng). Corrección: el validador de barras diarias puede optar por permitir **precios no positivos** — abriendo en barras negativas mientras sigue rechazando el cero ([#816](https://github.com/HKUDS/Vibe-Trading/pull/816), cierra [#571](https://github.com/HKUDS/Vibe-Trading/issues/571), gracias @darkknight4563). Además, una pasada de **normalización de intervalos** de 19 PR en los loaders: los alias en minúscula `1h/4h/1d/1w` se aceptan en todas partes, los intervalos no soportados ahora fallan rápido en lugar de devolver silenciosamente barras diarias, `4H` de Yahoo se mapea a `1h`, y MT5 acepta `1W/1M` ([#812](https://github.com/HKUDS/Vibe-Trading/pull/812)–[#838](https://github.com/HKUDS/Vibe-Trading/pull/838), gracias @santhreal), una corrección de diario de operaciones para fechas de número de serie de Excel de Eastmoney ([#811](https://github.com/HKUDS/Vibe-Trading/pull/811), gracias @santhreal), y una corrección de ancla de navegación del README ([#840](https://github.com/HKUDS/Vibe-Trading/pull/840), gracias @dvirarad).
- **2026-07-23** 🔧 **Pasada de fiabilidad + alpha-bench estricto expuesto + ciclo de vida de memoria opcional**: un lote de 22 PR de contribuidores. Una amplia **pasada de fiabilidad** corrige el manejo de timeframes de punta a punta — yfinance `1M`→mensual (no minuto), CCXT `1W`/`1M`, akshare/india-broker rechazando intervalos no soportados en lugar de devolver silenciosamente barras diarias, y los conectores Tiger/Alpaca/OKX/Shoonya/Longbridge manteniendo `1H`/`4H` como barras horarias — además de normalización de fechas Excel en el diario de operaciones (float `YYYYMMDD` de eastmoney, fechas de número de serie de Futu/Tonghuashun), `report_audit` con JSON finito, validación de `holding_days` en blanco, y bordes de tablas markdown en Feishu/CLI ([#778](https://github.com/HKUDS/Vibe-Trading/pull/778)–[#794](https://github.com/HKUDS/Vibe-Trading/pull/794), gracias @santhreal). `trading_history` de **MT5** ahora convierte los escalares de numpy de modo que la serialización JSON ya no muere con `int64` ([#776](https://github.com/HKUDS/Vibe-Trading/pull/776), cierra [#774](https://github.com/HKUDS/Vibe-Trading/issues/774), gracias @shadowinlife), y los **fundamentales PIT** deduplican filas reformuladas y evitan que el snapshot retroceda a un período fiscal más antiguo ante una reformulación tardía ([#772](https://github.com/HKUDS/Vibe-Trading/pull/772), cierra [#771](https://github.com/HKUDS/Vibe-Trading/issues/771), gracias @klmtseng). Novedad: **`alpha bench --strict`** finalmente conecta la puerta estricta de control aleatorio de mismo universo + OOS que había quedado inalcanzable desde 0.1.9 ([#796](https://github.com/HKUDS/Vibe-Trading/pull/796), cierra [#773](https://github.com/HKUDS/Vibe-Trading/issues/773), gracias @he-yufeng), un **ciclo de vida de memoria** opcional (puntuación de calidad, decaimiento de Ebbinghaus, GC solo de archivado — todo desactivado por defecto) ([#733](https://github.com/HKUDS/Vibe-Trading/pull/733), cierra [#732](https://github.com/HKUDS/Vibe-Trading/issues/732), gracias @shadowinlife), y artefactos de **notas de rebalanceo** de backtest + métricas de turnover ([#795](https://github.com/HKUDS/Vibe-Trading/pull/795), gracias @he-yufeng).
- **2026-07-22** 🚀 **Se lanza v0.1.12** ([Notas de la versión](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.12), `pip install -U vibe-trading-ai`): la **línea de tiempo de regímenes de correlación** añade un endpoint `GET /correlation/regime` + una franja opcional en la pestaña Correlation — la edge density pasa por una máquina de estados de histéresis causal que marca episodios de mercado FUSED, un contexto de riesgo descriptivo y no una señal ([#756](https://github.com/HKUDS/Vibe-Trading/pull/756), cierra [#719](https://github.com/HKUDS/Vibe-Trading/issues/719), gracias @ebujinovch). La resolución del endpoint del proveedor ahora recae en la URL base canónica de cada proveedor y maneja con elegancia los endpoints que no son SSE, corrigiendo el proveedor nativo **zai** en glm-5.1 ([#758](https://github.com/HKUDS/Vibe-Trading/issues/758)). Además, una **pasada de fiabilidad** de JSON estricto / números finitos a través de métricas, factores, patrones, sesión y diario ([#761](https://github.com/HKUDS/Vibe-Trading/pull/761)–[#770](https://github.com/HKUDS/Vibe-Trading/pull/770), gracias @santhreal) y un desacople del bracket de mantenimiento de Binance que mantiene los backtests `-PERP` sin necesidad de credenciales ([#757](https://github.com/HKUDS/Vibe-Trading/pull/757), gracias @honginp). Consolida ~90 correcciones desde 0.1.11.
- **2026-07-21** 🔧 **Completitud de los loaders de datos + una pasada de correcciones de fiabilidad**: los resultados parciales de datos de mercado ahora completan los símbolos faltantes a través de la cadena de fallback y fallan de forma cerrada en lugar de reducir silenciosamente el universo del backtest ([#689](https://github.com/HKUDS/Vibe-Trading/pull/689), cierra [#681](https://github.com/HKUDS/Vibe-Trading/issues/681), gracias @xkam7ar), y las barras de OKX usan el endpoint `history-candles` con reintento por límite de tasa para backfills profundos ([#644](https://github.com/HKUDS/Vibe-Trading/pull/644), gracias @tyj147454413-cmd). Además, una pasada de correcciones: la guarda de red de MCP acepta hosts IPv6 / con variantes de mayúsculas ([#750](https://github.com/HKUDS/Vibe-Trading/pull/750), gracias @Robin1987China), los parsers de diario de operaciones omiten filas de símbolo en blanco/NaN ([#749](https://github.com/HKUDS/Vibe-Trading/pull/749), gracias @Robin1987China), la Shadow Account omite la puerta de hora de entrada minada en barras diarias ([#748](https://github.com/HKUDS/Vibe-Trading/pull/748), gracias @Robin1987China), y los endpoints regionales de la API de MiniMax son seleccionables ([#731](https://github.com/HKUDS/Vibe-Trading/pull/731), gracias @octo-patch).
- **2026-07-20** 🔀 **Proveedores, MetaTrader 5, y una pasada de fiabilidad**: la **Anthropic Messages API** nativa (extra opcional `[anthropic]`, [#695](https://github.com/HKUDS/Vibe-Trading/pull/695), gracias @jelech), **SiliconFlow** ([#565](https://github.com/HKUDS/Vibe-Trading/pull/565), gracias @UNHNQ), y **iFlytek Spark** ([#537](https://github.com/HKUDS/Vibe-Trading/pull/537), gracias @FenjuFu) se unen al listado de proveedores, y llega un conector de broker **MetaTrader 5 (Exness)** + una fuente de datos forex/metales `mt5` (conectores de broker → **12**, [#481](https://github.com/HKUDS/Vibe-Trading/pull/481), gracias @StaniellG). Además, un motor OCR **`llm-vision`** agnóstico de proveedor ([#548](https://github.com/HKUDS/Vibe-Trading/pull/548), gracias @shadowinlife), una **vectorización de alineación de señales 80×** ([#698](https://github.com/HKUDS/Vibe-Trading/pull/698), gracias @shadowinlife), datos históricos de **funding/bracket de Binance USD-M** ([#716](https://github.com/HKUDS/Vibe-Trading/pull/716), gracias @honginp), una caché de descubrimiento MCP para swarm ([#704](https://github.com/HKUDS/Vibe-Trading/pull/704)), y una consolidación de fiabilidad que cierra **13** issues de SSE/sesión/CLI/swarm/scheduler ([#584](https://github.com/HKUDS/Vibe-Trading/pull/584), gracias @xkam7ar). Corrección: el **cierre parcial** de opciones ahora respeta la cantidad solicitada en lugar de aplanar el lote completo ([#577](https://github.com/HKUDS/Vibe-Trading/issues/577)), resolución centralizada de credenciales de proveedor ([#563](https://github.com/HKUDS/Vibe-Trading/pull/563)), manejo de cancelación en cola ([#641](https://github.com/HKUDS/Vibe-Trading/pull/641)), una condición de carrera de streaming-DOM en el frontend ([#717](https://github.com/HKUDS/Vibe-Trading/pull/717), gracias @Marnie0415), y los renderers de la CLI del connector ([#726](https://github.com/HKUDS/Vibe-Trading/pull/726), gracias @nareshkps).

- **2026-07-19** 🔧 **Artículos reales de noticias bursátiles de EE. UU./HK + corrección de análisis factorial de MCP + una pasada de robustez**: la herramienta de noticias bursátiles ahora devuelve **artículos reales de Yahoo Finance** (título/url/fuente/fecha de publicación/fragmento) para tickers de EE. UU. y HK en lugar de coincidencias de instrumentos relacionados, todavía enrutados a través del cliente congelado con limitación de IP ([#730](https://github.com/HKUDS/Vibe-Trading/pull/730), gracias @yxhuang). La herramienta MCP `factor_analysis` se realinea con el contrato CSV real de la herramienta registrada, así que las llamadas ya no mueren por `KeyError` antes de ejecutarse ([#715](https://github.com/HKUDS/Vibe-Trading/pull/715), cierra [#635](https://github.com/HKUDS/Vibe-Trading/issues/635), gracias @Robin1987China). Además, una pasada de robustez: toda la **serie Kimi K** (k2/k3/…/`for-coding`) ahora fuerza automáticamente `temperature=1` como exige la API ([#701](https://github.com/HKUDS/Vibe-Trading/pull/701), gracias @sambazhu), y `split_message`, los rangos de páginas de PDF, y los filtros de fecha del diario de operaciones fallan rápido ante entradas degeneradas o invertidas en lugar de colgarse o devolver silenciosamente nada ([#727](https://github.com/HKUDS/Vibe-Trading/pull/727)–[#729](https://github.com/HKUDS/Vibe-Trading/pull/729), gracias @santhreal).

- **2026-07-18** 🔧 **Fallback de cripto en Binance + correcciones de ejecución paralela y de corrección**: un loader de **Binance** se une a la cadena de fallback de datos históricos de cripto ([#643](https://github.com/HKUDS/Vibe-Trading/pull/643), gracias @tyj147454413-cmd), y el connector de IBKR pasa a un pool de conexiones thread-local con cotizaciones snapshot, corrigiendo bloqueos bajo ejecuciones paralelas de agentes ([#636](https://github.com/HKUDS/Vibe-Trading/pull/636), gracias @MikeCer). Además, una pasada de corrección: el análisis factorial rechaza `n_groups` no positivos, los rangos de período invertidos y las ventanas de detección no positivas fallan rápido, se maneja un `DatetimeIndex` sin nombre en la matriz de correlación, se aceptan los alias de columna nav/value de `equity.csv`, y los códigos de acciones A vacíos ya no se coaccionan a `000000.SZ` ([#709](https://github.com/HKUDS/Vibe-Trading/pull/709)–[#714](https://github.com/HKUDS/Vibe-Trading/pull/714), gracias @santhreal). Un factor de estabilidad de reconexión de correlación se une al zoo académico ([#705](https://github.com/HKUDS/Vibe-Trading/pull/705), gracias @ebujinovch), el zoo fundamental queda en lista blanca para el análisis factorial ([#707](https://github.com/HKUDS/Vibe-Trading/pull/707), gracias @sambazhu), el estado de ejecución persistido ahora es durable mediante fsync ([#645](https://github.com/HKUDS/Vibe-Trading/pull/645), gracias @tyj147454413-cmd), y el extra `dev` instala el toolchain documentado de Black/Ruff ([#634](https://github.com/HKUDS/Vibe-Trading/pull/634), gracias @xkam7ar).

- **2026-07-17** 🧩 **Skill de régimen de correlación + una amplia pasada de corrección de backtest / datos / seguridad en vivo**: una nueva skill de detección de **régimen de correlación** (skills incluidas → 88, [#557](https://github.com/HKUDS/Vibe-Trading/pull/557), gracias @ebujinovch), una tarjeta de conexión de runtime de Longbridge ([#569](https://github.com/HKUDS/Vibe-Trading/pull/569), gracias @fanfpy), y presets de swarm definidos por el usuario cargados desde `~/.vibe-trading` ([#570](https://github.com/HKUDS/Vibe-Trading/pull/570), gracias @darkknight4563). Además, endurecimiento a través de toda la pila: correcciones de corrupción silenciosa de datos en los loaders de Futu / Tencent / CCXT / mootdx, guardas de look-ahead-bias y de OOS estricto en el factor bench y en la Shadow Account, seguridad en el trading en vivo (límites de exposición firmados, límites diarios de órdenes atómicos, confirmaciones de mandato con consentimiento previo, estado en vivo con fallo cerrado), y mejoras de diario / presupuesto de QVeris / swarm / puerta de CI ([#552](https://github.com/HKUDS/Vibe-Trading/pull/552), gracias @xor-xe; buena parte del trabajo de corrección de @xkam7ar).

- **2026-07-16** 🔧 **Lock de dependencias reparado + corrección al guardar configuración en Windows**: el lock de runtime verificado por hash se regenera de modo que `pip install --require-hashes` de Docker vuelve a resolverse limpiamente, corrigiendo los pins incompatibles de `caio`/`pydantic-core`/`websockets` ([#564](https://github.com/HKUDS/Vibe-Trading/pull/564), cierra [#558](https://github.com/HKUDS/Vibe-Trading/issues/558), gracias @tianrking). Guardar la configuración del LLM del Agent desde la Web UI ya no devuelve HTTP 500 en Windows — el endurecimiento `os.fchmod`, exclusivo de POSIX, ahora está protegido por plataforma, con un test de regresión para plataformas sin `fchmod` ([#561](https://github.com/HKUDS/Vibe-Trading/pull/561), gracias @CRui5in).

- **2026-07-15** 🧮 **Corrección de backtest + núcleo de Portfolio Studio**: una pasada de convergencia de 10 PR hizo que los rebalanceos fueran causales e independientes del orden, cobró los costes de cierre terminal, reportó el turnover derivado de las ejecuciones, aplicó los límites de exposición, y mantuvo la salida de validación finita y estricta ([#530](https://github.com/HKUDS/Vibe-Trading/pull/530)/[#531](https://github.com/HKUDS/Vibe-Trading/pull/531)/[#532](https://github.com/HKUDS/Vibe-Trading/pull/532)/[#540](https://github.com/HKUDS/Vibe-Trading/pull/540)). Los gráficos ahora reutilizan la fuente de datos real de la ejecución, las consultas de mercado repetibles ya no se descartan, y las cargas de `.env` refrescan la configuración en caché ([#535](https://github.com/HKUDS/Vibe-Trading/pull/535)/[#544](https://github.com/HKUDS/Vibe-Trading/pull/544)/[#554](https://github.com/HKUDS/Vibe-Trading/pull/554)). Se cierran Portfolio Studio [#456](https://github.com/HKUDS/Vibe-Trading/issues/456) y el bug de configuración [#541](https://github.com/HKUDS/Vibe-Trading/issues/541); también se cierran las correcciones de proveedor [#528](https://github.com/HKUDS/Vibe-Trading/issues/528)/[#529](https://github.com/HKUDS/Vibe-Trading/issues/529). Gracias @YZY0108, @santhreal, @Robin1987China, @xkam7ar, @Marnie0415, y @marichu99.

- **2026-07-14** 🌉 **Datos de mercado de Longbridge + transporte MCP moderno + fiabilidad de proveedores**: Longbridge se une a la capa de fallback de datos históricos con credenciales controladas por clave, división por ventana de fechas, comprobaciones estrictas de completitud, y una dependencia opcional del SDK; cuatro herramientas de flujo del mercado chino ganan fallbacks verificados de Tushare, y un equity final negativo ya no hace fallar las métricas de backtest. El servidor MCP ahora soporta Streamable HTTP, `write_file` recupera de forma segura argumentos de ruta con alias o faltantes, las actualizaciones de hipótesis rechazan campos no soportados, y las solicitudes de Correlation están autenticadas. NVIDIA NIM ahora es un proveedor de primera clase tanto en Web Settings como en ambos flujos de onboarding de la CLI, con un User-Agent de compatibilidad versionado para abordar el 403 reportado; Web Settings ahora escribe en el `~/.vibe-trading/.env` canónico, migra la configuración heredada, y reporta con claridad los fallos de permisos, corrigiendo el 500 de DeepSeek al guardar ([#534](https://github.com/HKUDS/Vibe-Trading/pull/534), cierra [#516](https://github.com/HKUDS/Vibe-Trading/issues/516)/[#524](https://github.com/HKUDS/Vibe-Trading/issues/524); [#528](https://github.com/HKUDS/Vibe-Trading/issues/528)/[#529](https://github.com/HKUDS/Vibe-Trading/issues/529)). Gracias @fanfpy, @asahikiko, @santhreal, @sTunnaSu, @abhishekjaisinghani, @huangcheng, @ShiroKSH, @Meru143, @DIEGOD79, y @not-knope por el código, los reportes y el diagnóstico.

- **2026-07-13** 🔒 **Endurecimiento de seguridad: se cierran los 10 hallazgos de la auditoría externa + lote de contribuidores**: todos los hallazgos de la auditoría de seguridad externa del 2026-07-10 (issue [#476](https://github.com/HKUDS/Vibe-Trading/issues/476), discusión [#468](https://github.com/HKUDS/Vibe-Trading/discussions/468)) ya están resueltos en `main` — reconstrucción multi-etapa de Docker con imágenes ancladas por digest, un sandbox de backtest endurecido con AST que bloquea network/subprocess/eval/os.environ/unsafe-open (incluso dentro de cuerpos de función anidados), tickets de autenticación SSE de un solo uso y de corta duración, Compose endurecido (rootfs de solo lectura, capabilities eliminadas, límites de recursos), autenticación + limitación de tasa en `/correlation`, cabeceras de seguridad, dependencias ancladas por hash, y más. También se fusionó: **modo TAP** opcional para el aislamiento de claves de Alpaca ([#377](https://github.com/HKUDS/Vibe-Trading/pull/377), gracias @0xZKnw), el turnover de portafolio realizado expuesto en las métricas de backtest ([#478](https://github.com/HKUDS/Vibe-Trading/pull/478), gracias @Robin1987China), un factor académico de **betting-against-beta de Frazzini-Pedersen** (Alpha Zoo → 461, [#480](https://github.com/HKUDS/Vibe-Trading/pull/480), gracias @YogeshModi24), una corrección de look-ahead-bias en los 5 optimizadores de portafolio ([#487](https://github.com/HKUDS/Vibe-Trading/pull/487), gracias @YZY0108), y dos correcciones de preflight/configuración de proveedor ([#479](https://github.com/HKUDS/Vibe-Trading/pull/479)/[#484](https://github.com/HKUDS/Vibe-Trading/pull/484), cierra [#477](https://github.com/HKUDS/Vibe-Trading/issues/477)/[#482](https://github.com/HKUDS/Vibe-Trading/issues/482), gracias @ananaymital/@Bortlesboat).

- **2026-07-12** 🧪 **Strategy Development Manager + lote de correcciones de contribuidores**: la nueva skill `strategy-dev-manager` (#87) convierte papers académicos e investigación de brokers en factores/estrategias registrados con un almacén persistente de artefactos y monitoreo automatizado de decaimiento de IC/Sharpe — `sdm_register` / `sdm_status` / `sdm_decay_scan` gestionan un ciclo de vida activo → en monitoreo → decaído → deshabilitado sobre `~/.vibe-trading/` ([#457](https://github.com/HKUDS/Vibe-Trading/pull/457), cierra [#455](https://github.com/HKUDS/Vibe-Trading/issues/455), gracias @shadowinlife). También se fusionó: la pestaña Correlation acepta tickers simples (`AAPL,SPY`) y recorre toda la cadena de fallback de loaders ([#472](https://github.com/HKUDS/Vibe-Trading/pull/472), cierra [#471](https://github.com/HKUDS/Vibe-Trading/issues/471), gracias @yxhuang), el loader `local` respeta los intervalos solicitados mediante remuestreo de OHLCV ([#467](https://github.com/HKUDS/Vibe-Trading/pull/467), gracias @Shizoqua), el historial de perpetuos USD-M de Binance llega con enrutamiento explícito de `BTC-USDT-PERP` + separación de precio de ejecución/marca como la primera porción de [#462](https://github.com/HKUDS/Vibe-Trading/issues/462) ([#470](https://github.com/HKUDS/Vibe-Trading/pull/470), gracias @honginp), los imports de transporte de FastMCP ahora funcionan en ambos layouts de módulo ([#469](https://github.com/HKUDS/Vibe-Trading/pull/469), gracias @roberttidball), y Requesty está disponible como proveedor de gateway LLM compatible con OpenAI ([#474](https://github.com/HKUDS/Vibe-Trading/pull/474), gracias @Thibaultjaigu).

- **2026-07-11** 🚀 **Se lanza v0.1.11** (`pip install -U vibe-trading-ai`): consolida tres semanas desde 0.1.10 — backtesting de primera clase para acciones indias (NSE/BSE), la capa de factores fundamentales segura ante PIT (Alpha Zoo → 460), el runtime de canales IM con 16 adaptadores, investigación programada de punta a punta, datos premium opcionales de QVeris, y el lote de contribuidores de hoy: un optimizador consciente del turnover ([#466](https://github.com/HKUDS/Vibe-Trading/pull/466), gracias @Robin1987China), una herramienta de visión `analyze_image` + emparejamiento de DM de NapCat + la corrección de lectura de medios IM ([#464](https://github.com/HKUDS/Vibe-Trading/pull/464)/[#463](https://github.com/HKUDS/Vibe-Trading/pull/463)/[#465](https://github.com/HKUDS/Vibe-Trading/issues/465), gracias @fei-moss), serialización Decimal de Longbridge ([#459](https://github.com/HKUDS/Vibe-Trading/pull/459), gracias @fanfpy), y guardas de recuento del manifiesto empaquetado ([#461](https://github.com/HKUDS/Vibe-Trading/pull/461), gracias @asahikiko). Detalles completos: [CHANGELOG](CHANGELOG.md) · [notas de la versión](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.11).

- **2026-07-10** 🇮🇳 **Soporte para acciones indias (NSE/BSE) + configuración de entorno centralizada**: llega un `IndiaEquityEngine` dedicado — liquidación T+1, bandas de circuito, y una pila de costes STT/stamp/exchange/SEBI/GST gobernada por configuración — con enrutamiento de símbolos `.NS`/`.BO`, un puente de datos opcional de solo lectura para Shoonya/Dhan, y 255 factores alpha101/qlib158 incorporados al nuevo universo `equity_in` ([#305](https://github.com/HKUDS/Vibe-Trading/pull/305), gracias @muku314115). Las variables de entorno ahora fluyen a través de un único esquema Pydantic `EnvConfig` con una puerta de CI basada en AST contra la futura proliferación de `os.getenv` ([#440](https://github.com/HKUDS/Vibe-Trading/pull/440), cierra [#438](https://github.com/HKUDS/Vibe-Trading/issues/438), gracias @shadowinlife). Además: un diálogo de segunda confirmación antes de confirmar un mandato de trading real más toasts de error unificados ([#453](https://github.com/HKUDS/Vibe-Trading/pull/453), gracias @wison1717-maker), tests de rutas de investigación programada ([#452](https://github.com/HKUDS/Vibe-Trading/pull/452), gracias @Robin1987China), y los modelos de razonamiento de GLM ya no pierden su stream de razonamiento en el proveedor zhipu ([#458](https://github.com/HKUDS/Vibe-Trading/issues/458)).

- **2026-07-09** 🧯 **Desbloqueo del arranque de Docker + lote de contribuidores de proveedores/CLI**: el arranque de Docker/servidor ya no falla cuando la iteración de rutas de FastAPI encuentra una entrada tipo router incluido sin `path` ([#450](https://github.com/HKUDS/Vibe-Trading/issues/450), gracias @Penn-Live). También incorporamos las correcciones rápidas en cola de contribuidores: las firmas de `fetch()` de los loaders ahora coinciden con el protocolo en OKX / Tushare / yfinance ([#437](https://github.com/HKUDS/Vibe-Trading/pull/437), gracias @shadowinlife), el prompt de reanudación de la CLI preserva el primer mensaje del usuario ([#448](https://github.com/HKUDS/Vibe-Trading/pull/448), cierra [#447](https://github.com/HKUDS/Vibe-Trading/issues/447), gracias @morluto), el OAuth de Codex usa por defecto `openai-codex/gpt-5.4` ([#446](https://github.com/HKUDS/Vibe-Trading/pull/446), gracias @morluto), Kimi for Coding está disponible como un proveedor distinto ([#435](https://github.com/HKUDS/Vibe-Trading/pull/435), gracias @yxhuang), los mapeos de proveedor de opencode están conectados ([#444](https://github.com/HKUDS/Vibe-Trading/pull/444), gracias @imsankz), y los bloques de código de referencia de Tushare ahora dicen `python` en lugar de `pyhton` ([#449](https://github.com/HKUDS/Vibe-Trading/pull/449), gracias @flash1234pku). La validación incluyó tests focalizados de servidor/CLI/proveedor/loader además de un build de Docker y un smoke test de `/health`.

- **2026-07-08** 💎 **Capa de factores fundamentales (Fase 1) + datos premium opcionales de QVeris + día de mantenimiento**: los fundamentales de la SEC seguros ante PIT ahora fluyen a los paneles de factores diarios — columnas de panel `fund:*`, anclaje por fecha de presentación con protección ante reformulaciones y marcos YTD, y 4 nuevos factores de calidad/valor (el registro ya tiene 460 alphas). El enrutamiento de datos gana una vía premium opcional: las 18 fuentes gratuitas siguen siendo la opción por defecto, mientras que QVeris desbloquea más de 63 proveedores vía Settings → QVeris o `vibe-trading data mode paid` (ver la sección de QVeris más abajo). Además: se completa la modularización de `api_server` (1,103 → 371 líneas, [#424](https://github.com/HKUDS/Vibe-Trading/pull/424) cerrando [#331](https://github.com/HKUDS/Vibe-Trading/issues/331), gracias @shadowinlife), el `validation.json` del backtest ya no requiere un directorio de artefactos preexistente ([#429](https://github.com/HKUDS/Vibe-Trading/pull/429), gracias @isaveall), errores de `--swarm-run` más claros ([#428](https://github.com/HKUDS/Vibe-Trading/issues/428), gracias @isaveall), y revertimos la pila de gobernanza que rompía los chats de sesión ([#433](https://github.com/HKUDS/Vibe-Trading/issues/433), gracias @yxhuang por el diagnóstico preciso).

- **2026-07-07** ✅ **Lote de PR de contribuidores**: se fusionó el trabajo en cola de contribuidores para la configuración de timeout de canales IM ([#413](https://github.com/HKUDS/Vibe-Trading/pull/413), gracias @SyntaxSawdust), las vistas previas sociales de Alpha Library y el tutorial para principiantes ([#396](https://github.com/HKUDS/Vibe-Trading/pull/396), [#393](https://github.com/HKUDS/Vibe-Trading/pull/393), gracias @kadaliao), skills / herramientas / presets de comité de value investing ([#407](https://github.com/HKUDS/Vibe-Trading/pull/407), gracias @sambazhu), el manejo de campos de orden de tamaño cero en `trading_place_order` ([#417](https://github.com/HKUDS/Vibe-Trading/pull/417), gracias @irfanallana-oss), y timestamps UTC con reconocimiento de zona horaria en las rutas de sesión/API ([#397](https://github.com/HKUDS/Vibe-Trading/pull/397), gracias @mustafakamal88).

- **2026-07-06** 🧭 **Endurecimiento del preflight, particiones de API, y fallback de búsqueda para CN**: el preflight de proveedor ya no sigue redirecciones ([#404](https://github.com/HKUDS/Vibe-Trading/pull/404), cierra [#402](https://github.com/HKUDS/Vibe-Trading/issues/402), gracias @SyntaxSawdust), las rutas de API restantes se movieron a módulos focalizados ([#387](https://github.com/HKUDS/Vibe-Trading/pull/387), sustituyendo a [#383](https://github.com/HKUDS/Vibe-Trading/pull/383)-[#386](https://github.com/HKUDS/Vibe-Trading/pull/386), gracias @shadowinlife), y los fallbacks de búsqueda web para CN ahora incluyen Alibaba Cloud IQS ([#408](https://github.com/HKUDS/Vibe-Trading/pull/408), gracias @sambazhu). La limpieza de mantenimiento añadió tests de fallback sin red y limpieza de espacios en blanco al final de archivo (EOF) ([fbac74f](https://github.com/HKUDS/Vibe-Trading/commit/fbac74f77bfed58dd7fc23d0f001c29190b4b2b6)); el CI de `main` está en verde ([ejecución 28780619018](https://github.com/HKUDS/Vibe-Trading/actions/runs/28780619018)).

- **2026-07-05** ✅ **Cola de PR de contribuidores cerrada + baseline de Windows en verde**: se fusionaron los cuatro PR no-draft seleccionados para la pasada de mantenimiento de hoy. Las extracciones por lote de mootdx de acciones A ahora dejan propagar `KeyboardInterrupt` / `SystemExit` en lugar de que un `except` desnudo los engulla ([#399](https://github.com/HKUDS/Vibe-Trading/pull/399), cierra [#398](https://github.com/HKUDS/Vibe-Trading/issues/398), gracias @shadowinlife). La partición de rutas de Settings y los pisos de dependencia parcheados ya están fusionados bajo sus PR de contribuidores originales ([#382](https://github.com/HKUDS/Vibe-Trading/pull/382), [#390](https://github.com/HKUDS/Vibe-Trading/pull/390), gracias @shadowinlife y @aeonframework). La compatibilidad de baseline de Windows ahora aísla las cachés de loaders, hace que las aserciones de caché de OAuth sean conscientes de la plataforma, omite un test mock exclusivo de fork en Windows, y evita los proxies para los fixtures de loopback de MCP ([#401](https://github.com/HKUDS/Vibe-Trading/pull/401), gracias @Elfsa-Miranda). Validación: `4701 passed, 47 skipped`.

- **2026-07-04** 🧩 **Particiones de rutas de API, documentación de tutorial, y pisos de dependencia**: las rutas de canales IM y de Settings se movieron fuera de `api_server.py` hacia `src/api/channels_routes.py` y `src/api/settings_routes.py`, continuando la vía acotada de modularización de [#331](https://github.com/HKUDS/Vibe-Trading/issues/331) a partir del trabajo de contribuidores ([#379](https://github.com/HKUDS/Vibe-Trading/pull/379), [#382](https://github.com/HKUDS/Vibe-Trading/pull/382), gracias @shadowinlife). El wiki ganó un tutorial para principiantes en chino para lectores sin formación financiera ([#393](https://github.com/HKUDS/Vibe-Trading/pull/393), gracias @kadaliao), y los pisos de dependencia ahora mantienen a Pillow / LangChain / LangGraph en la vía parcheada instalable ([#390](https://github.com/HKUDS/Vibe-Trading/pull/390), gracias @aeonframework).

- **2026-07-04** 🧹 **Limpieza de timestamps UTC para rutas de sesión y API**: se reforzó la corrección de timestamps de #395 para que los timestamps de sesión, objetivo, canal y API ahora emitan valores UTC con zona horaria explícita en formato ISO.

- **2026-07-03** 🛡️ **Actualización de Robinhood MCP + modularización de API + protección SSRF**: Robinhood Agentic Trading ahora usa los nombres de herramientas MCP actuales en las lecturas genéricas, la plomería del live-runner, las semillas de solo lectura por defecto y las pruebas de la puerta de mandato, mientras que el arranque interactivo respeta el mismo orden de búsqueda de `.env` que el cargador de proveedores (`~/.vibe-trading/.env` → `agent/.env` → `$CWD/.env`) ([#391](https://github.com/HKUDS/Vibe-Trading/pull/391), cierra [#381](https://github.com/HKUDS/Vibe-Trading/issues/381) y [#380](https://github.com/HKUDS/Vibe-Trading/issues/380)). Las rutas del sistema (`/health`, `/correlation`, `/system/shutdown`, `/skills`, `/api`) se movieron a `src/api/system_routes.py` como el siguiente tramo acotado de modularización de la API ([#378](https://github.com/HKUDS/Vibe-Trading/pull/378), gracias @shadowinlife). Las defensas SSRF de medios de canal ahora rechazan objetivos CGNAT/mesh/no globales, y los redireccionamientos de medios de QQ hacia destinos internos se bloquean antes de la obtención ([#389](https://github.com/HKUDS/Vibe-Trading/pull/389), gracias @hobostay).

- **2026-07-02** ⚡ **Aceleración de factores + límites de runtime más seguros**: los operadores de factores rolling en caliente ahora usan las rutas rápidas de `bottleneck`/NumPy, el paralelismo del alpha bench evita cargas de trabajo repetidas sobre paneles grandes, y las matemáticas base de equity cuentan con cobertura de regresión ([#376](https://github.com/HKUDS/Vibe-Trading/pull/376), cierra [#339](https://github.com/HKUDS/Vibe-Trading/issues/339), trabajo original de [#342](https://github.com/HKUDS/Vibe-Trading/pull/342) por @shadowinlife). Las rutas de subida y de informes Shadow se sacaron del monolítico `api_server.py` como el primer tramo acotado de modularización de la API, mientras [#331](https://github.com/HKUDS/Vibe-Trading/issues/331) permanece abierto ([#375](https://github.com/HKUDS/Vibe-Trading/pull/375), basado en [#358](https://github.com/HKUDS/Vibe-Trading/pull/358), gracias @shadowinlife). Los backtests generados ahora heredan solo un entorno de subproceso en lista blanca en lugar de la superficie completa de secretos del proceso padre ([#374](https://github.com/HKUDS/Vibe-Trading/pull/374), cierra [#332](https://github.com/HKUDS/Vibe-Trading/issues/332)), y los canales de mensajería instantánea ganaron el restablecimiento de sesión `/new` y comandos de emparejamiento insensibles a mayúsculas/minúsculas ([#372](https://github.com/HKUDS/Vibe-Trading/pull/372), cierra [#371](https://github.com/HKUDS/Vibe-Trading/issues/371), gracias @shadowinlife).

- **2026-07-01** 🧹 **Refinamiento de seguridad + limpieza del tracker**: se reforzaron los valores por defecto de desarrollo de API/Docker/frontend, se estabilizaron el canal de Settings y los bordes de `zh-CN`, se resolvieron alertas de dependencias/CSP del frontend y se cerraron elementos obsoletos del tracker de WhatsApp y paper-trading ([#338](https://github.com/HKUDS/Vibe-Trading/pull/338), [#351](https://github.com/HKUDS/Vibe-Trading/pull/351), [#349](https://github.com/HKUDS/Vibe-Trading/pull/349), [#365](https://github.com/HKUDS/Vibe-Trading/pull/365), [#367](https://github.com/HKUDS/Vibe-Trading/pull/367), [#350](https://github.com/HKUDS/Vibe-Trading/pull/350), [#335](https://github.com/HKUDS/Vibe-Trading/pull/335), [#283](https://github.com/HKUDS/Vibe-Trading/issues/283)).

- **2026-06-30** 💬 **Runtime de canales de mensajería instantánea para entrega de investigación**: Vibe-Trading ahora puede conectar el mismo runtime de sesión de agente a 16 adaptadores de mensajería integrados — WebSocket, Telegram, Slack, Discord, Matrix, WhatsApp, Signal, QQ/NapCat, WeChat/WeCom, Feishu/Lark, DingTalk, Teams, correo electrónico y Mochat. La CLI (`vibe-trading channels status/start/stop/login/pairing`), REST (`/channels/status`, `/channels/start`, `/channels/stop`, `/channels/pairing/command`) y el panel de Settings de la Web UI exponen estado, sugerencias de recuperación, arranque/detención y emparejamiento de remitentes; los adaptadores respaldados por SDK permanecen detrás de extras como `vibe-trading-ai[telegram]` o `vibe-trading-ai[channels]` ([#341](https://github.com/HKUDS/Vibe-Trading/pull/341)).

- **2026-06-29** 🛡️ **Seguridad de asesoría en vivo + conector de solo lectura de Trading 212 + correcciones de Windows/Gemini**: las protecciones de órdenes en vivo ahora cuentan con una `PreTradeAdvisoryInterface` opcional y agnóstica de broker que registra revisiones de asesoría sin eludir la puerta de mandato, el interruptor de emergencia ni el registro de auditoría ([#328](https://github.com/HKUDS/Vibe-Trading/pull/328), cierra [#317](https://github.com/HKUDS/Vibe-Trading/issues/317), gracias @shadowinlife). Trading 212 se incorpora a la capa de conectores con soporte de solo lectura para cuenta, posiciones, órdenes, historial y metadatos de instrumentos; `place_order` / `cancel_order` siguen rechazando de forma estricta hasta que exista un límite estructural entre paper y live ([#321](https://github.com/HKUDS/Vibe-Trading/pull/321), cierra [#309](https://github.com/HKUDS/Vibe-Trading/issues/309), gracias @mvanhorn). El arranque en Windows evita el fallo de `Timestamp` de pandas 3.0 mediante la restricción `<3.0.0` ([#329](https://github.com/HKUDS/Vibe-Trading/pull/329), cierra [#324](https://github.com/HKUDS/Vibe-Trading/issues/324), gracias @hannibal-lee); se verificó/corrigió en `main` la reproducción del historial en formato dict de `thought_signature` de Gemini ([#318](https://github.com/HKUDS/Vibe-Trading/issues/318)); los estados financieros de `.US` ahora se enrutan a SEC EDGAR en lugar de Eastmoney ([#325](https://github.com/HKUDS/Vibe-Trading/issues/325)); y la página de aterrizaje de la Alpha Library recibió endurecimiento de caché/fecha/selector/noscript/DNS-prefetch, mientras que un CSP más estricto y mejoras de tarjetas sociales siguen en seguimiento ([#323](https://github.com/HKUDS/Vibe-Trading/issues/323)).

- **2026-06-28** 🧰 **Configuración/desarrollo multiplataforma + endurecimiento de runtime y herramientas de archivo**: `vibe-trading setup` y `vibe-trading dev` ahora manejan compilaciones de TypeScript en Windows, lanzan el backend desde el cwd correcto, usan el puerto 5899 de Vite y cierran los procesos hijos de forma limpia ([#292](https://github.com/HKUDS/Vibe-Trading/pull/292), gracias @digger-yu). El sondeo de estado del runtime ahora se degrada en lugar de fallar ([#322](https://github.com/HKUDS/Vibe-Trading/issues/322)); las claves de caché de OAuth de MCP se sanean ([#313](https://github.com/HKUDS/Vibe-Trading/issues/313)); se reforzaron los valores por defecto de OpenAI y la validación de `agent.json` de Robinhood ([#319](https://github.com/HKUDS/Vibe-Trading/pull/319), [#320](https://github.com/HKUDS/Vibe-Trading/pull/320), gracias @mvanhorn); y las herramientas de archivo obtuvieron raíces de lectura/escritura aisladas más pruebas de sandbox más amplias ([#299](https://github.com/HKUDS/Vibe-Trading/pull/299), gracias @skloxo).
- **2026-06-27** 🧯 **Resiliencia del filtro de contenido + limpieza del contrato de funciones de la cuenta espejo**: las ejecuciones dirigidas por eventos y de swarm ahora omiten los rechazos individuales de moderación de contenido de LLM, advierten en las tarjetas de ejecución cuando las tasas de filtrado son altas, y reconocen los motivos de finalización de seguridad de Gemini en lugar de abortar todo un análisis ([#308](https://github.com/HKUDS/Vibe-Trading/pull/308), cierra [#307](https://github.com/HKUDS/Vibe-Trading/issues/307), gracias @shadowinlife). La extracción/generación de código de la cuenta espejo ahora comparte un único contrato `PRICE_FEATURES` y mantiene límites de retorno de cuatro decimales, evitando la desviación entre reglas y código generado y la pérdida de precisión en `prior_5d_return` ([#316](https://github.com/HKUDS/Vibe-Trading/pull/316), gracias @Robin1987China).
- **2026-06-26** 🎯 **Entrada condicional de la cuenta espejo + enrutamiento de tushare para ETF/índice/HK**: las reglas extraídas de la cuenta espejo ahora incorporan límites de RSI / retorno previo, de modo que el SignalEngine generado entra en condiciones reales (RSI dentro de rango, retorno previo dentro de rango) en lugar de replicar ciegamente la cadencia de tenencia ([#314](https://github.com/HKUDS/Vibe-Trading/pull/314), sigue a [#302](https://github.com/HKUDS/Vibe-Trading/pull/302), gracias @Robin1987China). El cargador de tushare también enruta ETF/LOF → `fund_daily()`, índices → `index_daily()`, y acciones de HK → `hk_daily()` en lugar de llamar siempre a `daily()` (que devuelve vacío silenciosamente para no-acciones), con advertencias de resultado vacío/obtención parcial por símbolo ([#315](https://github.com/HKUDS/Vibe-Trading/pull/315), cierra [#310](https://github.com/HKUDS/Vibe-Trading/issues/310), gracias @shadowinlife).
- **2026-06-25** 🧪 **JSON de validación estricto + contexto de agente más ligero**: la validación de backtest independiente ahora normaliza los valores anidados `NaN` / `Infinity` antes de escribir `artifacts/validation.json` o la salida estándar de la CLI, de modo que los analizadores JSON estrictos ya no fallan con los payloads de validación ([#306](https://github.com/HKUDS/Vibe-Trading/pull/306), gracias @gyx09212214-prog). El prompt del agente también deriva el número actual de fuentes de datos desde el registro del cargador, y `_microcompact()` ahora espera a que haya presión real de tokens en lugar de limpiar resultados de herramientas antiguos durante ejecuciones cortas ([#296](https://github.com/HKUDS/Vibe-Trading/pull/296), cierra [#282](https://github.com/HKUDS/Vibe-Trading/issues/282), gracias @MarkfuGod).
- **2026-06-24** 🎯 **Contexto de precio de la cuenta espejo + UI china reactiva + corrección de autenticación LAN**: la extracción de reglas de la cuenta espejo ahora ve un contexto de entrada seguro en el tiempo (PIT) — `entry_rsi14` y `prior_5d_return` obtenidos a través del registro del cargador a la fecha de `buy_dt`, con degradación elegante sin conexión/sin datos ([#302](https://github.com/HKUDS/Vibe-Trading/pull/302), sigue a [#295](https://github.com/HKUDS/Vibe-Trading/issues/295), gracias @Robin1987China). Los paneles principales de la Web UI ahora usan traducciones reactivas en inglés / zh-CN en gráficos, chat, Alpha Library, Correlation y Run Detail ([#301](https://github.com/HKUDS/Vibe-Trading/pull/301), gracias @skloxo). Los despliegues remotos del mismo origen de la Web UI con `API_AUTH_KEY` pueden volver a publicar y subir archivos tras el endurecimiento de CSRF, mientras que los orígenes cross-site no coincidentes siguen bloqueados ([#304](https://github.com/HKUDS/Vibe-Trading/pull/304), gracias @Hinotoi-agent).
- **2026-06-23** 🛡️ **Endurecimiento de CSRF de la API local**: una página web maliciosa ya no puede impulsar solicitudes cross-site inseguras (POST/PUT/DELETE) contra la API loopback — CORS bloquea la lectura de la respuesta pero no el efecto secundario, así que la confianza del modo de desarrollo loopback ahora aplica la protección cross-site existente a los métodos inseguros *antes* de otorgarla. Los métodos seguros y las subidas locales de CLI / no-navegador no se ven afectados ([#293](https://github.com/HKUDS/Vibe-Trading/pull/293), gracias @Hinotoi-agent).
- **2026-06-22** 🔧 **Corrección de OAuth de autorización en vivo + corrección del titular de Alpha Zoo**: `connector authorize` ahora mantiene abierto el intercambio OAuth durante un inicio de sesión de broker de varios minutos (ajustable mediante `VIBE_LIVE_AUTHORIZE_TIMEOUT_SECONDS`) y ya no lanza un servidor de callback competidor en el reintento, de modo que el token realmente persiste ([#281](https://github.com/HKUDS/Vibe-Trading/pull/281), cierra [#259](https://github.com/HKUDS/Vibe-Trading/issues/259), gracias @Robin1987China). La página de Alpha Zoo ya no imprime su recuento de alphas dos veces ([#287](https://github.com/HKUDS/Vibe-Trading/pull/287), cierra [#286](https://github.com/HKUDS/Vibe-Trading/issues/286), gracias @digger-yu). La investigación programada también recibió documentación de uso de extremo a extremo ([#288](https://github.com/HKUDS/Vibe-Trading/pull/288)).
- **2026-06-21** ⏰ **Ejecutor de investigación programada + biblioteca de informes + atribución posterior al backtest**: la investigación programada ahora funciona **de extremo a extremo** — un ejecutor en segundo plano desactivado por defecto (`VIBE_TRADING_ENABLE_SCHEDULER`) dispara los trabajos de intervalo/cron vencidos a través del runtime de sesión ([#278](https://github.com/HKUDS/Vibe-Trading/pull/278), gracias @mvanhorn, cerrando [#254](https://github.com/HKUDS/Vibe-Trading/issues/254)). Una nueva página de **biblioteca de ejecuciones `/reports`** lista, busca y filtra ejecuciones dignas de informe con enlaces a Run Detail + Compare ([#224](https://github.com/HKUDS/Vibe-Trading/pull/224), gracias @LemonCANDY42). Y después de cada backtest el agente ahora ejecuta **atribución por capas** — ganadores/perdedores a nivel de operación, regresión beta, análisis de régimen de mercado, y una prueba de permutación de Monte Carlo, condicionada por la disponibilidad de datos y el enrutamiento ([#280](https://github.com/HKUDS/Vibe-Trading/pull/280), gracias @shadowinlife).
- **2026-06-20** 🔬 **Se cierra el bucle del Research Autopilot (fase 3) + protección de integridad OHLC del cargador + 4 alphas académicos**: **Research Autopilot** ahora ejecuta **hipótesis → motor de señales → backtest** de extremo a extremo — `scaffold_signal_engine` escribe un motor con contrato correcto y `link_autopilot_backtest` retroalimenta las métricas de la ejecución a la hipótesis (**68 herramientas**) ([#267](https://github.com/HKUDS/Vibe-Trading/pull/267)). Una **comprobación estructural de sanidad OHLC** descarta barras corruptas (`high < low`, precios no positivos, mal encuadre) de forma centralizada en el límite del cargador, protegiendo cada fuente de datos ([#274](https://github.com/HKUDS/Vibe-Trading/pull/274), gracias @Shizoqua). Y la **familia de alphas académicos crece de 6 a 10** — reversión de Jegadeesh, máximo de 52 semanas de George-Hwang, iliquidez de Amihud, asimetría de Harvey-Siddique (**456 factores**) ([#277](https://github.com/HKUDS/Vibe-Trading/pull/277), gracias @Robin1987China).
- **2026-06-19** 🚀 **v0.1.10 — Capa de datos global**: las fuentes de datos de mercado crecen de 10 a 18 (gratuitas **Eastmoney / Sina / Stooq / Yahoo** + con clave **Finnhub / Alpha Vantage / Tiingo / FMP**, con respaldo ante riesgo de bloqueo) más **18 herramientas de datos de solo lectura** (flujo de fondos, dragon-tiger, flujo hacia el norte, margen, operaciones en bloque, SEC EDGAR + XBRL, estados financieros, cadenas de opciones, cribado de todo el mercado…) en A-share / US / HK, todo a través de MCP. También agrupa todo lo publicado desde 0.1.9 — 10 conectores de broker, `alpha compare`, la revisión general de fiabilidad de proveedores, y la caché de datos opcional. `pip install -U vibe-trading-ai`
- **2026-06-18** 🔬 **Research Autopilot fase 1 + un cargador local Data Bridge, + un aviso de seguridad de Discord**: las nuevas `run_research_autopilot` + `generate_backtest_config` conectan **Hipótesis → Objetivo de Investigación → backtest** de extremo a extremo (ahora **50 herramientas**), y un cargador **`local`** lee OHLCV directamente desde tus propios archivos **CSV / Parquet / DuckDB** ([#260](https://github.com/HKUDS/Vibe-Trading/pull/260), [#252](https://github.com/HKUDS/Vibe-Trading/pull/252), gracias @Robin1987China), junto con el análisis de llamadas a herramientas `DSML` de DeepSeek y una ola de endurecimiento de contención de identificadores. ⚠️ **Seguridad:** la antigua invitación de Discord de la comunidad ahora apunta a un servidor que no controlamos, que ejecuta una estafa de phishing con una falsa "verificación" de wallet de Collab.Land — eliminada en todas partes; el **único** Discord oficial es el servidor de HKUDS ([discord.gg/6TdQnT5xcF](https://discord.gg/6TdQnT5xcF)), y nunca te pediremos que conectes una wallet.
- **2026-06-17** 🧩 **Compatibilidad de instalación + correcciones de proveedores Opus/Kimi**: la instalación base `pip install vibe-trading-ai` ya no arrastra la cadena de dependencias opcional `pyharmonics` / `ta`; la detección armónica ahora vive detrás de `vibe-trading-ai[harmonic]` mientras el detector integrado sigue disponible ([#250](https://github.com/HKUDS/Vibe-Trading/pull/250), cierra [#249](https://github.com/HKUDS/Vibe-Trading/issues/249)). El bucle del agente también evita los mensajes de traspaso de prellenado del asistente rechazados por Opus 4.8+, y Kimi/Moonshot puede sobrescribir el `User-Agent` del cliente con `MOONSHOT_USER_AGENT` ([#248](https://github.com/HKUDS/Vibe-Trading/pull/248), cierra [#246](https://github.com/HKUDS/Vibe-Trading/issues/246) y [#204](https://github.com/HKUDS/Vibe-Trading/issues/204)); las pruebas de seguimiento ahora cubren directamente las rutas de traspaso de resultados en segundo plano y de auto-compactación ([#251](https://github.com/HKUDS/Vibe-Trading/pull/251)).
- **2026-06-16** 🛡️ **Endurecimiento de seguridad/API + alias GLM/Zhipu**: las escrituras de Settings requieren autenticación cuando está configurada ([#245](https://github.com/HKUDS/Vibe-Trading/pull/245)); las herramientas de la API con capacidad de shell requieren la habilitación explícita `VIBE_TRADING_ENABLE_SHELL_TOOLS=1` ([#243](https://github.com/HKUDS/Vibe-Trading/pull/243)); el apagado local requiere autenticación cuando hay una clave de API configurada ([#241](https://github.com/HKUDS/Vibe-Trading/pull/241)); y los hosts con apariencia loopback no confiables se rechazan en lugar de tratarse como locales ([#242](https://github.com/HKUDS/Vibe-Trading/pull/242)). También se limpiaron bordes del runtime: el chat de la Web UI sincroniza los intentos completados ([#236](https://github.com/HKUDS/Vibe-Trading/pull/236)), las tarjetas de ejecución emiten JSON estricto para métricas no finitas ([#238](https://github.com/HKUDS/Vibe-Trading/pull/238)), un valor malformado de `RSSHUB_TIMEOUT_S` / `RSSHUB_FETCH_BUDGET_S` recurre de forma segura a su valor por defecto ([#240](https://github.com/HKUDS/Vibe-Trading/pull/240)), y el respaldo de reintento de ddgs cuenta con cobertura de regresión ([#239](https://github.com/HKUDS/Vibe-Trading/pull/239)). GLM/Zhipu es ahora un alias de proveedor de primera clase con inferencia de nombre de modelo ([#247](https://github.com/HKUDS/Vibe-Trading/pull/247), cierra [#237](https://github.com/HKUDS/Vibe-Trading/issues/237)).

- **2026-06-15** 🧭 **Resiliencia de búsqueda web + correcciones de continuidad de ejecución en la Web UI**: `web_search` ya no falla cuando un solo motor está limitado por tasa — ahora consulta varios motores gratuitos sin clave en orden (DuckDuckGo, Google, Bing, Brave, Mojeek, Yahoo) con reintento/backoff, trata "sin resultados" como una respuesta vacía en lugar de un error, y devuelve un mensaje útil en lugar de un ❌ escueto cuando todos los motores están limitados (sobrescribe la lista de motores con `VIBE_TRADING_SEARCH_BACKENDS`) ([#232](https://github.com/HKUDS/Vibe-Trading/pull/232), cierra [#231](https://github.com/HKUDS/Vibe-Trading/issues/231), gracias @Ethan-sun01). En la Web UI, cambiar de página durante una ejecución ya no la congela — el chat se vuelve a suscribir a la transmisión en vivo y reproduce el progreso perdido al regresar ([#234](https://github.com/HKUDS/Vibe-Trading/pull/234)) — y el botón Detener ahora surte efecto en medio de la transmisión y entre herramientas en lugar de solo en los límites de iteración ([#235](https://github.com/HKUDS/Vibe-Trading/pull/235)), cerrando ambas mitades de [#229](https://github.com/HKUDS/Vibe-Trading/issues/229) (gracias @kalkinj). El cargador de baostock también acepta códigos nativos `sh.601398` / `sz.000001` junto con el estilo tushare `601398.SH` ([#230](https://github.com/HKUDS/Vibe-Trading/pull/230), gracias @bhlt).

- **2026-06-14** 📊 **Uso de tokens por ejecución + gráficos progresivos en Run Detail**: cada ejecución del agente ahora persiste el uso de tokens reportado por el proveedor como un `llm_usage.json` a nivel de ejecución — proveedor/modelo, totales agregados y conteos por iteración — expuesto de forma aditiva en `/runs/{id}`, de modo que el costo en tokens de una ejecución terminada sigue siendo auditable después de que la transmisión en vivo desaparece (solo datos reportados por el proveedor; sin captura de prompt/contenido, sin estimación de precio) ([#223](https://github.com/HKUDS/Vibe-Trading/pull/223), gracias @LemonCANDY42). La página Run Detail ya no carga por adelantado las velas de todos los símbolos: la respuesta por defecto de `/runs/{id}` no cambia, pero la UI ahora renderiza primero el resumen de la ejecución y carga el gráfico de cada símbolo a demanda mediante los modos opcionales `?chart_payload=summary` / `?chart_symbol=`, con estado de carga por símbolo y un control de "cargar todo con progreso" ([#225](https://github.com/HKUDS/Vibe-Trading/pull/225), gracias @LemonCANDY42). Dos correcciones del cargador cierran el ciclo: el límite exclusivo `end` de yfinance ya no descarta el último día de negociación solicitado — la descarga ahora pasa `end + 1 día` mientras las claves de caché conservan el rango original ([#226](https://github.com/HKUDS/Vibe-Trading/pull/226), gracias @gyx09212214-prog) — y un valor malformado de `CCXT_TIMEOUT_MS` / `OKX_TIMEOUT_S` ahora advierte y recurre a su valor por defecto en lugar de lanzar una excepción en la importación y bloquear el arranque ([#227](https://github.com/HKUDS/Vibe-Trading/pull/227), gracias @gyx09212214-prog).
- **2026-06-13** ↩️ **Reanudar una sesión pasada por ID desde la CLI**: la CLI interactiva ahora imprime el id de sesión al salir, con una sugerencia lista para copiar y pegar `vibe-trading resume <session-id>` — de modo que localizar el rastro de una ejecución terminada ya no implica adivinar cuál carpeta bajo `agent/sessions/` es la más reciente por timestamp. El nuevo subcomando `vibe-trading resume <session-id>` reabre exactamente esa sesión y reproduce sus turnos recientes en el bucle; un id desconocido falla rápido en lugar de iniciar silenciosamente una sesión en blanco ([#218](https://github.com/HKUDS/Vibe-Trading/pull/218), gracias @zwrong).
- **2026-06-12** 🩺 **Revisión general de fiabilidad de proveedores — bloqueos de DeepSeek, acceso a Kimi, viveza del streaming**: un conjunto de reportes de proveedores — ejecuciones de DeepSeek atascadas en "Agent is working…" ([#208](https://github.com/HKUDS/Vibe-Trading/issues/208), gracias @XYWOX), `reached max iterations` enmascarando respuestas vacías del modelo ([#203](https://github.com/HKUDS/Vibe-Trading/issues/203), gracias @mojianliang), la UI que nunca se recupera tras un estancamiento ([#195](https://github.com/HKUDS/Vibe-Trading/issues/195), gracias @mafia23), y Kimi rechazando al cliente ([#204](https://github.com/HKUDS/Vibe-Trading/issues/204), gracias @liao497) — compartían una misma raíz: cada proveedor compatible con OpenAI pasaba por un único shim que aplicaba peculiaridades de DeepSeek/Kimi/Gemini de forma global y silenciaba fallos de transmisión. El comportamiento específico de cada proveedor ahora vive en una **capa de capacidades** explícita — captura/reproducción de razonamiento, firmas de pensamiento de Gemini, el `User-Agent` de Kimi, el cuerpo de razonamiento de OpenRouter están cada uno acotados a su propio proveedor en lugar de contaminarse entre sí. Las transmisiones que solo contienen razonamiento muestran un indicador en vivo de **"Reasoning…"** en lugar de silencio absoluto; un fallo de transmisión lanza un `provider_stream_error` contextual con un reintento automático para reinicios transitorios (los 4xx deterministas fallan rápido) en lugar de recurrir silenciosamente a una llamada no transmitida más lenta; una respuesta vacía del modelo se reporta como `empty_model_response` en lugar de "max iterations"; los heartbeats de SSE ya no rompen la reproducción de reconexión; y una herramienta de solo lectura atascada expira en lugar de esconderse detrás de los heartbeats para siempre. Un nuevo **`vibe-trading provider doctor`** imprime una instantánea redactada de proveedor/modelo/paquete/proxy para triaje en un solo comando de bloqueos del lado del entorno. Los usuarios de DeepSeek pueden optar por el adaptador nativo oficial con `pip install "vibe-trading-ai[deepseek]"`, y el requisito `temperature=1` de kimi-k2.x se aplica automáticamente — la ruta de Kimi está verificada de extremo a extremo contra la API en vivo (llamadas a herramientas + reproducción estricta de razonamiento multi-turno en `kimi-k2.6`).

- **2026-06-11** 🐝 **Los workers del swarm ahora obtienen datos de mercado a través de la capa del cargador**: una ejecución del comité de inversión sobre NVDA expuso una cadena de brechas — los workers escribían scripts ad-hoc de yfinance, confiaban en una última barra malformada (volumen presente, OHLC vacío), filtraban `NaN` en JSON no estricto, y un prompt de continuación sin contexto reenrutaba al preset equivocado ([#198](https://github.com/HKUDS/Vibe-Trading/issues/198), gracias @BillDin por un diagnóstico excepcional además de ambas correcciones). Los workers del swarm ahora obtienen una herramienta local `get_market_data` respaldada por el mismo registro de cargador normalizado que MCP — JSON estricto, los flotantes no finitos se serializan como `null` — conectada a **cada preset de datos de mercado** (21 workers en 13 presets) con una política de prompt que orienta el trabajo de OHLCV primero hacia herramientas ([#199](https://github.com/HKUDS/Vibe-Trading/pull/199)); `run_swarm` toma un `preset_name` explícito y rechaza fragmentos de continuación ambiguos en lugar de recurrir silenciosamente a `equity_research_team` ([#200](https://github.com/HKUDS/Vibe-Trading/pull/200)). El anclaje también se volvió más inteligente: un ticker estadounidense simple como `NVDA` en un prompt de swarm se promueve a `NVDA.US` (con protección contra stopwords), de modo que los workers parten de precios pre-obtenidos y autorizados. La herramienta también se une al registro del agente principal — ahora **48 herramientas**. Además: **tus datos de Docker ahora sobreviven a las actualizaciones** — la memoria persistente, el índice de búsqueda de sesiones, las skills creadas por el usuario, las cuentas espejo y la configuración de broker viven en volúmenes con nombre, de modo que `docker compose up --build` ya no los borra ([#197](https://github.com/HKUDS/Vibe-Trading/issues/197), gracias @FlyerJ).
- **2026-06-10** 🐳 **Docker alcanza un Ollama del lado del host listo para usar**: dentro del contenedor, `localhost` es el propio contenedor, así que el `OLLAMA_BASE_URL=http://localhost:11434` incluido por defecto fallaba en la comprobación previa del LLM para cada configuración de Ollama en Docker. `docker-compose.yml` ahora por defecto usa `http://host.docker.internal:11434` (exporta `OLLAMA_BASE_URL` para apuntar a otro lugar) y agrega el mapeo `host-gateway` en `extra_hosts` para que el mismo archivo funcione tanto en Linux como en Docker Desktop ([#196](https://github.com/HKUDS/Vibe-Trading/pull/196), gracias @ShahNewazKhan).
- **2026-06-09** 🔑 **Error más claro cuando la Web UI se abre desde otra máquina**: acceder al chat desde un cliente no loopback (otra máquina, un host VM, un teléfono en tu LAN) sin `API_AUTH_KEY` configurado devolvía `403` en cada endpoint sensible — enviar un mensaje, listar sesiones, estado en vivo — pero el chat solo mostraba un genérico "Failed to send message, please retry.". La ruta de envío ahora muestra la razón real — *"Remote API access requires an API key. Add it in Settings, or run the backend on localhost for local-only use."* — y la configuración de la Web UI en el README explica la regla de localhost frente a LAN además de las tres soluciones (navegar vía `localhost` en la misma máquina; configurar `API_AUTH_KEY` e ingresarlo una vez en Settings; o `VIBE_TRADING_TRUST_DOCKER_LOOPBACK=1` para la puerta de enlace del host de Docker Desktop) ([#191](https://github.com/HKUDS/Vibe-Trading/issues/191), gracias @mafia23).
- **2026-06-08** 🔧 **Corrección de llamadas a herramientas multi-turno de Gemini 3.x**: esto completa la corrección del modelo de pensamiento de Gemini 3.x. El intercambio del 6/05 ([#176](https://github.com/HKUDS/Vibe-Trading/pull/176)) solo cubría el historial en memoria, pero el bucle real del agente reproduce el historial como diccionarios en formato OpenAI, donde LangChain descartaba la `thought_signature` por llamada a herramienta antes de construir la solicitud — así que las llamadas a herramientas multi-turno seguían fallando con `400` por `missing thought_signature`. Ahora se vuelve a adjuntar en el único punto de estrangulamiento `_convert_input` por el que pasan tanto `invoke` como `stream` (incluidas las llamadas paralelas, donde solo la primera de N está firmada) ([#184](https://github.com/HKUDS/Vibe-Trading/pull/184), gracias @ngoanpv).
- **2026-06-07** 🐝 **Estado del swarm en vivo en la línea de tiempo del chat**: cuando el agente lanza un swarm multiagente (comité de inversión, mesa cuantitativa, comité de riesgo, …), el chat ahora renderiza una **tarjeta de estado** en línea que transmite el estado de cada worker — esperando / ejecutando / hecho / fallido / bloqueado / reintentando — en tiempo real, la misma visibilidad por agente que ya tenía el panel independiente del swarm. Los eventos del runtime se puentean hacia la transmisión SSE de la sesión sin cambiar la API `/swarm/runs` existente, y una tarjeta terminada se rehidrata desde el resultado final de `run_swarm` al reconectar o reproducir el historial ([#188](https://github.com/HKUDS/Vibe-Trading/pull/188), gracias @BillDin). El enrutamiento de presets también se volvió más preciso: un preset nombrado explícitamente (p. ej., `investment_committee`, con o sin guiones bajos) ahora gana sobre la puntuación por palabras clave, y la palabra clave desnuda `IV` de derivados ya no coincide falsamente dentro de palabras comunes como "g**iv**en" ([#189](https://github.com/HKUDS/Vibe-Trading/pull/189), gracias @BillDin).
- **2026-06-06** ⚖️ **Alpha compare — cara a cara entre CLI, Web UI, REST y agente**: un nuevo `alpha compare` enfrenta una lista corta de alphas de Alpha Zoo entre sí en un universo y periodo, y luego los clasifica por IC medio/desviación, IR, ratio de IC positivo o número de muestras — cada uno con su brecha respecto al líder. A diferencia de un bench completo del zoo, evalúa **solo los alphas que nombres** (un nuevo filtro de subconjunto `run_bench(only=…)`), así que comparar tres alphas ya no puntúa los 191 de su zoo. Un núcleo compartido impulsa cada superficie: `vibe-trading alpha compare <id1> <id2> … --sort ir` (CLI), una **vista Compare** en la Web UI de Alpha Zoo (marca alphas en el catálogo → comparación con un clic con una tabla de clasificación transmitida), `POST /alpha/compare` + SSE (REST), y una herramienta de agente de solo lectura `alpha_compare` (**47 herramientas** ahora).
- **2026-06-05** 🇮🇳 **Conectores Dhan + Shoonya (India) — 10 brokers en total**: la capa de trading orientada a conectores agrega **Dhan** y **Shoonya** para el mercado indio (acciones NSE/BSE + F&O), llevando el total a diez brokers. Ambos son **solo paper + solo lectura** — como Longbridge, sus APIs no exponen ningún discriminador de runtime entre paper y live, así que sus `place_order` / `cancel_order` rechazan de forma estricta cualquier configuración que no sea paper desde la primera línea (la regla: un broker sin protección estructural entre paper y live queda limitado a paper + solo lectura) ([#181](https://github.com/HKUDS/Vibe-Trading/pull/181), cierra [#174](https://github.com/HKUDS/Vibe-Trading/issues/174)). Este ciclo también corrige los **modelos de pensamiento de Gemini 2.5 / 3.x**: su `thoughtSignature` por llamada a herramienta ahora se propaga correctamente a través de la ruta compatible con OpenAI, así que las llamadas a funciones multi-turno ya no fallan con `INVALID_ARGUMENT` ([#176](https://github.com/HKUDS/Vibe-Trading/pull/176), cierra [#170](https://github.com/HKUDS/Vibe-Trading/issues/170), gracias @mvanhorn y @jliu6789). Se agregaron docstrings en chino a los **452 factores de Alpha Zoo** ([#180](https://github.com/HKUDS/Vibe-Trading/pull/180), gracias @LeeCQiang), y una **suite de pruebas frontend (197 pruebas vitest)** más pruebas de seguridad backend de autenticación / recorrido de rutas / CORS se unieron a la CI ([#175](https://github.com/HKUDS/Vibe-Trading/pull/175), gracias @sambazhu).
- **2026-06-04** 🗃️ **Caché de datos local opcional para las 7 fuentes de datos**: un nuevo interruptor `VIBE_TRADING_DATA_CACHE` permite que cada cargador de backtest — tushare, okx, ccxt, akshare, mootdx, yfinance, futu — almacene en caché las barras históricas ya asentadas bajo `~/.vibe-trading/cache` (directorio de usuario, nunca el repositorio), de modo que los backtests repetidos y de largo horizonte / entre mercados evitan la red y las limitaciones de tasa del proveedor. Desactivado por defecto. Los cargadores por lotes y de conexión (yfinance, futu) omiten por completo la descarga masiva / la conexión a FutuOpenD ante un acierto total de caché, una protección de obsolescencia nunca almacena en caché un rango que termina hoy (su última barra aún se está formando), y los marcos en caché se reproducen byte a byte idénticos a los recién obtenidos ([#177](https://github.com/HKUDS/Vibe-Trading/pull/177), gracias @mvanhorn). También se publicó una nueva guía para colaboradores para PR asistidos por IA / automatización, que mapea las comprobaciones locales seguras y las superficies de alto riesgo de broker/MCP/credenciales ([#173](https://github.com/HKUDS/Vibe-Trading/pull/173)).
- **2026-06-03** 🧹 **Triaje comunitario + correlación de trazas**: las entradas de traza de llamadas a herramientas ahora llevan el `call_id` original, de modo que un `tool_result` pueda emparejarse de vuelta con su `tool_call` al reproducir la traza de una ejecución — las vistas previas de argumentos se mantienen truncadas para que los archivos de traza sean pequeños ([#168](https://github.com/HKUDS/Vibe-Trading/pull/168), gracias @zwrong). Los comentarios del código fuente ya no apuntan a una ruta de documentación de uso interno que los colaboradores externos no podían encontrar ([#166](https://github.com/HKUDS/Vibe-Trading/issues/166), gracias @jaleelpersonal). También se clarificó que la advertencia del resolutor de `langchain-community` en la instalación es solo un aviso inofensivo de paquete residual, no un fallo ([#167](https://github.com/HKUDS/Vibe-Trading/issues/167)), y se catalogó la propagación de `thoughtSignature` de Gemini 2.5/3.0 para llamadas a funciones como una tarea `help wanted` con un plan de corrección completo ([#170](https://github.com/HKUDS/Vibe-Trading/issues/170), gracias @jliu6789).
- **2026-06-02** 🔌 **Seis nuevos conectores de broker (Tiger / Longbridge / Alpaca / OKX / Binance / Futu)**: la capa de trading orientada a conectores gana un transporte de SDK directo junto a IBKR (local) y Robinhood (MCP). Cada conector expone cuenta / posiciones / órdenes / cotización / historial de solo lectura **más colocación de órdenes en cuenta paper**; prueba tus estrategias en estas cuentas paper de broker. Cinco de ellos (Tiger, Alpaca, OKX, Binance, Futu) también admiten **colocación de órdenes acotada y con puerta de mandato** bajo el mismo modelo de seguridad que Robinhood: un mandato comprometido por el usuario (universo de símbolos / tamaño de orden / exposición / apalancamiento / límite diario), un interruptor de emergencia a nivel de sistema de archivos, una puerta previa a la operación que falla de forma segura, y un libro de auditoría completo. **Longbridge es solo paper + solo lectura** (su API no expone ningún discriminador de runtime entre paper y live). Cada distinción entre paper y live es una protección estructural por broker — formato de id de cuenta, separación de host, bandera de demo o entorno de trading. Nuevas herramientas `trading_place_order` / `trading_cancel_order`; se agregaron las clases de activos de HK y A-share al universo del mandato. Experimental / usar bajo tu propio riesgo.
- **2026-06-01** 🚀 **Se publica v0.1.9** (`pip install -U vibe-trading-ai`): recoge todo lo publicado desde 0.1.8. Perfiles de broker orientados a conectores (IBKR local de solo lectura TWS / IB Gateway + Robinhood Agentic Trading detrás de OAuth, un mandato comprometido, protección de órdenes, libro de auditoría y parada instantánea). Runtime de Objetivo de Investigación en CLI / REST / MCP / Web. Un pase sobre el swarm — reconciliación en vivo + keepalive de MCP, herramientas MCP de worker configuradas por el operador, un control aleatorio estricto para el alpha-bench, y un nuevo `retry_run` para relanzar ejecuciones fallidas/obsoletas (ahora **36 herramientas MCP**). La refactorización del paquete `agent/cli/` con una UI de terminal renovada, el cargador de A-share sin token `mootdx`, y un pase de robustez en backtest / bucle del agente / sesiones. `--version` ahora siempre coincide con el paquete instalado, corrigiendo la desviación de 0.1.8 ([#156](https://github.com/HKUDS/Vibe-Trading/issues/156)).
- **2026-05-31** 🔌 **Arquitectura de broker orientada a conectores (IBKR + Robinhood)**: el acceso al trading ahora parte de un perfil de conector seleccionable en lugar de puntos de entrada separados de broker/live. `vibe-trading connector list/use/check/account/positions/orders/quote/history` y las herramientas MCP `trading_*` comparten el mismo perfil seleccionado, donde paper/live es un atributo del conector. IBKR puede usarse de inmediato a través de un perfil local de solo lectura TWS / IB Gateway, mientras que la ruta oficial de MCP remoto de IBKR se establece como una sonda OAuth `mcp.read` hasta que haya nombres de herramientas de lectura estables disponibles. Robinhood Agentic Trading sigue siendo el conector MCP en vivo acotado detrás de OAuth, un mandato comprometido, protección de órdenes, libro de auditoría y parada instantánea.
- **2026-05-30** 🧰 **Pase de robustez — backtest, bucle del agente, sesiones**: los motores de señales generados por LLM ahora pasan una validación de interfaz previa antes de instanciarse, detectando auto-importaciones circulares, un `generate()` faltante, argumentos de `__init__` sin valor por defecto y tipos de retorno incorrectos con errores JSON útiles en lugar de tracebacks sin procesar ([#149](https://github.com/HKUDS/Vibe-Trading/pull/149)); una mejora posterior enruta los errores de validación AST a nivel de código fuente a través del mismo sobre JSON limpio. El bucle del agente ya no consume las 50 iteraciones para terminar en un estado `failed` sin salida — ahora refleja el aviso de cierre del worker del swarm al 80% del presupuesto de iteraciones y descarta las definiciones de herramientas en la última iteración para forzar una respuesta de texto final ([#148](https://github.com/HKUDS/Vibe-Trading/pull/148)), protegido para activarse solo a mitad de ejecución de modo que nunca desplace el contexto del objetivo de investigación. Las escrituras de mensajes de sesión ahora hacen `flush + fsync` en cada append para que las respuestas de IA costosas sobrevivan a un fallo a mitad de escritura, y la ruta de lectura omite las líneas JSONL corruptas (registrando los primeros 200 caracteres para recuperación) en lugar de devolver un 500 en todo el endpoint `/messages` ([#147](https://github.com/HKUDS/Vibe-Trading/pull/147)). El compositor de la Web también corrige el manejo de Enter con IME para que un Enter que confirma una composición ya no envíe a mitad de palabra ([#146](https://github.com/HKUDS/Vibe-Trading/pull/146)).
- **2026-05-29** 🔐 **Soporte de Robinhood Agentic Trading (opcional, autonomía acotada)**: agrega soporte para Robinhood Agentic Trading (MCP remoto, OAuth). Desactivado y de solo lectura por defecto; el agente actúa solo dentro de un mandato comprometido por el usuario (símbolos / tamaño de orden / exposición / apalancamiento / límite diario), con un interruptor de emergencia instantáneo a nivel de sistema de archivos, cierre preventivo de posiciones, expiración automática de mandato, un libro de auditoría completo y un runner autónomo persistente. Sin custodia, sin sede de negociación propia — el broker retiene los fondos y ejecuta; nosotros solo transmitimos la intención. Experimental / usar bajo tu propio riesgo.
- **2026-05-28** 🧪 **Seguridad del swarm + puerta estricta de alpha + MCP de worker**: el DAG del swarm bloquea tareas posteriores cuando falla una anterior ([#145](https://github.com/HKUDS/Vibe-Trading/pull/145)). El nuevo `run_bench_strict()` agrega un control aleatorio sobre el mismo universo + una división OOS para detectar factores que solo siguen el beta del mercado ([#143](https://github.com/HKUDS/Vibe-Trading/pull/143), gracias @Soli22de). Los workers del swarm pueden llamar a servidores MCP externos configurados por el operador, con el límite de confianza fijado ([#142](https://github.com/HKUDS/Vibe-Trading/pull/142), gracias @shadowinlife).
- **2026-05-27** 📊 **Fuente de datos A-share mootdx + refinamiento de salida**: el nuevo cargador `mootdx` habla el protocolo TCP nativo 通达信 para OHLCV de A-share (sin autenticación, sin límite de tasa por IP, diario + intradía con paginación de retroceso de 25 páginas), ubicándose entre tushare y akshare en la cadena de respaldo ([#107](https://github.com/HKUDS/Vibe-Trading/issues/107)). El cargador CCXT ahora lee `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY` para que los datos públicos de Binance/OKX funcionen desde redes restringidas ([#126](https://github.com/HKUDS/Vibe-Trading/pull/126), gracias @ruok808). El renderizado de la respuesta final también eliminó los feos separadores horizontales `---` de ancho completo en CLI y Web: el prompt del sistema ahora orienta al agente hacia tablas markdown y encabezados `##`, el renderizador de la CLI elimina los HR independientes como defensa adicional, y la burbuja de chat oculta cualquier `<hr>` que se filtre ([#139](https://github.com/HKUDS/Vibe-Trading/issues/139), gracias @sdwxm188).
- **2026-05-26** ✅ **Cierre del ciclo de vida del Objetivo de Investigación**: el modo Goal ahora se comporta como un ejecutor de tareas real: la creación de objetivos en la Web UI crea o vincula la sesión y envía de inmediato el turno de arranque; los objetivos activos pueden continuarse, editarse, cancelarse y completarse a través de Web/API/CLI/MCP; y el agente avanza desde la instantánea actual del objetivo (criterios, evidencia, afirmaciones, elementos abiertos) en lugar de solo el prompt original. Los objetivos cubiertos pero aún activos ahora entran en una actualización de auditoría/estado en lugar de detenerse en silencio, con cobertura de regresión en backend, CLI, MCP y eventos del frontend.

- **2026-05-25** 🧼 **UI de chat más limpia + flujo de trabajo del compositor**: la Web UI mantiene el chat centrado en la siguiente acción: los modos de subida, swarm y objetivo de investigación ahora viven detrás del menú `+` del compositor en lugar de paneles flotantes. El contexto activo aparece encima del campo de entrada como chips compactos, y los detalles del objetivo se expanden en línea solo cuando es necesario. La UI también elimina la antigua capa de i18n personalizada en favor de texto directo en inglés, restringe las tarjetas de Full Report a ejecuciones dignas de informe, y refuerza el arranque/reporte de estado del desarrollo local para pruebas de humo confiables en el navegador.
- **2026-05-24** 🎯 **Runtime del Objetivo de Investigación**: se agregó una capa de Objetivo de Investigación con alcance de sesión en backend, CLI, API/MCP, SSE y Web UI. Los objetivos persisten afirmaciones, criterios de aceptación, filas de evidencia, presupuestos y política de finalización; las herramientas del agente pueden crear objetivos y adjuntar evidencia; `/goal` le da a la CLI un punto de entrada directo; REST/MCP exponen instantáneas de objetivos y escrituras de evidencia; SSE mantiene actualizados a los clientes de chat. Correcciones de auditoría posteriores blindaron la evidencia verificada, bloquearon niveles de riesgo de trading en vivo a través de herramientas del agente, conectaron los objetivos creados por CLI a turnos posteriores, limpiaron los libros de objetivos al eliminar la sesión, habilitaron reproducir-todo, y corrigieron condiciones de carrera del frontend entre sesiones.
- **2026-05-23** 🖥️ **Renovación de la CLI interactiva**: la puerta de entrada de la terminal ahora se abre con un banner más grande de Vibe-Trading, un divisor de prompt más limpio, resumen del turno anterior, tiempo posterior a la ejecución, y un riel de actividad estilo Claude Code para el trabajo en vivo del agente. Las llamadas a herramientas, obtenciones de datos/web, acciones estilo shell, respuestas en Markdown y tablas con pipes se renderizan en una transcripción más legible, mientras que las ejecuciones canalizadas (piped) o sin TTY mantienen la salida de texto simple para automatización. Las capturas de pantalla de la CLI generadas ahora se tratan como artefactos locales en lugar de archivos de documentación versionados, manteniendo el repositorio más ligero.
- **2026-05-22** 🧭 **Recuperación del swarm + keepalive de MCP**: el estado del swarm ahora se reconcilia a partir de los archivos de tarea en vivo en cada lectura, de modo que las vistas de API/MCP/SSE/lista recuperan ejecuciones caídas o obsoletas en lugar de mostrar instantáneas permanentes de `running`. `run_swarm` envía heartbeats de progreso de MCP mientras hace sondeo, con un primer frame fijo de `swarm_started run_id=<id>` para los clientes que se reconectan tras cortes de transporte; los workers ahora emiten heartbeat durante el streaming del LLM, las obtenciones de anclaje y la ejecución de herramientas. El recolector de ejecuciones obsoletas usa umbrales por ejecución y deriva el estado terminal de los estados de las tareas, `SwarmTool` ya no cancela un equipo aún en ejecución solo porque su presupuesto de espera venció, y los clientes MCP pueden llamar a `reap_stale_runs()` para limpieza explícita. El pase de DX de hoy también actualizó los modelos por defecto de los proveedores y alineó las comprobaciones de sintaxis de CI con el nuevo paquete `agent/cli/`. 22 nuevas pruebas de regresión cubren hidratación, recuperación de terminal, recolección de obsoletos, cadencia de keepalive, análisis de entorno y conexión de heartbeat; la suite completa de swarm/MCP está en 169 aprobadas, 4 omitidas.
- **2026-05-21** 🧱 **Refactorización del paquete CLI**: `agent/cli.py` (3216 LOC) se dividió en el paquete `agent/cli/` — puerta de entrada interactiva, enrutador de slash, componentes Rich, más un shim `_legacy.py` que preserva cada subcomando y reexporta cada símbolo público para que `cli.cmd_*` / `cli._INIT_ENV_PATH` / `cli.Confirm` sigan funcionando. Un nuevo middleware de FastAPI sirve el shell de la SPA cuando un navegador abre `/runs/{id}` o `/correlation` directamente; el mismo estrechamiento se aplicó al proxy de desarrollo de Vite. La versión se unificó a través de `cli/_version.py` (ya no hay desviación entre `--version` y el banner), `python -m cli` se restauró mediante `__main__.py`, y la puerta del chat se estrechó para que `chat --help` / `chat extra` lleguen al argparse heredado en lugar de ser engullidos por el REPL.
- **2026-05-20** 🔬 **CLI del Registro de Hipótesis**: cierra el lado de CLI del Registro de Hipótesis publicado solo en backend el 2026-05-16. `vibe-trading hypothesis list` imprime una tabla Rich o JSON (filtro `--status`, `--limit`); `show <id>` renderiza un panel de detalle incluyendo tarjetas de ejecución vinculadas; `invalidate <id> --note "..."` cambia el estado a `rejected` preservando las notas de invalidación previas cuando se omite `--note`. Respeta la sobrescritura existente por variable de entorno `VIBE_TRADING_HYPOTHESES_PATH` y agrega un `--path` por invocación. 22 nuevas pruebas cubren la conexión, la salida JSON, el filtro de estado, el límite, los errores de id faltante y la persistencia de notas.
- **2026-05-19** ✨ **Retroalimentación de herramientas en vivo + cancelación elegante**: las herramientas de larga duración (backtests, PDFs grandes, workers de swarm) ya no parecen congeladas. Cada llamada a herramienta ahora emite un heartbeat de 3 segundos más progreso estructurado por etapa — `run_backtest` muestra marcadores de fase (`validate` / `simulate` / `finalize`), `read_document` marca el avance por página en PDF o por hoja en Excel, `read_url` marca `fetch` / `parse`. El panel Rich Live de la CLI renderiza un spinner Unicode, una barra de progreso ASCII, ETA, y apila hasta 3 herramientas en paralelo identificadas por nombre; el chat del frontend incorpora un nuevo `ToolProgressIndicator` con renderizados coalescidos por rAF, ARIA `role="status"` + un `<progress>` nativo oculto para lectores de pantalla, y un `ProgressRing` SVG determinado cuando se conoce el total. El primer `Ctrl+C` durante una ejecución de la CLI ahora llama a `agent.cancel()` para una salida elegante (el paso actual termina, la traza se cierra limpiamente); un segundo dentro de 2s fuerza el cierre. Primitivas reutilizables extraídas en el proceso: `ProgressBar.tsx` y `lib/tools.ts` (i18n de nombres de herramientas compartido).
- **2026-05-18** 🧹 **Pase de limpieza + tres correcciones de errores latentes**: `CompositeEngine` ya no enruta incorrectamente códigos de futuros chinos simples como `RB2410` a `GlobalFuturesEngine` — `_is_china_futures` se movió a un módulo compartido `_market_hooks` con una tabla de productos normalizada por mayúsculas/minúsculas y una protección para bolsas no chinas, más 9 nuevos casos de regresión. Los índices FTS5 de sesión ahora persisten timestamps para que la búsqueda entre sesiones pueda ordenar por fecha; la misma ruta también corrigió un re-upsert que actualizaba el reloj de pared del `started_at` de cada sesión. El proxy de modo desarrollo de Vite ganó la entrada faltante de `/alpha` para que la página AlphaZoo resuelva en `npm run dev`. `tests/test_e2e_harness_v2.py` (suite e2e con LLM real) ahora está condicionada por `VIBE_TRADING_RUN_LIVE_E2E=1` para que la CI ya no cambie de forma según la presencia de claves de entorno. Se agregaron `per-file-ignores` de Ruff para el zoo de factores (3783 → 0 avisos F401), el tsconfig del frontend habilita `noUnusedLocals` / `noUnusedParameters` como protecciones de regresión, y se eliminaron 76 líneas de código repetitivo sin uso `vw = vwap(...)` de los alphas de `gtja191`. Neto **-918 LOC**.
- **2026-05-17** 🧬 **Alpha Zoo v1 (0.1.8)**: 452 alphas cuantitativos preconstruidos en 4 zoos — `qlib158` (Microsoft Qlib, atribución Apache-2), `alpha101` (Kakushadze 101 Formulaic Alphas, reescritura del paper de arXiv:1601.00991), `gtja191` (informe de factores de corto plazo de Guotai Junan de 2014), y `academic` (proxies basados en precio de Fama-French 5 + Carhart). Un comando CLI de una línea para benchmarking de cualquier zoo en tu universo: `vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025`. Incluye una puerta de pureza AST, una prueba de protección contra lookahead, un interruptor de emergencia de red `pytest-socket`, un LICENSE.md por zoo, y un flujo de Developer Certificate of Origin (DCO) para PRs de la comunidad. Alpha Library autogenerada en [vibetrading.wiki/alpha-library/](https://vibetrading.wiki/alpha-library/) + artículo del laboratorio de investigación [¿Cuáles de los 191 alphas de GTJA aún funcionan en 2026?](https://vibetrading.wiki/research-lab/posts/alpha-191-in-2026.html).
- **2026-05-16** 🧪 **Actualización de la columna vertebral de investigación**: se agregó un Registro de Hipótesis en el backend con `create_hypothesis`, `update_hypothesis`, `link_backtest` y `search_hypotheses`; los lectores de contenido externo ahora adjuntan `security_warnings` solo de advertencia; y el escaneo de la cuenta espejo ahora usa evaluación determinista de características OHLCV en lugar del antiguo stub de fase calendárica.
- **2026-05-15** 🪪 la página de detalle de ejecución ahora muestra la tarjeta de la Capa de Confianza junto a métricas y artefactos, completando el lado de UI del trabajo de `run_card.json` publicado el 2026-05-12. `PersistentMemory.add()` también se reforzó en cuanto a longitud, nombres vacíos o con solo espacios en blanco, y bytes de control C0/C1 a partir del triaje de #108/#109/#110 ([#112](https://github.com/HKUDS/Vibe-Trading/pull/112), gracias @Teerapat-Vatpitak).
- **2026-05-14** 🌐 la wiki pública ya está en línea en [vibetrading.wiki](https://vibetrading.wiki/) con secciones de documentación, tutoriales, Research Lab y Alpha Library desplegadas a través de Cloudflare Pages. La memoria persistente también es inspeccionable desde la CLI mediante `vibe-trading memory list/show/search/forget` ([#102](https://github.com/HKUDS/Vibe-Trading/pull/102), gracias @Teerapat-Vatpitak), y la tokenización/slugs de memoria ahora admiten texto en tailandés, árabe, hebreo y cirílico ([#104](https://github.com/HKUDS/Vibe-Trading/pull/104)).
- **2026-05-13** 🧭 las ejecuciones de swarm ahora fundamentan a los workers con datos de mercado obtenidos e informes persistidos más limpios ([#93](https://github.com/HKUDS/Vibe-Trading/pull/93), [#84](https://github.com/HKUDS/Vibe-Trading/pull/84)).
- **2026-05-12** 🧾 los backtests ahora emiten `run_card.json` y `run_card.md` junto con los artefactos para ejecuciones de investigación reproducibles.
- **2026-05-11** 🧭 **Slugs de memoria, contabilidad de swarm y comprobación previa de la CLI**: la memoria persistente ahora preserva los caracteres CJK al generar slugs de archivo, evitando colisiones silenciosas de nombre de archivo para notas en chino/japonés/coreano ([#95](https://github.com/HKUDS/Vibe-Trading/pull/95), gracias @voidborne-d). Los totales de ejecución de swarm ahora prefieren el uso de tokens reportado por el proveedor con el respaldo de estimación existente ([#94](https://github.com/HKUDS/Vibe-Trading/pull/94), gracias @Teerapat-Vatpitak), y la UI de ejecución de la CLI obtuvo una comprobación previa de arranque para problemas comunes de entorno ([#96](https://github.com/HKUDS/Vibe-Trading/pull/96), gracias @ykykj).
- **2026-05-10** 🧱 **Protecciones de regresión + metadatos de ejecución**: la recuperación de memoria ahora trata los guiones bajos como límites de token, de modo que las memorias guardadas en snake_case como `mcp_wiring_test` coincidan con consultas en lenguaje natural como "mcp wiring" ([#87](https://github.com/HKUDS/Vibe-Trading/pull/87), gracias @hp083625). El servidor MCP tiene una prueba de humo de subproceso que cubre initialize → `tools/list` → `tools/call` para proteger la ruta de bloqueo en la primera llamada ([#86](https://github.com/HKUDS/Vibe-Trading/pull/86)), mientras que se aplicó endurecimiento de bajo riesgo para pruebas sensibles a rutas en Windows, manejo de excepciones best-effort de la API, validación de raíz permitida de `run_dir` en el backtest, y metadatos de proveedor/modelo de SwarmRun ([#88](https://github.com/HKUDS/Vibe-Trading/pull/88), [#90](https://github.com/HKUDS/Vibe-Trading/pull/90), [#91](https://github.com/HKUDS/Vibe-Trading/pull/91), [#92](https://github.com/HKUDS/Vibe-Trading/pull/92), gracias @Teerapat-Vatpitak).
- **2026-05-09** 🛡️ **Endurecimiento de rutas de la API + estabilidad del servidor MCP**: las rutas de ejecución/sesión de la API ahora validan los IDs de ruta antes de la búsqueda, rechazando parámetros malformados que contienen saltos de línea y fijando el comportamiento en la suite de regresión de autenticación/seguridad ([#80](https://github.com/HKUDS/Vibe-Trading/pull/80), gracias @SJoon99). El servidor MCP ahora precalienta el registro de herramientas en el hilo principal antes de servir `tools/call`, evitando un bloqueo en la primera llamada en el descubrimiento perezoso de herramientas ([#85](https://github.com/HKUDS/Vibe-Trading/pull/85), gracias @Teerapat-Vatpitak). El proxy de desarrollo de Vite también respeta `VITE_API_URL` para destinos de backend no predeterminados ([#82](https://github.com/HKUDS/Vibe-Trading/pull/82), gracias @voidborne-d).
- **2026-05-08** 🧾 **Campos de estados financieros de Tushare en filtros**: los backtests diarios de A-share ahora pueden solicitar campos de estados financieros seguros en el tiempo (PIT) mediante `fundamental_fields`, de modo que los motores de señales puedan filtrar por `income_total_revenue`, `income_n_income`, `balancesheet_total_hldr_eqy_exc_min_int`, `fina_indicator_roe` y columnas similares con prefijo de tabla después de sus fechas de anuncio/divulgación ([#76](https://github.com/HKUDS/Vibe-Trading/pull/76), gracias @mrbob-git). Un endurecimiento posterior hace que las solicitudes explícitas de campos de estados financieros fallen rápido si el enriquecimiento de Tushare no puede ejecutarse, en lugar de recurrir silenciosamente a las barras de precio sin procesar ([#77](https://github.com/HKUDS/Vibe-Trading/pull/77)).
- **2026-05-07** 📈 **Fundamentales de Tushare + triaje comunitario**: se agregó un contrato `TushareFundamentalProvider` seguro en el tiempo (point-in-time) para flujos de trabajo de investigación fundamental, con cobertura de regresión para la ruta de variable de entorno `TUSHARE_TOKEN` del proyecto ([#74](https://github.com/HKUDS/Vibe-Trading/pull/74)). El triaje comunitario también clarificó que Vibe-Trading mantiene la iteración rápida enfocada en un solo idioma de UI por ahora, evita agregar dependencias de búsqueda redundantes mientras `web_search` respaldado por DuckDuckGo ya está incluido, y trata los despliegues alojados no oficiales como lugares no confiables para claves de API o tokens de fuente de datos.
- **2026-05-06** 🚀 **Se publica v0.1.7** ([Notas de la versión](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.7), `pip install -U vibe-trading-ai`): el endurecimiento del límite de seguridad ya está publicado en PyPI y ClawHub, cubriendo valores por defecto más seguros de API/lectura/subida/archivo/URL/código generado/herramienta de shell/Docker mientras se mantiene la baja friccion de los flujos de trabajo de CLI/Web UI en localhost. Este ciclo también incluye Settings de la Web UI, mapa de calor de correlación, OAuth de OpenAI Codex, filtrado de pre-ST de A-share, UX de CLI interactiva, inspección de presets de swarm, análisis de dividendos, refinamiento del flujo de desarrollo y pisos de dependencias de compilación del frontend auditados. Gracias a los colaboradores de 0.1.7 y a lemi9090 (S2W) por la validación de seguridad coordinada.
- **2026-05-05** 🛡️ **Seguimiento del límite de seguridad**: completa el endurecimiento restante del límite de seguridad en torno a orígenes CORS explícitos, indicadores de credenciales de Settings, lectura de URL web, y generación de código de la cuenta espejo, con pruebas de regresión agregadas para cada ruta. Los flujos de trabajo normales de CLI/Web UI en localhost permanecen igual; los despliegues remotos deberían seguir usando `API_AUTH_KEY` y orígenes de confianza explícitos.
- **2026-05-04** 🖥️ **UX de CLI interactiva + limpieza de CI**: el modo interactivo ahora tiene una barra de estado inferior en vivo que muestra proveedor/modelo, duración de sesión, latencia de la última ejecución y estadísticas acumuladas de llamadas a herramientas, además de navegación por el historial de prompts y edición con el cursor mediante las flechas del teclado a través de `prompt_toolkit` ([#69](https://github.com/HKUDS/Vibe-Trading/pull/69)). La CLI sigue recurriendo a los prompts de Rich cuando `prompt_toolkit` o una TTY no están disponibles. Las expectativas de rutas de la CI también se alinearon con el sandbox reforzado de importación de archivos y la resolución multiplataforma de `/tmp`, devolviendo main a verde ([`bb67dc7`](https://github.com/HKUDS/Vibe-Trading/commit/bb67dc7cfcc11553c57d8962bee56381dca43758)).
- **2026-05-03** 🛡️ **Parche de endurecimiento de seguridad**: refuerza la autenticación de API por defecto para despliegues no locales, protege las lecturas sensibles de ejecución/sesión/swarm, restringe los límites de subida y lectura de archivos locales, condiciona las herramientas con capacidad de shell por punto de entrada, valida la carga de estrategias generadas antes de la importación, y ejecuta la imagen de Docker como usuario no root con un puerto publicado solo en localhost por defecto. Los flujos de trabajo de CLI local y Web UI en localhost siguen teniendo baja fricción; los despliegues remotos de API/Web deberían configurar `API_AUTH_KEY`.
- **2026-05-02** 🧭 **Análisis de dividendos + hoja de ruta más definida**: se agregó la skill `dividend-analysis` para acciones de ingreso, sostenibilidad de pagos, crecimiento de dividendos, rendimiento para el accionista y comprobaciones de trampas de rendimiento, fijada mediante pruebas de regresión de skills incluidas. La hoja de ruta pública ahora se enfoca en el trabajo próximo: Research Autopilot, Data Bridge, Options Lab, Portfolio Studio, Alpha Zoo, Research Delivery, Trust Layer y compartición con la comunidad.
- **2026-05-01** 🔥 **Mapa de calor de correlación + OAuth de OpenAI Codex + filtro de pre-ST de A-share**: el nuevo panel/API de correlación calcula correlaciones de retorno rolling y renderiza un mapa de calor ECharts para análisis de portafolio y símbolos ([#64](https://github.com/HKUDS/Vibe-Trading/pull/64)). El soporte del proveedor OpenAI Codex ahora usa OAuth de ChatGPT mediante `vibe-trading provider login openai-codex`, con metadatos de Settings y pruebas de regresión del adaptador ([#65](https://github.com/HKUDS/Vibe-Trading/pull/65)). Se agregó y reforzó la skill `ashare-pre-st-filter` para el cribado de riesgo ST/*ST de A-share, incluyendo filtrado de relevancia de sanciones de Sina para que las menciones de cuentas de valores no inflen los recuentos E2 ([#63](https://github.com/HKUDS/Vibe-Trading/pull/63)).
- **2026-04-30** ⚙️ **Settings de la Web UI + endurecimiento de la CLI de validación**: nueva página de Settings para proveedor/modelo de LLM, URL base, esfuerzo de razonamiento y credenciales de fuente de datos, respaldada por APIs de configuración locales/protegidas por autenticación y metadatos de proveedor basados en datos ([#57](https://github.com/HKUDS/Vibe-Trading/pull/57)). También refuerza `python -m backtest.validation <run_dir>` para que entradas faltantes, en blanco, malformadas, inexistentes y que no sean directorios fallen con mensajes claros orientados al operador antes de que comience la validación ([#60](https://github.com/HKUDS/Vibe-Trading/pull/60)).
- **2026-04-28** 🚀 **Se publica v0.1.6** (`pip install -U vibe-trading-ai`): corrige que `vibe-trading --swarm-presets` devolviera vacío después de `pip install` / `uv tool install` ([#55](https://github.com/HKUDS/Vibe-Trading/issues/55)) — los YAML de presets ahora están incluidos dentro del paquete `src.swarm` y fijados mediante una suite de regresión de 6 pruebas. Además, el cargador de AKShare ahora enruta correctamente ETFs (`510300.SH`) y forex (`USDCNH`) a los endpoints correctos con respaldo de registro reforzado. Recoge todo lo publicado desde v0.1.5: panel de comparación de benchmark, streaming de `/upload` + límites de tamaño, cargador Futu (HK + A-share), skill de exportación a vnpy, endurecimiento de seguridad, carga diferida del frontend (688KB → 262KB).
- **2026-04-27** 📊 **Panel de benchmark + seguridad de subida**: la salida del backtest ahora incluye un panel de comparación de benchmark (ticker / retorno del benchmark / retorno excedente / ratio de información) con resolución respaldada por yfinance para SPY, CSI 300, etc. ([#48](https://github.com/HKUDS/Vibe-Trading/issues/48)). Además, `/upload` transmite el cuerpo de la solicitud en fragmentos de 1 MB y aborta al superar `MAX_UPLOAD_SIZE`, acotando la memoria ante clientes sobredimensionados/malformados ([#53](https://github.com/HKUDS/Vibe-Trading/pull/53)) — fijado por una suite de regresión de 4 casos.
- **2026-04-22** 🛡️ **Endurecimiento + nuevas integraciones**: se aplicó contención de rutas en `safe_path` + sandbox de la herramienta de journal/shadow, `MANIFEST.in` incluye `.env.example` / pruebas / archivos de Docker en el sdist, la carga diferida a nivel de ruta reduce el paquete inicial del frontend de 688KB a 262KB. Además, cargador de datos Futu para acciones de HK y A-share ([#47](https://github.com/HKUDS/Vibe-Trading/pull/47)) y skill de exportación de `CtaTemplate` de vnpy ([#46](https://github.com/HKUDS/Vibe-Trading/pull/46)).
- **2026-04-21** 🛡️ **Espacio de trabajo + documentación**: `run_dir` relativo normalizado al directorio de ejecución activo ([#43](https://github.com/HKUDS/Vibe-Trading/pull/43)). Ejemplos de uso en el README ([#45](https://github.com/HKUDS/Vibe-Trading/pull/45)).
- **2026-04-20** 🔌 **Razonamiento + Swarm**: `reasoning_content` se preserva en todas las rutas de `ChatOpenAI` — Kimi / DeepSeek / Qwen funcionan de extremo a extremo con pensamiento ([#39](https://github.com/HKUDS/Vibe-Trading/issues/39)). Streaming de swarm + Ctrl+C limpio ([#42](https://github.com/HKUDS/Vibe-Trading/issues/42)).
- **2026-04-19** 📦 **v0.1.5**: publicado en PyPI y ClawHub. Actualización del piso de la CVE de `python-multipart`, 5 nuevas herramientas MCP conectadas (`analyze_trade_journal` + 4 herramientas de cuenta espejo), corrección del registro `pattern_recognition` → `pattern`, paridad de dependencias de Docker, manifiesto SKILL sincronizado (22 herramientas MCP / 71 skills).
- **2026-04-18** 👥 **Cuenta espejo**: extrae las reglas de tu estrategia desde un journal de broker → haz backtest de la cuenta espejo en distintos mercados → informe HTML/PDF de 8 secciones que muestra exactamente cuánto dejas sobre la mesa (violaciones de reglas, salidas anticipadas, señales perdidas, operaciones contrafactuales). 4 nuevas herramientas, 1 skill, 32 herramientas en total. Las muestras de Trade Journal + Shadow Account ya están en la pantalla de bienvenida de la web UI.
- **2026-04-17** 📊 **Analizador de journal de trading + lector universal de archivos**: sube exportaciones de broker (同花顺/东财/富途/CSV genérico) → perfil de trading automático (días de tenencia, tasa de aciertos, ratio de PnL, drawdown) + 4 diagnósticos de sesgo (efecto de disposición, sobreoperación, persecución del momentum, anclaje). `read_document` ahora despacha PDF, Word, Excel, PowerPoint, imágenes (OCR) y más de 40 formatos de texto detrás de una sola llamada unificada.
- **2026-04-16** 🧠 **Arnés del agente**: memoria persistente entre sesiones, búsqueda de sesiones con FTS5, skills autoevolutivas (CRUD completo), compresión de contexto en 5 capas, agrupamiento de herramientas de lectura/escritura. 27 herramientas, 107 pruebas nuevas.
- **2026-04-15** 🤖 **Z.ai + MiniMax**: proveedor Z.ai ([#35](https://github.com/HKUDS/Vibe-Trading/pull/35)), corrección de temperatura de MiniMax + actualización de modelo ([#33](https://github.com/HKUDS/Vibe-Trading/pull/33)). 13 proveedores.
- **2026-04-14** 🔧 **Estabilidad de MCP**: se corrigió el error `Connection closed` de la herramienta de backtest en el transporte stdio ([#32](https://github.com/HKUDS/Vibe-Trading/pull/32)).
- **2026-04-13** 🌐 **Backtest compuesto entre mercados**: el nuevo `CompositeEngine` hace backtest de portafolios de mercados mixtos (p. ej., A-shares + cripto) con un pool de capital compartido y reglas por mercado. También se corrigió el respaldo de variables de plantilla de swarm y un timeout del frontend.
- **2026-04-12** 🌍 **Exportación multiplataforma**: `/pine` exporta estrategias a TradingView (Pine Script v6), TDX (通达信/同花顺/东方财富) y MetaTrader 5 (MQL5) en un solo comando.
- **2026-04-11** 🛡️ **Fiabilidad y DX**: arranque de `.env` con `vibe-trading init` ([#19](https://github.com/HKUDS/Vibe-Trading/pull/19)), comprobaciones previas, respaldo de fuente de datos en runtime, motor de backtest reforzado. README multilenguaje ([#21](https://github.com/HKUDS/Vibe-Trading/pull/21)).
- **2026-04-10** 📦 **v0.1.4**: corrección de Docker ([#8](https://github.com/HKUDS/Vibe-Trading/issues/8)), herramienta MCP `web_search`, 12 proveedores de LLM, dependencias `akshare`/`ccxt`. Publicado en PyPI y ClawHub.
- **2026-04-09** 📊 **Backtest oleada 2**: motores ChinaFutures, GlobalFutures, Forex, Options v2. Monte Carlo, IC Bootstrap, validación Walk-Forward.
- **2026-04-08** 🔧 **Backtest multi-mercado** con reglas por mercado, exportación a Pine Script v6, 5 fuentes de datos con respaldo automático.

</details>

---

## ✨ Key Features

<div align="center">
<table align="center" width="94%" style="width:94%; margin-left:auto; margin-right:auto;">
  <tr>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-self-improving-trading-agent.png" height="130" alt="Self-improving trading agent"/><br>
      <h3>🔍 Agente de Trading Autoperfeccionable</h3>
      <div align="left">
        • Investigación de mercado en lenguaje natural<br>
        • Borradores de estrategias y análisis de archivos/web<br>
        • Flujos de trabajo respaldados por memoria
      </div>
    </td>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-multi-agent-trading-teams.png" height="130" alt="Multi-agent trading teams"/><br>
      <h3>🐝 Equipos de Trading Multiagente</h3>
      <div align="left">
        • Equipos de inversión, cuantitativo, cripto y riesgo<br>
        • Progreso en streaming e informes persistidos<br>
        • Workers fundamentados con datos de mercado obtenidos en tiempo real
      </div>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-cross-market-data-backtesting.png" height="130" alt="Cross-market data and backtesting"/><br>
      <h3>📊 Datos Multimercado y Backtesting</h3>
      <div align="left">
        • Acciones de A / HK / EE. UU. / Canadá / Reino Unido / India / Corea, cripto, futuros y forex<br>
        • Fallback de datos y backtests compuestos<br>
        • Datos PIT, validación y run cards
      </div>
    </td>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-shadow-account.png" height="130" alt="Shadow Account"/><br>
      <h3>👥 Shadow Account</h3>
      <div align="left">
        • Diagnóstico de comportamiento a partir del diario del broker<br>
        • Comparaciones de Shadow Account basadas en reglas<br>
        • Informes de auditoría exportables y código de estrategia
      </div>
    </td>
  </tr>
</table>
</div>

## 💡 What Is Vibe-Trading?

Vibe-Trading es un espacio de trabajo de investigación de código abierto para convertir preguntas financieras en análisis ejecutables. Conecta prompts en lenguaje natural con cargadores de datos de mercado, generación de estrategias, motores de backtest, informes, exportaciones y memoria de investigación persistente.

Está diseñado para investigación, simulación y backtesting, y, cuando tú lo decidas, para trading autónomo a través de un broker que autorices tú mismo (por ejemplo, Robinhood Agentic Trading). No retiene fondos y nunca opera fuera de los límites que establezcas, y puedes detenerlo al instante.

---

## ✨ What You Can Do

| Tarea | Resultado |
|------|--------|
| **Hacer una pregunta de trading** | Investigación de mercado con herramientas, datos, documentos y contexto de sesión reutilizable. |
| **Backtestear una idea de estrategia** | Código de estrategia, métricas, contexto de benchmark, artefactos de validación y run cards. |
| **Revisar tus propias operaciones** | Análisis del diario del broker, diagnóstico de comportamiento, extracción de reglas y comparaciones de Shadow Account. |
| **Leer documentos y gráficos** | Analiza PDF / DOCX / XLSX / PPTX / imágenes con OCR conectable (`read_document`), y lee capturas de gráficos de forma semántica con un modelo de visión (`analyze_image`). El chat web acepta hasta cinco archivos a la vez mediante el selector, arrastrar y soltar o pegar desde el portapapeles. |
| **Leer informes institucionales y libros de fondos** | Libros de gestores SEC 13F con diferencias de posiciones trimestre a trimestre, componentes de ETF en distintos mercados, probabilidad implícita de contratos de eventos y extracción de factores de arXiv / OpenAlex, todo de solo lectura, sobre fuentes públicas gratuitas. |
| **Mejorar la investigación repetida** | La memoria persistente y las skills editables convierten rutinas útiles en flujos de trabajo reutilizables. |
| **Ejecutar equipos de analistas** | Revisiones de investigación multiagente para flujos de trabajo de inversión, cuantitativo, cripto, macro y riesgo. |
| **Llevar la investigación a canales de mensajería** | Ejecuta el mismo runtime de sesión a través de WebSocket, Telegram, Slack, Discord, Matrix, WhatsApp, Signal, QQ/NapCat, WeChat/WeCom, Feishu/Lark, DingTalk, Teams, correo electrónico y Mochat, con controles de CLI, REST y Web UI. |
| **Entregar artefactos utilizables** | Informes, TradingView Pine Script, TDX, MetaTrader 5, herramientas MCP y sesiones de investigación posteriores. |
| **Evaluar un zoológico de alfas preconstruido** | Clasificación IC + viva/invertida/muerta en una línea, en 462 alfas (Qlib 158 + Kakushadze 101 + GTJA 191 + académicas + fundamentales PIT-safe) sobre tu universo. |
| **Detectar regímenes de correlación** | Una línea de tiempo de densidad de aristas + histéresis en la superficie `/correlation` que muestra cuándo los mercados se fusionan en un solo bloque: contexto de riesgo descriptivo, no una señal. |

---

## ⚡ Quick Example

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

## 👥 Shadow Account

Shadow Account parte de tus propios registros de trading en lugar de una plantilla de estrategia genérica.

Sube una exportación del broker, deja que el agente resuma tu comportamiento y luego compara tu trayectoria real de trading con una estrategia espejo basada en reglas.

| Paso | Resultado del agente |
|------|--------------|
| **1. Lee tu diario** | Analiza exportaciones de broker de 同花顺, 东方财富, 富途 y formatos CSV genéricos. |
| **2. Perfila tu comportamiento** | Días de tenencia, tasa de aciertos, ratio de PnL, drawdown, efecto disposición, sobreoperación, persecución de momentum y verificaciones de anclaje. |
| **3. Extrae tus reglas** | Convierte entradas/salidas recurrentes en un perfil de estrategia explícito en lugar de un resumen vago. |
| **4. Ejecuta la cuenta espejo** | Backtestea las reglas extraídas y resalta incumplimientos de reglas, salidas anticipadas, señales perdidas y trayectorias de operación alternativas. |
| **5. Entrega el informe** | Genera un informe HTML/PDF que puede inspeccionarse, archivarse o refinarse en una sesión posterior. |

```bash
vibe-trading --upload trades_export.csv
vibe-trading run -p "Analyze my trading behavior, extract my shadow strategy, and compare it with my actual trades"
```

---

## 💼 Cartera Local Multi-Broker

La Web UI añade una página **Cartera** de solo lectura que agrega las posiciones de las conexiones de broker que elijas. Las fuentes son instancias de conexión de perfiles de solo lectura que declaran `account.read` y `positions.read` — configúralas en **Conectores de Broker** dentro de [Detailed Capabilities](#-detailed-capabilities). El perfil MCP oficial de IBKR aún no puede usarse como fuente.

| Comportamiento | Qué obtienes |
|----------------|--------------|
| **Procedencia por fuente** | Cada posición indica de qué conexión proviene, valorada en USD con conversión a CNY. |
| **Fuentes fallidas excluidas** | Una fuente que falla se reporta como error y queda fuera de los totales — nunca se arrastra el valor anterior — y la instantánea se marca como incompleta. |
| **Instantáneas inmutables** | Cada actualización se guarda en `~/.vibe-trading/portfolio/portfolio.sqlite3`; los ajustes sin credenciales viven en `~/.vibe-trading/portfolio.json` y `connections.json`. |
| **Exportación y análisis** | Exportación CSV, más una herramienta de agente `portfolio_summary` saneada cuyos `risk_xray_args` se pasan directamente a `portfolio_risk_xray`. La misma instantánea se imprime en la terminal con `vibe-trading portfolio show` (también `refresh` / `sources`). |

Los conectores de solo lectura que instales tú permanecen fuera del checkout, en `~/.vibe-trading/connectors/<name>/`: un manifiesto `connector.json` más un `adapter.py` que implemente `check_status` / `get_account_snapshot` / `get_positions`. Un manifiesto que declare cualquier capacidad de escritura es rechazado.

```bash
vibe-trading connector init my-broker --destination /tmp
vibe-trading connector validate /tmp/my-broker
vibe-trading connector install /tmp/my-broker
```

Sus credenciales van al llavero del sistema operativo (macOS Keychain, Windows Credential Manager, Linux Secret Service) con `pip install "vibe-trading-ai[keyring]"`, nunca a los archivos de configuración. Nada en esta ruta puede enviar ni cancelar una orden.

---

## 🧪 Research Workflow

La mayoría de las ejecuciones siguen la misma ruta de evidencia: enrutar la solicitud, cargar el contexto de mercado correcto, ejecutar herramientas, validar resultados y mantener los artefactos inspeccionables.

| Capa | Qué sucede |
|-------|--------------|
| **Plan** | Selecciona las skills financieras, herramientas, fuentes de datos y el preset de swarm relevantes cuando resulta útil. |
| **Ground** | Extrae acciones A, acciones de HK/EE. UU./Canadá/Reino Unido, cripto, futuros, forex, documentos o contexto web a través de los cargadores disponibles. |
| **Execute** | Genera código de estrategia comprobable, ejecuta herramientas y utiliza el motor de backtest o el flujo de análisis correspondiente. |
| **Validate** | Añade métricas, comparación con benchmark, Monte Carlo, Bootstrap, Walk-Forward, run cards y advertencias cuando corresponde. |
| **Deliver** | Devuelve informes, artefactos, trazas de herramientas y exportaciones para TradingView, TDX, MetaTrader 5, clientes MCP o sesiones posteriores. |

---

## 📡 Fuentes de Datos y Fallback Inteligente

Una sola llamada `get_market_data`, **23 fuentes de datos de mercado gratuitas** (además del mercado premium opcional **QVeris**). Establece `source: "auto"`: el cargador elige según el símbolo y luego recorre una cadena por mercado ordenada por **riesgo de bloqueo de IP**: primero las fuentes públicas que nunca se bloquean, al final las limitadas o que requieren clave. Cero configuración, sin punto único de fallo.

| Fuente | Mercados | Autenticación | Rol |
|--------|---------|------|------|
| `tencent` · `mootdx` | A-share + HK | ninguna | nunca bloqueada por IP (`mootdx` = 通达信 TCP) |
| `eastmoney` | A / EE. UU. / HK | ninguna | OHLCV + herramientas de fundamentales y flujo profundas (limitada) |
| `baostock` · `akshare` | A (+ EE. UU./HK/futuros/macro/fx) | ninguna | fallbacks gratuitos |
| `tushare` | A / HK / futuros / fondos / macro | token | la más completa para A-share |
| `yahoo` | EE. UU. / HK / Canadá / Reino Unido | ninguna | gráfico/cotizaciones/opciones directos; TSX `.TO` / TSXV `.V`; LSE `.L` con normalización según la divisa declarada |
| `sina` · `stooq` | EE. UU. | ninguna | velas hasta 1984 · CSV EOD |
| `yfinance` | EE. UU. / HK / Canadá / Reino Unido | ninguna | wrapper; TSX `.TO` / TSXV `.V`; LSE `.L` bajo el mismo contrato GBP/GBp |
| `longbridge` | EE. UU. / HK | App Key + App Secret + Access Token | fuente OHLCV histórica opcional; instala el SDK opcional |
| `finnhub` · `alphavantage` · `tiingo` · `fmp` | EE. UU. | clave | proveedores opcionales |
| `qveris` | multiactivo global | clave · créditos | **mercado premium** — 63+ proveedores mediante una sola clave (solo explícito, nunca en el fallback automático) |
| `okx` · `ccxt` · `binance` | cripto | ninguna | OKX + 100+ exchanges + históricos de Binance / perpetuos USD-M |
| `futu` | HK / A | OpenD | FutuOpenD local opcional |
| `mt5` | forex / metales | terminal MT5 | barras de forex/metales de MetaTrader 5 (estilo Exness), 1m–1D |
| `pykrx` | Corea (KRX: KOSPI/KOSDAQ) | ninguna | barras diarias de KOSPI / KOSDAQ para `.KS` / `.KQ` (extra opcional `krx`) |
| `india_broker` | India (NSE/BSE) | login de broker | barras de solo lectura de Zerodha / Shoonya / Dhan para `.NS` / `.BO` (al final de la cadena de fallback) |
| `local` | cualquiera | ninguna | tu propio CSV / Parquet / DuckDB mediante el prefijo `local:` |

**Cadenas de fallback (por riesgo de bloqueo de IP):**

- **A-share** → `tencent` · `mootdx` · `eastmoney` · `baostock` · `akshare` · `tushare` · `local`
- **EE. UU.** → `yahoo` · `stooq` · `sina` · `eastmoney` · `yfinance` · `tiingo` · `fmp` · `finnhub` · `alphavantage` · `longbridge` · `akshare` · `local`
- **HK** → `tencent` · `eastmoney` · `yahoo` · `futu` · `akshare` · `yfinance` · `tushare` · `longbridge` · `local`
- **India (NSE/BSE)** → `yahoo` · `yfinance` · `india_broker` · `local`
- **Corea (KOSPI/KOSDAQ)** → `pykrx` · `yahoo` · `yfinance` · `local`
- **Reino Unido (LSE)** → `yahoo` · `yfinance` · `local` *(solo cotizaciones declaradas en GBP/GBp)*
- **Cripto** → `okx` · `ccxt` · `binance` · `yfinance` · `local`
- **Forex / metales** → `mt5` · `yfinance` · `akshare` · `local` &nbsp;·&nbsp; *(futuros / fondos / macro → `tushare`/`akshare` → `local`)*

### Uso explícito de Longbridge

Longbridge es un cargador histórico OHLCV opcional para EE. UU./HK. Instala su SDK con:

```bash
pip install "vibe-trading-ai[longbridge]"
```

Configura las tres credenciales en `.env`:

```dotenv
LONGBRIDGE_APP_KEY=...
LONGBRIDGE_APP_SECRET=...
LONGBRIDGE_ACCESS_TOKEN=...
```

Para un backtest, establece `source` en `config.json`:

```json
{
  "codes": ["QQQ.US"],
  "start_date": "2025-01-01",
  "end_date": "2025-01-10",
  "interval": "1D",
  "source": "longbridge"
}
```

En una conversación con el Agent, pide explícitamente: **"Use Longbridge to fetch QQQ.US historical data."** La solicitud explícita de fuente es independiente de `source: "auto"`; `auto` mantiene la cadena de fallback normal por mercado.

Más allá del OHLCV, **22 herramientas de datos de solo lectura** alcanzan fundamentales y flujo: flujo de fondos, dragon-tiger, northbound, margen, operaciones en bloque, número de accionistas, lockup, sector, informes de investigación, noticias, presentaciones ante la SEC, estados financieros, cadenas de opciones, perfil de la acción, screening de mercado, búsqueda de símbolos, macro, iwencai, tenencias institucionales (13F), look-through de ETF, mercados de predicción y papers de investigación, todo expuesto a través de MCP. Un símbolo `local:` explícito nunca recurre en silencio a una fuente de red.

<!-- QVERIS-START -->
### 💎 Datos premium opcionales — QVeris

<img src="https://www.qveris.com/logo-color.png" alt="QVeris" height="36">

**Datos: enrutamiento gratuito o premium, tú decides.** Lo gratuito sigue siendo el valor por defecto: 23 fuentes integradas con fallback por riesgo de bloqueo, sin clave, sin costo. Lo premium mediante QVeris añade más de 10.000 capacidades (según QVeris) en 63+ proveedores para Greeks de opciones, fundamentales premium, datos de China/HK/globales, macro, cripto, noticias y presentaciones regulatorias; las llamadas fallidas no se cobran. Actívalo en Settings -> QVeris o con `vibe-trading data mode paid`.

*Aviso de QVeris: [registrarte a través del enlace de referido de Vibe-Trading](https://qveris.ai/?ref=Vyjjo5G_1cAHJA) te da **+1.000 créditos de bonificación** y apoya el proyecto.*
<!-- QVERIS-END -->

---

## 🔩 Detailed Capabilities

Los inventarios detallados se pliegan a continuación para mantener el README principal fácil de escanear. Ábrelos cuando quieras inspeccionar los bloques de construcción disponibles.

<details>
<summary><b>Biblioteca de Skills Financieras</b> <sub>90 skills en 9 categorías</sub></summary>

- 📊 90 skills financieras especializadas organizadas en 9 categorías
- 🌐 Cobertura completa desde mercados tradicionales hasta cripto y DeFi
- 🔬 Capacidades integrales que abarcan desde el sourcing de datos hasta la investigación cuantitativa

| Categoría | Skills | Ejemplos |
|----------|--------|----------|
| Fuente de Datos | 10 | `data-routing`, `tushare`, `yfinance`, `okx-market`, `akshare`, `mootdx`, `ccxt`, `eastmoney`, `sec-edgar`, `qveris` |
| Estrategia | 19 | `strategy-generate`, `cross-market-strategy`, `technical-basic`, `candlestick`, `ichimoku`, `elliott-wave`, `smc`, `multi-factor`, `ml-strategy` |
| Análisis | 23 | `factor-research`, `correlation-regime`, `macro-analysis`, `global-macro`, `valuation-model`, `investor-lenses`, `credit-analysis`, `dividend-analysis` |
| Clase de Activo | 9 | `options-strategy`, `options-advanced`, `convertible-bond`, `etf-analysis`, `asset-allocation`, `sector-rotation` |
| Cripto | 7 | `perp-funding-basis`, `liquidation-heatmap`, `stablecoin-flow`, `defi-yield`, `onchain-analysis` |
| Flujo | 8 | `hk-connect-flow`, `us-etf-flow`, `edgar-sec-filings`, `financial-statement`, `adr-hshare` |
| Herramienta | 10 | `backtest-diagnose`, `report-generate`, `pine-script`, `doc-reader`, `web-reader`, `vnpy-export`, `trade-journal` |
| Investigación | 2 | `alpha-zoo`, `strategy-dev-manager` |
| Análisis de Riesgo | 1 | `ashare-pre-st-filter` |

</details>

<details>
<summary><b>Fuente de Datos Personalizada</b> <sub>registra tu propio loader histórico de OHLCV</sub></summary>

¿Necesitas un mercado o proveedor para el que no incluimos un loader? Añade tu
propio loader de barras históricas y selecciónalo con `source="<name>"`. Los
pasos modifican el código fuente del paquete, así que ejecútalos desde un
clon (`pip install -e .`).

1. **Escribe el loader** — crea `agent/backtest/loaders/<name>_loader.py` con una
   clase que satisfaga `DataLoaderProtocol` (duck-typed, sin necesidad de clase
   base) y esté etiquetada con `@register`:

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

2. **Registra el módulo** para que `@register` se active — añade
   `"backtest.loaders.<name>_loader"` a `_loader_modules` en
   `agent/backtest/loaders/registry.py`.
3. **Habilita el nombre** en la validación de configuración — añade `"mysource"`
   a `_VALID_SOURCES` en `agent/backtest/runner.py`.
4. *(Opcional)* insértalo en el `FALLBACK_CHAINS` de un mercado en `registry.py`
   para que `source="auto"` pueda alcanzarlo.
5. **Úsalo** — `source="mysource"` en una configuración de backtest, o vía la
   CLI / el agente.

> **Los ticks en tiempo real / la profundidad del libro de órdenes quedan fuera
> del alcance de los loaders** — la capa de loaders es solo barras históricas
> point-in-time. Los datos de mercado en vivo fluyen a través de los conectores
> de broker en su lugar: `okx` / `binance` / `ccxt` para cripto,
> `futu` / `tiger` para acciones.

</details>

<details>
<summary><b>Conectores de Broker</b> <sub>14 brokers — lectura + paper, live acotado donde esté soportado</sub></summary>

Perfiles centrados en el conector. La mayoría hace lectura + colocación de órdenes en cuenta paper — IBKR es de solo lectura, Robinhood es solo live (sin cuenta paper), y Trading 212 rechaza la colocación de órdenes por completo, incluido el paper; la colocación de órdenes live está acotada por un mandato definido por el usuario (lista blanca de símbolos, límites de tamaño de orden / exposición, límite diario de operaciones, interruptor de apagado instantáneo) y nunca retiene fondos — el broker ejecuta. Las herramientas de colocación de órdenes se mantienen fuera de MCP (solo agente + CLI). Las rutas de investigación / backtest están estructuralmente vetadas de cualquier endpoint live.

| Broker | Mercados | Capacidades |
|--------|---------|--------------|
| **IBKR** | global | TWS / Gateway local, solo lectura |
| **Robinhood** | EE. UU. | MCP agéntico (OAuth de escritorio) — lectura + live acotado |
| **Tiger** | EE. UU. / HK / A | lectura + paper + live acotado |
| **Alpaca** | EE. UU. | lectura + paper + live acotado (+ modo TAP de aislamiento de credenciales) |
| **OKX** · **Binance** | cripto | lectura + paper + live acotado |
| **Futu** | HK / EE. UU. / A | lectura + paper + live acotado |
| **eToro** | global | lectura + paper + live acotado (API pública; las claves demo solo alcanzan rutas `/demo`, además de flujos de copy-trading) |
| **MetaTrader 5** | forex / CFD | lectura + paper + live acotado (estilo Exness; guardia de identidad demo ⇔ paper) |
| **Longbridge** · **Dhan** · **Shoonya** · **Zerodha** | EE. UU. / HK · India (NSE/BSE) | solo lectura + paper — sin discriminador de runtime paper/live, por lo que la colocación de órdenes live se rechaza de forma estricta |
| **Trading 212** | Reino Unido / UE | completamente de solo lectura — `place_order` / `cancel_order` se rechazan de forma estricta incluso en paper |

Paper-vs-live es una **guardia de runtime estructural por broker** (formato de id de cuenta, separación de host, flag demo, o entorno de trading), nunca un flag de configuración que el agente pueda cambiar. Un broker que no exponga tal discriminador queda limitado a paper + solo lectura.

</details>

<details>
<summary><b>Equipos de Trading Preconfigurados</b> <sub>30 presets de swarm</sub></summary>

- 🏢 30 equipos de agentes listos para usar
- ⚡ Flujos de trabajo financieros preconfigurados
- 🎯 Presets de inversión, trading y gestión de riesgo

| Preset | Flujo de trabajo |
|--------|----------|
| `investment_committee` | Debate alcista/bajista → revisión de riesgo → decisión final del PM |
| `global_equities_desk` | Investigador de A-share + HK/US + cripto → estratega global |
| `crypto_trading_desk` | Funding/basis + liquidaciones + flujo → gestor de riesgo |
| `earnings_research_desk` | Fundamental + revisión + opciones → estratega de resultados |
| `macro_rates_fx_desk` | Tasas + FX + materias primas → PM macro |
| `quant_strategy_desk` | Screening + investigación de factores → backtest → auditoría de riesgo |
| `technical_analysis_panel` | TA clásico + Ichimoku + armónicos + Elliott + SMC → consenso |
| `risk_committee` | Drawdown + riesgo de cola + revisión de régimen → aprobación final |
| `global_allocation_committee` | A-shares + cripto + HK/US → asignación cross-market |

<sub>Además de más de 20 presets especializados adicionales — ejecuta vibe-trading --swarm-presets para explorarlos todos.
Trae los tuyos: coloca los YAML de preset en <code>~/.vibe-trading/swarm/presets/</code> — se listan
junto al catálogo incluido (los archivos con el mismo nombre lo sobrescriben, igual que los skills de usuario) y sobreviven a las actualizaciones.

</sub>

</details>

<details>
<summary><b>Alpha Zoo</b> <sub>462 alphas cuantitativos preconstruidos en 5 familias</sub></summary>

- 🧬 462 alphas cross-sectional, con prohibición de lookahead a nivel de la capa de operadores
- 📈 Categorización de IC + IR + vivo/invertido/muerto en un solo comando de la CLI
- 🔬 Puerta de pureza AST + test centinela de lookahead de 300 filas + interruptor de apagado de red `pytest-socket`
- 📦 Atribución Apache-2 para Qlib; `LICENSE.md` por zoo que declara las fórmulas como contenido matemático
- 🤝 Flujo de firma Developer Certificate of Origin (DCO) para PRs de la comunidad

| Zoo | Cantidad | Fuente | Licencia |
|-----|-------|--------|---------|
| **qlib158** | 154 | Microsoft Qlib `Alpha158` (Apache-2.0, fijado a un commit) | Apache-2.0 |
| **alpha101** | 101 | Kakushadze (2015), "101 Formulaic Alphas", arXiv:1601.00991 | Las fórmulas son contenido matemático |
| **gtja191** | 191 | Guotai Junan (2014), "191 Short-period Trading Alpha Factors" | Las fórmulas son contenido matemático |
| **academic** | 12 | Fama-French 5 + momentum de Carhart + reversión de Jegadeesh + máximo de 52 semanas de George-Hwang + iliquidez de Amihud + skew de Harvey-Siddique + betting-against-beta de Frazzini-Pedersen + estabilidad por recableado de correlación (proxies basados en precio) | Literatura académica pública |
| **fundamental** | 4 | Datos de company facts de la SEC seguros PIT — earnings yield, ROE, rentabilidad bruta, crecimiento de activos (anclados a la fecha de presentación) | Datos financieros públicos |

Ejecuta `vibe-trading alpha list` para explorar, `vibe-trading alpha show <id>` para ver fórmulas + fuente, `vibe-trading alpha bench --zoo X --universe Y --period Z` para puntuar un zoo completo, y `vibe-trading alpha compare --all` para clasificar zoos entre sí.

</details>

<details>
<summary><b>Motores de Backtest</b> <sub>10 motores + cartera de opciones, composite cross-market</sub></summary>

| Motor | Mercado | Notas |
|--------|--------|-------|
| **ChinaA** | A-share | T+1, límites de precio, filtro pre-ST |
| **GlobalEquity** | EE. UU. / HK / Canadá / Reino Unido | trading en la misma sesión; lotes, ticks, divisas de liquidación y costos específicos de cada mercado |
| **IndiaEquity** | India (NSE/BSE) | T+1, bandas de circuito, pila de costos STT / stamp / SEBI / GST basada en configuración |
| **KoreaEquity** | Corea (KRX: KOSPI/KOSDAQ) | solo largo, banda de ±30% evaluada en el momento de ejecución sobre la malla de ticks unificada, impuesto de transacción del 0.20% en 2026 |
| **Crypto** | spot cripto / perps USD-M | liquidaciones de funding, división ejecución/mark |
| **ChinaFutures** · **GlobalFutures** | futuros | margen, multiplicadores de contrato |
| **Forex** | FX / metales | vía el loader `mt5` |
| **Composite** | cross-market | un único pool de capital compartido entre mercados (`source="auto"`) |
| **options_portfolio** | opciones | multi-leg, greeks, payoff/escenario |

Barras intradía: 1m / 5m / 15m / 30m / 1H / 4H / 1D. 15 métricas + comparación con benchmark, **5 optimizadores de cartera** (volatilidad-igual / risk-parity / media-varianza / máxima diversificación / con conciencia de turnover), y 3 herramientas de validación (Monte Carlo / Bootstrap / Walk-Forward).

</details>

<details>
<summary><b>Quant Library</b> <sub>306 funciones probadas en 23 módulos, invocables desde cualquier transporte</sub></summary>

`src/quantlib` contiene una implementación probada de cada pieza de matemática
financiera que el agente necesita. Las skills **importan** estas funciones en
lugar de llevar fórmulas dentro de bloques de código markdown — si encuentras
una fórmula de pricing viviendo en un `SKILL.md`, eso es un bug, no un patrón.

| Módulo | Qué cubre |
|--------|----------------|
| `options` | Precio Black-Scholes + greeks, inversión de volatilidad implícita |
| `fixedincome` | Matemática de bonos, ajuste de curva Nelson-Siegel / Svensson |
| `credit` | Z-score de Altman, distancia al default Merton / KMV |
| `timeseries` | Estacionariedad, cointegración, GARCH, bootstrap |
| `risk` · `var_backtest` | VaR / CVaR / EVT y sus backtests |
| `attribution` | Descomposición de Brinson-Fachler |
| `performance` · `fundmath` | TWR / MWR / Dietz modificado; XIRR / MOIC / DPI / TVPI |
| `factormodel` · `eventstudy` | Regresiones de factores, estudios de eventos |
| `multipletesting` · `crossvalidation` | Significancia deflacionada, CV purgada |
| `impact` | Modelos de impacto de mercado |
| `volatility` | Valoración con volatilidad estocástica de Heston (1993) |
| `portfolio` | Asignación por Paridad de Riesgo Jerárquica (HRP) |
| `copula` | Cópulas gaussianas y arquimedianas |
| `microstructure` | VPIN, spread de Roll, iliquidez de Amihud, lambda de Kyle |

La herramienta de solo lectura `quantlib_call` da acceso a todo esto mediante un
único contrato, de modo que la matemática financiera funciona en la CLI, la Web
UI, la API REST y MCP — incluidos despliegues donde `bash` está bloqueado. Es
estructuralmente no un shell — allowlist de módulos, despacho solo mediante
`__all__`, `export_*` rechazado. La econometría necesita el extra `stats`
(`pip install "vibe-trading-ai[stats]"`); esas funciones hacen lazy-import y te
indican cuál falta.

</details>

<details>
<summary><b>Valoración e Investigación Institucional</b> <sub>DCF, comparables, three-statement, y seis comandos de investigación</sub></summary>

Un motor de valoración que se niega a inventar sus propios inputs. La única
regla en `contracts.py`: **un input faltante hace que un modelo sea NOT
RUNNABLE y nunca se le asigna un valor por defecto de forma silenciosa** — cada
valor por defecto en un modelo de valoración es una opinión disfrazada de
constante.

| Modelo | Comportamiento que vale la pena conocer |
|-------|-------------------------|
| `run_dcf` | Puente FCFF, construcción de WACC, descuento a mitad de año, puente de deuda neta, grilla de sensibilidad WACC×g. Valor terminal dual: cada método se contrasta contra el múltiplo implícito y la g implícita del otro |
| `run_comps` | Puente de EV, calendarización LTM + año calendario, matriz de múltiplos. Un peer con un denominador no positivo se **excluye y se reporta**, nunca se promedia como un múltiplo negativo |
| `threestatement` | Proyección enlazada con una aserción de balance estricta, un plug explícito de revolver, y una circularidad iterada interés↔deuda que debe converger o lanzar un error |

Los artefactos están hasheados por input y versionados, con exportación a xlsx / pptx.

Seis slash commands impulsan los flujos de trabajo — `/comps` `/dcf` `/attrib`
`/memo` `/earnings` `/screen` — cada uno con un esqueleto de pasos y un ejemplo
resuelto aritméticamente consistente (la descomposición de Brinson suma
exactamente al retorno activo; el puente de resultados suma exactamente a la
variación del EPS). La skill `investor-lenses` apila marcos de razonamiento de
inversores reconocidos por encima como capas de análisis: cada lente es un
procedimiento operativo — señales prioritarias, condiciones descalificantes,
mal uso típico — no una biografía, y no nombra ninguna herramienta.

Más allá de las barras, `src/entities` ingiere flujos de caja con fechas
irregulares (NAVs, capital calls, cupones) y `cashflow_performance` reporta
XIRR / MOIC / DPI / TVPI / TWR / Dietz modificado / MWR sobre ellos. Esta ruta
es deliberadamente paralela a los motores de barras para que una columna `nav`
nunca pueda llegar a uno de ellos y ser valorada como un cierre.

</details>

<details>
<summary><b>Gobernanza y Registro de Auditoría</b> <sub>responder "¿qué metodología produjo ese número?"</sub></summary>

Cada ejecución escribe un **manifiesto** que hashea el prompt, el contenido de
la skill, el registro de herramientas y las versiones del paquete, de modo que
un número producido el mes pasado pueda rastrearse hasta la metodología exacta
que lo produjo.

El **ledger de auditoría** encadena cada registro al hash de su predecesor y
hace fsync, de modo que editar o eliminar un registro es detectable — e incluso
una edición que recalcula su propio hash queda igualmente atrapada un registro
más adelante vía `prev_hash_mismatch`. Las marcas de tiempo siempre son
proporcionadas por el llamador; ningún módulo aquí llama a `datetime.now()`.

La redacción de trazas es **consciente del sink**: los argumentos de las
llamadas a herramientas y el ledger de auditoría en vivo usan un sink de fallo
cerrado donde `content` permanece redactado, mientras que el sink de resultado
de herramienta lo libera y depura por patrones sus hojas de string. `env`
nunca se libera en ninguno de los dos.

</details>

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
<td colspan="2" align="center"><sub>☝️ Backtest en lenguaje natural y debate de swarm multiagente — Web UI + CLI</sub></td>
</tr>
</table>
</div>

---

## 🚀 Quick Start

### Instalación en una línea (PyPI)

```bash
pip install vibe-trading-ai
```

Luego ejecuta una primera tarea de investigación:

```bash
vibe-trading init
vibe-trading run -p "Backtest a BTC-USDT 20/50 moving-average strategy for 2024 and summarize return and drawdown"
```

> **¿Actualizando desde una versión anterior?** La 0.1.10 pasó a LangChain 1.x. Si las importaciones fallan después de ejecutar `pip install -U vibe-trading-ai` sobre una instalación anterior a la 0.1.10 (por ejemplo, si langgraph no se puede importar), recrea el venv o ejecuta `pip install --force-reinstall vibe-trading-ai`. Una instalación nueva no se ve afectada.

> **Nombre del paquete frente a los comandos:** El paquete de PyPI es `vibe-trading-ai`. Una vez instalado, obtienes tres comandos:
>
> | Comando | Propósito |
> |---------|-----------|
> | `vibe-trading` | CLI / TUI interactivo |
> | `vibe-trading serve` | Inicia el servidor web FastAPI |
> | `vibe-trading-mcp` | Inicia el servidor MCP (para Claude Desktop, OpenClaw, Cursor, etc.) |

```bash
vibe-trading init              # configuración interactiva de .env
vibe-trading                   # inicia la CLI
vibe-trading serve --port 8899 # inicia la interfaz web
vibe-trading-mcp               # inicia el servidor MCP (stdio)
```

### O elige una ruta

| Ruta | Ideal para | Tiempo |
|------|----------|------|
| **A. Docker** | Pruébalo ya, sin configuración local | 2 min |
| **B. Local install** | Desarrollo, acceso completo a la CLI | 5 min |
| **C. MCP plugin** | Conéctalo a tu agente existente | 3 min |
| **D. ClawHub** | Un solo comando, sin clonar | 1 min |

### Requisitos previos

- Una **clave de API de LLM** de cualquier proveedor compatible, o ejecútalo localmente con **Ollama** (no necesita clave)
- **Python 3.11+** para el Path B
- **Docker** para el Path A
- OpenAI Codex también se puede usar con ChatGPT OAuth: configura `LANGCHAIN_PROVIDER=openai-codex` y luego ejecuta `vibe-trading provider login openai-codex`. Esto no usa `OPENAI_API_KEY`.

> **Proveedores de LLM compatibles:** OpenRouter, Requesty, OpenAI, Anthropic (API de Messages nativa), DeepSeek, Gemini, Groq, DashScope/Qwen, Zhipu, Moonshot/Kimi, MiniMax, SiliconFlow (CN + Global), Xiaomi MIMO, Novita AI, iFlytek Spark, Z.ai, NVIDIA NIM, ModelScope, GitHub Copilot, Ollama (local). Cuando no se configura ningún `*_BASE_URL`, cada proveedor recurre a su endpoint canónico, así que basta con una clave. Consulta `.env.example` para la configuración.

> **Consejo:** Todos los mercados funcionan sin ninguna clave de API gracias al fallback automático. yfinance/Yahoo (HK/US/Canadá/Reino Unido), OKX (cripto), mootdx (acciones A, conexión TCP directa, sin limitación de IP) y AKShare (acciones A, EE. UU., HK, futuros, forex) son gratuitos. Las cotizaciones LSE `.L` deben declarar GBP o GBp para normalizar los peniques antes de la contabilidad en GBP. El token de Tushare es opcional — mootdx es el fallback preferido sin token para acciones A, con AKShare como respaldo más amplio.

### Ruta A: Docker (configuración cero)

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
cp agent/.env.example agent/.env
# Edit agent/.env — uncomment your LLM provider and set API key
docker compose up --build
```

Abre `http://localhost:8899`. Backend + frontend en un mismo contenedor.

> [!NOTE]
> **OAuth de OpenAI Codex con Docker:** el inicio de sesión en el navegador necesita una terminal para
> que puedas pegar la URL de callback. Ejecútalo a través de Compose, que asigna
> automáticamente una terminal interactiva:
>
> ```bash
> docker compose exec vibe-trading vibe-trading provider login openai-codex
> ```
>
> Si usas `docker exec` directamente, pasa `-it` antes del nombre del contenedor.

Docker publica el backend en `127.0.0.1:8899` de forma predeterminada y ejecuta la aplicación como un usuario de contenedor no root. Si expones la API intencionalmente más allá de tu propia máquina, configura un `API_AUTH_KEY` fuerte y envía `Authorization: Bearer <key>` desde los clientes.

> [!NOTE]
> **Uso de Ollama con Docker:** el contenedor accede a un Ollama alojado en el host mediante `host.docker.internal`, no `localhost` (dentro del contenedor, `localhost` es el propio contenedor). `docker-compose.yml` establece `OLLAMA_BASE_URL` en `http://host.docker.internal:11434` por defecto; exporta `OLLAMA_BASE_URL` (o configúralo en un `.env` de nivel superior) para apuntar a otro lugar. Esto depende del mapeo `host-gateway` en `extra_hosts`, que requiere **Docker Engine ≥ 20.10 / Compose v2** (disponible automáticamente en Docker Desktop).

Tus datos sobreviven a las actualizaciones: la memoria persistente, el índice de búsqueda entre sesiones, las skills creadas por el usuario, las cuentas shadow, la configuración de conectores de broker, las sesiones web, las ejecuciones de backtest, el historial de swarm y los archivos subidos residen todos en volúmenes de Docker con nombre, así que `git pull && docker compose up --build` los conserva. Las respuestas web en curso también se guardan como checkpoints, de modo que un reinicio restaura la respuesta parcial y marca el intento como interrumpido en lugar de descartarla en silencio. Los datos solo se eliminan con `docker compose down -v`.

### Ruta B: Instalación local

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
> **En Windows:** `cp` es un alias de PowerShell para `Copy-Item`, así que los fragmentos anteriores funcionan tal cual en PowerShell. CMD no tiene `cp` — usa en su lugar `copy agent\.env.example agent\.env` (esto también aplica al fragmento de Docker anterior). Si PowerShell se niega a ejecutar `Activate.ps1`, ejecuta primero `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`; esto se aplica solo a esa sesión de shell.

<details>
<summary><b>Iniciar la interfaz web (opcional)</b></summary>

```bash
# Terminal 1: API server
vibe-trading serve --port 8899

# Terminal 2: Frontend dev server
cd frontend && npm install && npm run dev  # requiere Node >= 22.22
```

Abre `http://localhost:5899`. El frontend envía las llamadas a la API mediante proxy a `localhost:8899`.

**Modo de producción (un solo servidor):**

```bash
cd frontend && npm run build && cd ..
vibe-trading serve --port 8899     # FastAPI serves dist/ as static files
```

> [!NOTE]
> `vibe-trading serve` se vincula a `0.0.0.0` pero, de forma predeterminada, solo confía en loopback: abrir la interfaz en la **misma máquina** (`http://localhost:8899`) funciona sin ninguna configuración. Si navegas desde **otra máquina, un host de VM o un teléfono en tu LAN**, los endpoints sensibles devuelven `403` y el chat muestra "Remote API access requires an API key" — configura un `API_AUTH_KEY` fuerte en `agent/.env`, reinicia, e introduce la misma clave una vez en **Settings**. (Puerta de enlace de host de Docker Desktop: configura `VIBE_TRADING_TRUST_DOCKER_LOOPBACK=1` manteniendo el enlace de puerto predeterminado `127.0.0.1`.)

</details>

### Ruta C: Plugin MCP

Consulta la sección [MCP Plugin](#-mcp-plugin) más abajo.

### Ruta D: ClawHub (un comando)

```bash
npx clawhub@latest install vibe-trading --force
```

El skill + configuración MCP se descarga en el directorio de skills de tu agente. Consulta [ClawHub install](#-mcp-plugin) para más detalles.

---

## 🧠 Environment Variables

Copia `agent/.env.example` a `agent/.env` y descomenta el bloque del proveedor que quieras usar. Cada proveedor necesita entre 3 y 4 variables:

| Variable | Obligatoria | Descripción |
|----------|:--------:|-------------|
| `LANGCHAIN_PROVIDER` | Sí | Nombre del proveedor (`openrouter`, `deepseek`, `groq`, `ollama`, etc.) |
| `<PROVIDER>_API_KEY` | Sí* | Clave de API (`OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, etc.) |
| `<PROVIDER>_BASE_URL` | Sí | URL del endpoint de la API |
| `LANGCHAIN_MODEL_NAME` | Sí | Nombre del modelo (p. ej., `deepseek-v4-pro`) |
| `TUSHARE_TOKEN` | No | Token de Tushare Pro para datos de acciones A (recurre a AKShare como fallback) |
| `TIMEOUT_SECONDS` | No | Tiempo de espera para llamadas al LLM, 120 s por defecto |
| `API_AUTH_KEY` | Recomendado para despliegues en red | Token Bearer requerido cuando la API es accesible desde clientes no locales |
| `VIBE_TRADING_ENABLE_SHELL_TOOLS` | No | Activación explícita de herramientas con capacidad de shell en despliegues tipo API remota/MCP-SSE |
| `VIBE_TRADING_ALLOWED_FILE_ROOTS` | No | Rutas raíz adicionales, separadas por comas, para la importación de documentos y diarios de broker |
| `VIBE_TRADING_ALLOWED_RUN_ROOTS` | No | Rutas raíz adicionales, separadas por comas, para directorios de ejecución de código generado |
| `VIBE_TW_STOCK_DB` | No | Ruta a una instantánea SQLite del mercado taiwanés; la herramienta de solo lectura `taiwan_stock_data` solo se registra cuando el esquema es válido |
| `VIBE_TRADING_EXTRA_CORS_ORIGINS` | No | Orígenes separados por comas que se **añaden** a los valores predeterminados de CORS de loopback (`CORS_ORIGINS` los reemplaza en cambio) |
| `CONTENT_FILTER_WARNING_THRESHOLD` | No | Umbral de proporción de aviso del filtro de contenido (por defecto 0.05 = 5%). Cuando la proporción de respuestas del LLM bloqueadas por moderación de contenido supera este valor, la run card te avisa para que cambies de proveedor. |

<sub>* Ollama no requiere clave de API. OpenAI Codex usa ChatGPT OAuth y almacena los tokens mediante `oauth-cli-kit`, no en `agent/.env`.</sub>

**Datos gratuitos (sin necesidad de clave):** acciones A mediante AKShare, acciones de HK/EE. UU./Canadá/Reino Unido mediante Yahoo/yfinance, cripto mediante OKX, más de 100 exchanges de cripto mediante CCXT. El sistema selecciona automáticamente la mejor fuente disponible para cada mercado.

### 🎯 Recommended Models

Vibe-Trading es un agente que depende intensamente de herramientas: skills, backtests, memoria y swarms fluyen todos a través de llamadas a herramientas. La elección del modelo determina directamente si el agente *usa* sus herramientas o fabrica respuestas a partir de datos de entrenamiento.

| Nivel | Ejemplos | Cuándo usarlo |
|------|----------|-------------|
| **Best** | `anthropic/claude-opus-4.7`, `anthropic/claude-sonnet-4.6`, `openai/gpt-5.5-pro`, `google/gemini-3.5-flash` | Swarms complejos (3+ agentes), sesiones de investigación largas, análisis de calidad de paper |
| **Sweet spot** (predeterminado) | `deepseek-v4-pro`, `deepseek/deepseek-v4-pro`, `x-ai/grok-4.20`, `z-ai/glm-5.1`, `moonshotai/kimi-k2.6`, `qwen/qwen3-max-thinking` | Opción diaria — llamadas a herramientas confiables a ~1/10 del costo |
| **Evitar para uso en agentes** | `*-nano`, `*-flash-lite`, `*-coder-next`, variantes pequeñas / destiladas | Las llamadas a herramientas son poco confiables — el agente parecerá "responder de memoria" en lugar de cargar skills o ejecutar backtests |

El `agent/.env.example` predeterminado viene configurado con la API oficial de DeepSeek + `deepseek-v4-pro`; los usuarios de OpenRouter pueden usar `deepseek/deepseek-v4-pro`.

---

## 🖥 CLI Reference

La TUI interactiva (`vibe-trading`) ahora usa una transcripción nativa de terminal: un banner de inicio, una regla de prompt, un resumen del turno anterior, una barra de actividad en vivo, el renderizado de Markdown/tablas y el tiempo de ejecución, todo permanece en la CLI. Las invocaciones no interactivas como `vibe-trading run`, los pipes y `--json` siguen siendo adecuadas para scripts.

```bash
vibe-trading               # interactive TUI
vibe-trading run -p "..."  # single run
vibe-trading serve         # API server
vibe-trading alpha list    # explora 462 alphas preconstruidos; subcomandos show / bench / compare / export-manifest disponibles
vibe-trading playbook list # cinco plantillas de investigación programada; subcomandos show / create disponibles
vibe-trading channels status --local  # inspecciona la configuración de canales IM y sugerencias de instalación
vibe-trading provider doctor  # imprime diagnósticos redactados de provider/proxy/paquetes
```

<details>
<summary><b>Comandos slash dentro de la TUI</b></summary>

| Comando | Descripción |
|---------|-------------|
| `/help` | Muestra los atajos de teclado y la lista de comandos |
| `/model` | Cambia el proveedor de LLM y el modelo |
| `/memory` | Muestra / administra la memoria persistente |
| `/history` | Explora y reanuda sesiones anteriores |
| `/goal` | Inicia / inspecciona un objetivo de investigación financiera |
| `/search` | Búsqueda de texto completo en todas las sesiones |
| `/swarm` | Preajustes multiagente (comité / cuantitativo / riesgo) |
| `/skill` | Lista / carga / descarga skills |
| `/show` | Muestra una ejecución anterior por id |
| `/clear` | Borra la conversación actual |
| `/pine` | Exporta la estrategia actual como Pine Script |
| `/journal` | Analiza el CSV del diario de operaciones |
| `/shadow` | Entrena / visualiza la cuenta shadow |
| `/export` | Exporta la sesión actual (md / json) |
| `/debug` | Activa o desactiva el panel de depuración (uso de tokens / latencia) |
| `/comps` | Análisis de empresas comparables (múltiplos de pares → rango implícito) |
| `/dcf` | Valoración por flujo de caja descontado con cuadrícula de sensibilidad |
| `/attrib` | Atribución Brinson-Fachler (asignación vs. selección) |
| `/memo` | Memo de inversión — tesis, visión alternativa, escenarios, criterios de invalidación |
| `/earnings` | Revisión de resultados — puente de sorpresas de ingresos a EPS |
| `/screen` | Filtro sistemático de ideas — hipótesis, funnel, cola de supervivientes |
| `/playbook` | Plantillas de investigación programada (listar / ejecutar / programar) |
| `/connector` | Perfiles de conectores de trading (estado / iniciar / detener) |
| `/halt` | Interruptor de emergencia — detiene TODO el trading en vivo de inmediato |
| `/resume` | Desactiva el interruptor de emergencia (reactiva el trading en vivo) |
| `/data` | Modo de enrutamiento de datos |
| `/quit` | Salir (también: q, exit, :q) |

</details>

<details>
<summary><b>Single run y flags</b></summary>

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
<summary><b>Canales IM</b></summary>

Los adaptadores de canales IM conectan aplicaciones de chat externas al mismo runtime de sesión que usan la Web UI y la CLI. Configura los adaptadores habilitados en `channels` dentro de `~/.vibe-trading/agent.json`; los adaptadores basados en SDK son extras opcionales, y si falta un SDK se muestran sugerencias de recuperación en lugar de bloquear el runtime.

Para tareas de canal de larga duración, ajusta el presupuesto central de espera de respuesta del asistente con `replyTimeoutS` (segundos, por defecto `600`):

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

Esto controla cuánto tiempo espera el runtime de canal compartido a que la sesión del agente produzca un mensaje del asistente; los timeouts HTTP/socket de cada adaptador siguen siendo específicos de cada uno.

```bash
vibe-trading channels status --local   # inspecciona la configuración y sugerencias de SDK faltante sin usar la API
vibe-trading channels status           # consulta el runtime de la API en ejecución
vibe-trading channels start            # inicia los adaptadores habilitados a través de la API
vibe-trading channels stop             # detiene los adaptadores habilitados a través de la API
vibe-trading channels login weixin     # ejecuta el hook de inicio de sesión del adaptador cuando sea necesario
vibe-trading channels pairing --channel telegram list
```

`vibe-trading channels login feishu` guarda las credenciales de la aplicación autorizadas por QR en `~/.vibe-trading/agent.json` con permisos de archivo solo para el propietario antes de informar que el inicio de sesión fue exitoso.

Los adaptadores integrados cubren `websocket`, `telegram`, `slack`, `discord`, `matrix`, `whatsapp`, `signal`, `qq`, `napcat`, `weixin`, `wecom`, `feishu`, `dingtalk`, `msteams`, `email` y `mochat`. Usa extras específicos como `pip install "vibe-trading-ai[telegram]"`, o instala el conjunto completo de canales con `pip install "vibe-trading-ai[channels]"`.

**Comandos slash dentro del chat** (independientes del canal, funcionan en los 16 adaptadores):

| Comando | Descripción |
|---------|-------------|
| `/new` | Reinicia la sesión actual — el siguiente mensaje inicia una conversación nueva |
| `/reset` | Alias de `/new` |
| `/newsession` | Alias de `/new` |
| `/pairing list` | Muestra las solicitudes de emparejamiento de remitentes pendientes (solo operadores) |

Los comandos no distinguen mayúsculas/minúsculas y deben enviarse como el mensaje completo (por ejemplo, `hello /new` se trata como un mensaje normal, no como un reinicio).

> **`/pairing` está restringido a operadores.** Los comandos de control de emparejamiento dentro del chat se rechazan a menos que el remitente figure como operador — configura `channels.operators` (autoridad entre canales) o la propia lista `operators` de la sección de un canal en tu configuración de canales. Sin operadores configurados, `/pairing` dentro del chat se rechaza (fail-closed) y el emparejamiento solo se gestiona a través de la CLI autenticada (`vibe-trading channels pairing …`) y el endpoint REST protegido por autenticación. Esto evita que cualquier miembro de un grupo en la lista de permitidos pueda tomar control del emparejamiento entre canales.

</details>

---

## 💡 Examples

### Strategy & Backtesting

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

**Compara un alpha zoo predefinido** (una línea):
```bash
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

**Explora el catálogo** e inspecciona un alpha individual:
```bash
vibe-trading alpha list --zoo gtja191 --theme reversal --limit 10
vibe-trading alpha show gtja191_171
```

**Compón una señal multifactor** a partir del zoo (Python):
```python
from src.skills.multi_factor.zoo_signal_engine import ZooSignalEngine
engine = ZooSignalEngine.from_zoo(["gtja191_171", "gtja191_111", "gtja191_163"])
panel = ...  # your wide OHLCV panel
signal = engine.compute_signal(panel)
```

### Market Research

```bash
# Equity deep-dive
vibe-trading run -p "Research NVDA: earnings trend, analyst consensus, option flow, and key risks for next quarter"

# Macro analysis
vibe-trading run -p "Analyze the current Fed rate path, USD strength, and impact on EM equities and gold"

# Crypto on-chain
vibe-trading run -p "Deep dive BTC on-chain: whale flows, exchange balances, miner activity, and funding rates"
```

### Swarm Workflows

```bash
# Bull/bear debate on a stock
vibe-trading --swarm-run investment_committee '{"topic": "Is TSLA a buy at current levels?"}'

# Quant strategy from screening to backtest
vibe-trading --swarm-run quant_strategy_desk '{"universe": "S&P 500", "horizon": "3 months"}'

# Crypto desk: funding + liquidation + flow → risk manager
vibe-trading --swarm-run crypto_trading_desk '{"asset": "ETH-USDT", "timeframe": "1w"}'

# Global macro portfolio allocation
vibe-trading --swarm-run macro_rates_fx_desk '{"focus": "Fed pivot impact on EM bonds"}'
```

### Cross-Session Memory

```bash
# Save your preferences once
vibe-trading run -p "Remember: I prefer RSI-based strategies, max 10% drawdown, hold period 5–20 days"

# The agent recalls them in future sessions automatically
vibe-trading run -p "Build a crypto strategy that fits my risk profile"
```

### Upload & Analyze Documents

```bash
# Analyze a broker export or earnings report
vibe-trading --upload trades_export.csv
vibe-trading run -p "Profile my trading behavior and identify any biases"

vibe-trading --upload NVDA_Q1_earnings.pdf
vibe-trading run -p "Summarize the key risks and beats/misses from this earnings report"
```

---

## 🌐 API Server

```bash
vibe-trading serve --port 8899
```

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/runs` | Listar runs |
| `GET` | `/runs/{run_id}` | Detalles del run |
| `GET` | `/runs/{run_id}/pine` | Exportación de indicador multiplataforma |
| `POST` | `/sessions` | Crear sesión |
| `POST` | `/sessions/{id}/messages` | Enviar mensaje |
| `GET` | `/sessions/{id}/events` | Flujo de eventos SSE |
| `POST` | `/upload` | Subir un documento, archivo de datos o imagen |
| `GET` | `/swarm/presets` | Listar presets de swarm |
| `POST` | `/swarm/runs` | Iniciar un run de swarm |
| `GET` | `/swarm/runs/{id}/events` | Flujo SSE del swarm |
| `GET` | `/alpha/list` | Listar alphas (filtrar por zoo/theme/universe) |
| `GET` | `/alpha/{alpha_id}` | Metadatos del alpha + código fuente |
| `POST` | `/alpha/bench` | Iniciar un job de bench (devuelve `job_id`) |
| `GET` | `/alpha/bench/{job_id}/stream` | Flujo SSE de progreso |
| `GET` | `/settings/llm` | Leer los ajustes de LLM de la Web UI |
| `PUT` | `/settings/llm` | Actualizar los ajustes de LLM locales |
| `GET` | `/settings/data-sources` | Leer los ajustes locales de fuentes de datos |
| `PUT` | `/settings/data-sources` | Actualizar los ajustes locales de fuentes de datos |
| `GET` | `/channels/status` | Leer el estado del runtime y los adaptadores de canales de IM |
| `POST` | `/channels/start` | Iniciar los adaptadores de canales de IM configurados |
| `POST` | `/channels/stop` | Detener los adaptadores de canales de IM configurados |
| `POST` | `/channels/pairing/command` | Ejecutar un comando de emparejamiento de remitente contra el almacén compartido |
| `POST` | `/scheduled-runs` | Crear un job de investigación programada (interval-ms o cron) |
| `GET` | `/scheduled-runs` | Listar jobs programados |
| `GET` | `/scheduled-runs/status` | Estado del ejecutor y destinos de entrega configurados |
| `GET` | `/scheduled-runs/{job_id}` | Leer un job programado |
| `DELETE` | `/scheduled-runs/{job_id}` | Cancelar un job programado |
| `POST` | `/scheduled-runs/proposals/{proposal_id}/commit` | Confirmar una creación/cancelación propuesta por el agente |
| `POST` | `/scheduled-runs/proposals/{proposal_id}/discard` | Descartar una propuesta del agente |
| `GET` | `/scheduled-runs/playbooks` | Listar las plantillas de investigación |
| `GET` | `/scheduled-runs/playbooks/{slug}` | Mostrar una plantilla, con sus variables |
| `POST` | `/scheduled-runs/playbooks/{slug}` | Programar un job a partir de una plantilla |
| `POST` | `/sessions/{id}/cancel` | Detener el run en curso de la sesión (se registra como cancelado, no como fallido) |
| `POST` | `/sessions/{id}/title/auto` | Resumir el primer intercambio en un título de sesión (nunca sobrescribe un renombrado manual) |
| `GET` | `/correlation/regime` | Línea de tiempo del régimen de densidad de correlación |
| `GET` | `/agents.json` · `POST` `/v1/query` | Puente con OpenBB Workspace — registrado solo con el extra opcional `openbb`; `/v1/query` requiere autenticación |

La documentación interactiva está disponible en `http://localhost:8899/docs` en
modo de desarrollo loopback sin clave. Cuando se configura `API_AUTH_KEY`, `/docs` y
`/redoc` quedan deshabilitados; las herramientas autenticadas pueden obtener `/openapi.json` con un
encabezado `Authorization: Bearer <key>`.

### Security defaults

Para desarrollo en localhost, `vibe-trading serve` mantiene simple el flujo del navegador. Para cualquier cliente no local, los endpoints sensibles de la API requieren `API_AUTH_KEY`; usa `Authorization: Bearer <key>` para las solicitudes JSON/upload. Los flujos EventSource del navegador son gestionados por la Web UI después de que ingreses la misma clave una vez en Settings.

Las herramientas de proceso con capacidad de shell (`bash` / `background_run` / `cancel_background`) están habilitadas solo para la CLI local interactiva. Cualquier otra superficie — la API HTTP/SSE y el servidor MCP en **todos** los transportes (incluido stdio) — las mantiene desactivadas a menos que optes explícitamente por activarlas con `VIBE_TRADING_ENABLE_SHELL_TOOLS=1` (o pases `--enable-shell-tools` a `vibe-trading-mcp`). El tipo de transporte nunca otorga acceso a shell de forma implícita. `cancel_background` solo detiene el task ID rastreado devuelto por `background_run`; la terminación amplia de procesos de Python por nombre se rechaza porque podría terminar Vibe-Trading mismo. Los lectores de documentos y journals están limitados por defecto a las raíces de upload/import; coloca los archivos bajo `~/.vibe-trading/uploads`, `~/.vibe-trading/runs`, `./uploads`, `./data` (o las heredadas `agent/uploads` / `agent/runs`), o agrega un directorio dedicado mediante `VIBE_TRADING_ALLOWED_FILE_ROOTS`. Las sesiones, runs, swarm runs, uploads y el índice `sessions.db` viven bajo `~/.vibe-trading` (reubicable mediante la variable de entorno de shell `VIBE_TRADING_HOME`); el historial preexistente se traslada allí automáticamente en el primer arranque.

El código de backtest generado se ejecuta como un subproceso local de Python y puede hacer solicitudes de red a través de los cargadores de datos de mercado configurados. Su entorno es intencionalmente limitado: el runner conserva lo básico de OS/Python, la configuración de proxy/certificados, `VIBE_TRADING_ALLOWED_RUN_ROOTS`, y claves de solo lectura para datos de mercado como `TUSHARE_TOKEN`, `FMP_API_KEY`, `FRED_API_KEY` y `VIBE_TRADING_IWENCAI_KEY`. Por defecto no pasa claves de proveedores de LLM, tokens de autenticación de la API, interruptores de herramientas de shell, secretos de trading de brokers ni toggles de live/advisory al código de estrategia generado.

### Web UI Settings

La página de Settings de la Web UI permite a los usuarios locales actualizar el proveedor/modelo de LLM, la URL base, los parámetros de generación, el reasoning effort y credenciales opcionales de datos de mercado como el token de Tushare. Los ajustes se persisten en `agent/.env`; los valores por defecto del proveedor se cargan desde `agent/src/providers/llm_providers.json`.

Las lecturas de Settings no tienen efectos secundarios: `GET /settings/llm` y `GET /settings/data-sources` nunca crean `agent/.env`, y solo devuelven rutas relativas al proyecto. Las lecturas y escrituras de Settings pueden exponer el estado de credenciales o actualizar credenciales/entorno de runtime, por lo que requieren `API_AUTH_KEY` cuando está configurada. Si `API_AUTH_KEY` no está definida en modo dev, el acceso a settings solo se acepta desde clientes loopback.

La misma página de Settings incluye un panel de **Canales de IM** para operadores locales. Consulta periódicamente `/channels/status`, muestra los estados configured/enabled/available/loaded/running, expone sugerencias de recuperación del adaptador, y puede iniciar o detener el runtime del canal configurado sin volver a la terminal.

### Scheduled research

Ejecuta un prompt de investigación o un backtest con una programación repetida — desde la página **Scheduled** en la web UI o mediante REST. El ejecutor en segundo plano está **desactivado por defecto** — inicia el servidor con `VIBE_TRADING_ENABLE_SCHEDULER=1` para habilitarlo:

```bash
VIBE_TRADING_ENABLE_SCHEDULER=1 vibe-trading serve --port 8899
```

Luego crea jobs mediante REST. `schedule` es o bien un entero simple (intervalo en **milisegundos**) o una expresión cron de 5 campos (`min hour dom mon dow`; cada campo acepta `*`, `*/n`, números, listas separadas por comas, o rangos como `1-5`). Cron se ejecuta según el reloj de pared de la `timezone` opcional del job (una clave IANA), de modo que la cadencia se mantiene a través de las transiciones de horario de verano — un hueco de "spring-forward" se omite, y un momento ambiguo de "fall-back" se ejecuta una sola vez, en su primera ocurrencia. Los jobs sin `timezone` mantienen la semántica UTC habitual:

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

Cada disparo ejecuta el `prompt` a través de una sesión de agente nueva (los parámetros opcionales de backtest van en `config`), y los jobs se persisten bajo `~/.vibe-trading/` para sobrevivir a los reinicios. Sin el flag, los endpoints `/scheduled-runs` siguen registrando jobs, pero ninguno se dispara. Agrega `-H "Authorization: Bearer <key>"` a cada llamada cuando `API_AUTH_KEY` está configurada.

El agente ve exactamente una herramienta de programación, `scheduled_research`: las acciones de lectura inspeccionan estado/jobs/plantillas, y `propose_create` y `propose_cancel` solo persisten una propuesta de confirmación de corta duración; nunca mutan el almacén de jobs. La web muestra una tarjeta de confirmación determinista, la CLI pregunta `y/N`, y las conversaciones de IM requieren responder exactamente `confirm` (`确认`) o `cancel` (`取消`) — solo esa acción de superficie llama al endpoint de commit. Cuando pasa `end_at`, el job queda `expired` y no vuelve a ejecutarse. La entrega es agnóstica del canal: configura referencias opacas reutilizables bajo `channels.deliveryTargets`; el agente y las superficies de confirmación ven ref/label/channel pero nunca el chat/user id crudo del proveedor. El estado de entrega es `accepted` cuando un adaptador tuvo éxito sin recibo del proveedor, y `sent` solo cuando devolvió un id de mensaje del proveedor (actualmente implementado de extremo a extremo para Feishu).

**Cinco plantillas listas para programar** vienen incluidas con el scheduler — `premarket-brief`, `earnings-season-tracker`, `portfolio-checkup`, `a-share-money-flow`, `institutional-holdings-diff`. Cada una expresa en lenguaje natural los datos que necesita un run en lugar de nombrar herramientas, de modo que una plantilla sigue funcionando a medida que crece la superficie de herramientas, y cada una está obligada a señalar un input faltante en lugar de completarlo de memoria. Accede a ellas desde la CLI, mediante REST, o con `/playbook` en la TUI:

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

Enviar `{}` programa una plantilla con su propia cadencia sugerida y sus valores por defecto declarados. El cuerpo renderizado se convierte textualmente en el prompt del job, y una variable no declarada se rechaza en lugar de ignorarse silenciosamente.

---

## 🔌 MCP Plugin

Vibe-Trading expone 74 MCP tools para cualquier cliente compatible con MCP. Se ejecuta como un subproceso stdio — no requiere configuración de servidor. Las herramientas de investigación principales funcionan sin ninguna API key para HK/US/crypto; las herramientas del conector de trading usan el perfil de conector seleccionado, y `run_swarm` necesita una LLM key.

**Variables de entorno:** el cliente lanza el servidor él mismo, así que un `export` de shell nunca le llega — configúralas en el bloque `env` del cliente. El código de backtest generado está confinado a los run roots permitidos, así que para escribir resultados en un workspace propio necesitas `VIBE_TRADING_ALLOWED_RUN_ROOTS`:

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

Añade a `claude_desktop_config.json`:

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

Añade a `~/.openclaw/config.yaml`:

```yaml
skills:
  - name: vibe-trading
    command: vibe-trading-mcp
```

Para una primera prueba de humo solo de investigación, confirma el descubrimiento
de herramientas y ejecuta una solicitud de datos de mercado o de backtest antes
de seleccionar un perfil de conector de trading. Las herramientas de
investigación principales pueden ejecutarse sin credenciales de broker; las
herramientas `trading_*` respaldadas por conector solo deben usarse después de
seleccionar y verificar intencionadamente un perfil de conector. `run_swarm`
requiere una LLM key.

</details>

<details>
<summary><b>Cursor / Windsurf / other MCP clients</b></summary>

```bash
vibe-trading-mcp                   # stdio (default)
vibe-trading-mcp --transport http  # Streamable HTTP (current MCP spec default) at http://127.0.0.1:8900/mcp
vibe-trading-mcp --transport sse   # legacy SSE (deprecated) for older clients
```

Para clientes HTTP (QwenPaw, y cualquier cliente que negocie enviando por POST
una `InitializeRequest`), usa `--transport http` y apunta el cliente al único
endpoint `/mcp` — por ejemplo, `http://127.0.0.1:8900/mcp`. **No** apuntes un
cliente HTTP a `/sse`; esa ruta pertenece al transporte SSE de dos endpoints
ya obsoleto y devolverá `405 Method Not Allowed` en `POST`. Sobrescribe la
dirección de bind con `--host` / `--port`.

</details>

**MCP tools expuestas (74):** `list_skills`, `load_skill`, `start_research_goal`, `get_research_goal`, `add_goal_evidence`, `update_research_goal_status`, `backtest`, `factor_analysis`, `alpha_zoo`, `alpha_bench`, `analyze_options`, `analyze_options_payoff`, `pattern_recognition`, `read_url`, `read_document`, `web_search`, `write_file`, `read_file`, `list_strategies`, `query_strategies`, `get_strategy_evidence`, `refresh_strategy_evidence`, `trading_connections`, `trading_select_connection`, `trading_check`, `trading_account`, `trading_positions`, `trading_orders`, `trading_quote`, `trading_history`, `list_swarm_presets`, `run_swarm`, `get_market_data`, `get_fund_flow`, `get_dragon_tiger`, `get_northbound_flow`, `get_margin_trading`, `get_block_trades`, `get_shareholder_count`, `get_lockup_expiry`, `get_sector_info`, `get_research_reports`, `get_stock_news`, `get_sec_filings`, `get_financial_statements`, `get_options_chain`, `get_stock_profile`, `screen_market`, `search_symbol`, `get_macro_series`, `iwencai_search`, `qveris_search`, `qveris_inspect`, `qveris_execute`, `get_institutional_holdings`, `etf_holdings`, `prediction_market`, `research_papers`, `get_swarm_status`, `get_run_result`, `list_runs`, `reap_stale_runs`, `retry_run`, `analyze_trade_journal`, `extract_shadow_strategy`, `run_shadow_backtest`, `render_shadow_report`, `scan_shadow_signals`, `quantlib_call`, `cashflow_performance`, `orderbook_depth`, `sentiment`, `technical_indicators`, `get_fundamentals`.

### SWARM external MCP tools

Los workers de `run_swarm` pueden llamar a herramientas aprobadas por el operador provenientes de servidores MCP externos. Configura la allowlist del lado del servidor en `VIBE_TRADING_SWARM_AGENT_CONFIG`, `~/.vibe-trading/swarm-agent.json`, o el respaldo `~/.vibe-trading/agent.json`; luego lista las herramientas remotas en un swarm preset usando el nombre del wrapper MCP local, como `mcp_internal_kb_search`. Las `variables` proporcionadas por el llamador permanecen como simples datos de plantilla y no pueden inyectar URLs de MCP, comandos, variables de entorno ni overrides de la allowlist.

<details>
<summary><b>Install from ClawHub (one command)</b></summary>

```bash
npx clawhub@latest install vibe-trading --force
```

> `--force` es necesario porque el skill hace referencia a APIs externas, lo cual dispara el escaneo automático de VirusTotal. El código es completamente open-source y seguro de inspeccionar.

Esto descarga el skill + la configuración MCP al directorio de skills de tu agente. No se necesita clonar nada.

Explora en ClawHub: [clawhub.ai/skills/vibe-trading](https://clawhub.ai/skills/vibe-trading)

</details>

<details>
<summary><b>OpenSpace — self-evolving skills</b></summary>

Los 90 skills de finanzas están publicados en [open-space.cloud](https://open-space.cloud) y evolucionan de forma autónoma mediante el motor de auto-evolución de OpenSpace.

Para usarlo con OpenSpace, añade ambos servidores MCP a la configuración de tu agente:

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

OpenSpace descubrirá automáticamente los 90 skills, habilitando auto-fix, auto-improve y compartición comunitaria. Busca skills de Vibe-Trading mediante `search_skills("finance backtest")` en cualquier agente conectado a OpenSpace.

</details>

---

### MetaTrader 5 (Exness and other MT5 brokers)

Se conecta a una **terminal MT5 en ejecución local** a través del paquete oficial `MetaTrader5` (**solo Windows**):

```bash
pip install "vibe-trading-ai[mt5]"
```

Configura `~/.vibe-trading/mt5.json` (créalo tú mismo; `chmod 600` donde esté soportado):

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

Luego:

```bash
vibe-trading connector use mt5-paper-sdk
vibe-trading connector check
vibe-trading connector account
vibe-trading connector quote EURUSD
vibe-trading connector history EURUSD
```

| Profile | Account | Orders |
|---------|---------|--------|
| `mt5-paper-sdk` | demo | solo lectura |
| `mt5-live-sdk-readonly` | real | solo lectura |
| `mt5-paper-trade` | demo | colocación directa (aplican los límites de tamaño por orden del connector) |
| `mt5-live-trade` | real | controlado por mandato + kill-switch |

Límite de seguridad: **"paper" significa la propia cuenta demo del broker**, reverificada en cada llamada — la terminal reporta `account_info().trade_mode` y el número de cuenta con sesión iniciada, por lo que apuntar un perfil paper a una cuenta de dinero real (o al revés) se rechaza de plano. MT5 dimensiona las órdenes en **lotes** (1 lote EURUSD = 100.000 EUR); el gate de mandato live cotiza los lotes a través del hook USD del connector, y los propios límites `max_order_volume` / `max_order_notional_usd` del connector aplican tanto en demo como en live, fallando de forma cerrada cuando un nocional no puede cotizarse. En cuentas de hedging (el valor predeterminado de Exness), ten en cuenta que una orden opuesta **abre una posición de hedge** — cierra por ticket en su lugar (pasa el ticket de la posición a `trading_cancel_order`) para que la ejecución quede anclada a esa posición y solo pueda reducir la exposición. Ruta de rollback / detención: el kill switch bloquea nuevas órdenes live, mientras que la cancelación sigue disponible y se registra en el audit log. Los límites de mandato están denominados en USD; una moneda de cuenta distinta de USD es margenada por el broker en su propia moneda.

El loader de datos de mercado `mt5` — la cabeza de la cadena de fallback de forex — comparte este mismo `mt5.json`. Si no existe dicho archivo, se conecta en modo solo lectura a la terminal usada más recientemente que ya tenga la sesión iniciada.

---
## 🔌 Conector de API Pública de eToro

Se conecta a la [API Pública de eToro](https://builders.etoro.com/) para cuentas demo y reales mediante un par de claves de API (`x-api-key` + `x-user-key`). Los entornos demo y real están separados estructuralmente: las claves demo solo pueden acceder a las rutas de API `/demo`.

Configura `~/.vibe-trading/etoro.json` (créalo tú mismo; usa `chmod 600` donde esté disponible):

```json
{
  "api_key": "YOUR_PUBLIC_API_KEY",
  "user_key": "YOUR_USER_KEY",
  "profile": "paper"
}
```

También puedes definir `ETORO_API_KEY` y `ETORO_USER_KEY` en `~/.vibe-trading/.env`.

Luego:

```bash
vibe-trading connector use etoro-paper-sdk
vibe-trading connector check
vibe-trading connector account
vibe-trading connector positions
vibe-trading connector quote BTC
```

| Perfil | Cuenta | Órdenes |
|---------|---------|--------|
| `etoro-paper-sdk` | demo | solo lectura |
| `etoro-live-sdk-readonly` | real | solo lectura |
| `etoro-paper-trade` | demo | colocación directa en rutas demo |
| `etoro-live-trade` | real | condicionado por mandato + kill-switch |

La búsqueda de símbolos usa el buscador `internalSymbolFull` de eToro (por ejemplo, `BTC` → id de instrumento `100000`). Usa la herramienta de agente `etoro_search_instruments` para resolver los tickers antes de operar.

Límite de seguridad: demo y real están separados por ruta y vinculados a la clave (`paper_guard: path_separated_key_bound`). Las acciones en real que aumentan el riesgo (abrir posiciones y copy-start/increase) requieren un mandato autorizado, un estado de halt despejado y una cuenta USD verificada para la aplicación del nocional de copia. Los cierres totales y parciales de posición validados, la cancelación de órdenes abiertas y el cierre de copia siguen disponibles en estado de halt y quedan registrados en auditoría. Cancelar un cierre pendiente o editar los stops de una posición es exclusivo de paper: la ruta real falla en cerrado (fail closed) porque esas operaciones pueden aumentar la exposición o transferir margen adicional sin suficientes datos de la API para cuantificar el riesgo incremental en USD. Los importes de copia se denominan en la divisa de la cuenta de eToro, y cada inicio/ajuste de copia requiere un id de referencia URL-safe de 1 a 35 caracteres proporcionado por el llamador para hacer polling. Las herramientas de escritura específicas de eToro (`etoro_close_position`, `etoro_copy_*`, etc.) son solo herramientas de agente, no se exponen vía MCP ni CLI. Rollback: revertir el/los commit(s) del conector o desactivar los perfiles; el halt bloquea nuevas acciones en real que aumenten el riesgo.

---

## 🔌 Cargar Herramientas desde Servidores MCP Externos (Modo Cliente MCP)

> **Esta es la dirección opuesta al Plugin MCP descrito arriba.**
> El Plugin MCP permite que *otros* agentes llamen a las herramientas de Vibe-Trading.
> Esta sección permite que el agente *integrado* de Vibe-Trading llame a herramientas de *tus* servidores MCP externos.

### Inicio rápido

Crea `~/.vibe-trading/agent.json`:

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

Ejecuta cualquier comando de la CLI: las herramientas de servidores externos ordinarios se inyectan automáticamente en el registro del agente después de las herramientas locales:

```bash
vibe-trading run "use my-server to do X"
```

### Sonda de solo lectura del MCP oficial de IBKR

Vibe-Trading puede conectarse directamente al endpoint MCP remoto oficial de
Interactive Brokers en modo de solo lectura. Añade esto a `~/.vibe-trading/agent.json`:

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

Luego inicia el flujo de OAuth en el navegador:

```bash
vibe-trading connector authorize ibkr-live-official-mcp-readonly
```

El comodín solo se acepta para la sonda `mcp.read` de IBKR. Autorizar este
perfil confirma el acceso al scope de lectura oficial de IBKR; las llamadas genéricas a
`trading_account` y `trading_positions` permanecen deshabilitadas hasta que IBKR publique
nombres de herramientas de lectura estables que Vibe-Trading pueda mapear de forma segura. Una configuración
que añada `mcp.write` debe fijar una lista blanca explícita de herramientas y aun así pasar por el
guard de órdenes en real.

Si IBKR emite un cliente OAuth pre-registrado, añade `clientId` y `clientSecret`
dentro de `auth`.

### Conectores de trading: la ruta más rápida

Para usuarios que no pueden esperar la aprobación del cliente OAuth de IBKR, conéctate a una
sesión local de TWS o IB Gateway. Las credenciales permanecen dentro de la app de escritorio de IBKR; Vibe-
Trading solo se conecta a `127.0.0.1` y la expone como un perfil de conector.

Instala el SDK opcional:

```bash
pip install "vibe-trading-ai[ibkr]"
```

Abre TWS en modo paper trading o IB Gateway paper, habilita los clientes de socket de API y luego ejecuta:

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

Puertos locales por defecto:

| App | Paper | Real de solo lectura |
|-----|-------|----------------|
| TWS | `7497` | `7496` |
| IB Gateway | `4002` | `4001` |

El agente expone herramientas con alcance de conector llamadas `trading_connections`,
`trading_select_connection`, `trading_check`, `trading_account`,
`trading_positions`, `trading_orders`, `trading_quote` y `trading_history`.
Las herramientas MCP crudas de brokers en real no se registran directamente como `mcp_<broker>_*`.
No se registra ninguna herramienta de colocación de órdenes para IBKR.

### 🔐 Modo TAP — aislamiento total de credenciales y escrituras aprobadas por humanos

**Opcional, desactivado por defecto.** Si las variables `TAP_*` de abajo no están definidas, el
conector se comporta exactamente igual que antes (SDK directo del broker); nada cambia.

[TAP](https://tap.human.tech) (Tool Authorization Protocol) es un proxy de
credenciales: el agente nunca posee el secreto crudo de la API del broker, y las escrituras
con consecuencias reales están condicionadas a la **aprobación humana**. Con el modo TAP activado, **cada**
llamada a Alpaca (colocación de órdenes, cancelación, y las lecturas: cuenta/posiciones/órdenes/cotización/barras) se envía
al endpoint `/forward` del proxy TAP en lugar del SDK del broker; TAP inyecta la
clave real en el servidor y luego reenvía la solicitud hacia arriba.

- El proceso del agente **no posee ninguna clave de Alpaca en absoluto** — y ni siquiera necesita
  `alpaca-py` — porque todo el tráfico de salida pasa por TAP. El secreto se
  referencia por nombre (`<CREDENTIAL:alpaca.key_id>`) y TAP lo sustituye.
- **Las escrituras se bloquean hasta la aprobación humana.** Una orden o cancelación no puede llegar al broker
  sin que un humano la apruebe; incluso un "compra ahora" inyectado mediante prompt queda retenido, y
  denegarlo significa que nunca llega a Alpaca. Las órdenes llevan un
  `client_order_id` determinístico, de modo que un reintento por condición de carrera en la aprobación se deduplica en lugar de
  colocarse dos veces.
- **Las lecturas se aprueban automáticamente.** Cuenta/posiciones/órdenes/cotización/barras son GETs que TAP
  reenvía sin un paso humano — esto es *aislamiento* de credenciales (ninguna clave en el
  proceso), no una compuerta, así que la fricción añadida es prácticamente cero.
- `allowed_hosts` en la credencial de TAP fija a dónde puede enviarse la clave, de modo que un
  destino manipulado se rechaza (403) antes de la inyección.

**Cómo habilitarlo:**

1. En el panel de TAP, crea una credencial **multi-secreto** llamada `alpaca`
   que contenga tu par de claves de Alpaca en los campos `key_id` y `secret_key`, asignada a
   tu agente, con hosts permitidos `paper-api.alpaca.markets` (o el host real
   `api.alpaca.markets`) **y** `data.alpaca.markets` (el host de datos de mercado usado
   por quote/bars). Usa **credenciales de TAP separadas para paper y real** (por ejemplo,
   `alpaca-paper` / `alpaca-live`, seleccionadas mediante `TAP_ALPACA_CREDENTIAL`), cada una
   con `allowed_hosts` fijado a su propio host de API — así TAP se niega estructuralmente a
   enviar la clave de paper al host real y viceversa, manteniendo la separación
   paper/real nítida de principio a fin.
2. Añade a `agent/.env`:

| Variable | Requerida | Descripción |
|----------|:--------:|-------------|
| `TAP_PROXY_URL` | Sí | URL base del proxy TAP (por ejemplo, `https://proxy.tap.human.tech`) |
| `TAP_AGENT_KEY` | Sí | Tu clave de API del agente TAP (secreto) |
| `TAP_ALPACA_CREDENTIAL` | No | Nombre de la credencial TAP para Alpaca (por defecto `alpaca`) |
| `TAP_APPROVAL_TIMEOUT` | No | Segundos a esperar la decisión de un humano (por defecto `300`) |

Cuando se coloca una escritura, apruébala o denégala en tu canal de TAP (Telegram /
panel). Una orden/cancelación aprobada se reenvía a Alpaca; una denegada o que
agotó el tiempo de espera **nunca se envía**.

> **Limitación conocida — condición de carrera en la aprobación.** Si el humano aprueba justo en el
> límite de `TAP_APPROVAL_TIMEOUT`, TAP puede reenviar la orden mientras el polling ya
> se ha rendido: la compuerta entonces reporta un error aunque la orden llegó al
> broker, y el contador `max_trades_per_day` cuenta una de menos. El
> `client_order_id` determinístico evita que un reintento coloque esa orden por duplicado;
> si dependes de un límite estricto de operaciones por día, revisa las órdenes abiertas después de un
> error de timeout de TAP antes de reintentar.

**Alcance:** cubre la **colocación de órdenes, cancelación y las cinco lecturas** de Alpaca — el
tráfico de salida completo del conector, de modo que el proceso no posee la clave en ninguna ruta. Los brokers con firma
HMAC (Binance/OKX) quedan como trabajo futuro (la firma del lado del cliente no encaja con la inyección
de tráfico de salida pura). Los hooks son aditivos: viven dentro del conector de Alpaca y
dejan intacta la compuerta de mandato en real.

### Referencia de configuración

| Campo | Tipo | Por defecto | Descripción |
|-------|------|---------|-------------|
| `type` | string | inferido para stdio; requerido para HTTP | Omítelo para stdio, o ponlo en `sse` / `streamableHttp` para servidores basados en URL. |
| `command` | string | requerido para stdio | Ejecutable a lanzar para servidores stdio. Inválido para servidores `sse` / `streamableHttp`. |
| `args` | array | `[]` | Argumentos de línea de comandos solo para servidores stdio. |
| `env` | object | `{}` | Variables de entorno adicionales fusionadas en el entorno del subproceso solo para servidores stdio. |
| `url` | string | requerido para `sse` / `streamableHttp` | URL del endpoint remoto SSE / streamable HTTP. No se usa para servidores stdio. |
| `headers` | object | `{}` | Cabeceras HTTP adicionales solo para servidores `sse` / `streamableHttp`. |
| `toolTimeout` | number | `30` | Timeout por llamada a herramienta, en segundos |
| `initTimeout` | number | sin definir (`max(toolTimeout, 30)`) | Timeout de initialize / autorización OAuth de MCP, en segundos. Úsalo para autorización lenta por navegador sin ampliar las llamadas ordinarias a herramientas. |
| `enabledTools` | array | `["*"]` | Lista blanca de herramientas. Usa `["*"]` para exponer todas las herramientas del servidor |

Ubicación del archivo de configuración: `~/.vibe-trading/agent.json` (JSON o YAML).

Para transportes basados en URL, `type` es obligatorio. El agente ya no adivina entre SSE y streamable HTTP a partir del sufijo de la URL.

### Anulaciones por sesión (API)

Al crear una sesión mediante la API puedes pasar `mcpServers` dentro de `session.config` para extender o anular la configuración global solo para esa sesión:

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

### Nomenclatura de herramientas

Las herramientas remotas ordinarias se exponen con nombres estables: `mcp_<server>_<tool>`.
Los servidores MCP de brokers en real permanecen detrás de la superficie de conector `trading_*`.

Si dos nombres de servidor producen el mismo prefijo local seguro para ASCII (por ejemplo, `foo-bar` y `foo_bar` ambos se convierten en `foo_bar`), se añade un sufijo hash determinístico a nivel del segmento de servidor para que los nombres sigan siendo únicos. El operador recibe una advertencia:

```
WARNING: Configured MCP server 'foo-bar' collides with another server after local name
normalization. Using local tool prefix 'mcp_foo_bar_<hash>_<tool>' to keep generated
tool names unique. Rename the server in agent config if you want a different prefix.
```

### Límites de v1

| Límite | Detalle |
|-------|--------|
| Transporte | stdio, SSE y streamable HTTP |
| Ejecución | solo serial — las herramientas MCP nunca entran en la ruta paralela de solo lectura |
| Superficies | solo herramientas (resources y prompts excluidos en v1) |
| Recarga en caliente | no soportada — reinicia el proceso para aplicar cambios de configuración |
| Ruta Swarm | las herramientas MCP no están disponibles dentro de los registros de workers de Swarm en v1 |

---
## 📁 Project Structure

<details>
<summary><b>Haz clic para expandir</b></summary>

```
Vibe-Trading/
├── agent/                          # Backend (Python)
│   ├── cli/                        # Paquete CLI — TUI interactiva + subcomandos
│   ├── api_server.py               # Servidor FastAPI — runs, sesiones, carga, swarm, SSE
│   ├── mcp_server.py               # Servidor MCP — 74 herramientas para OpenClaw / Claude Desktop
│   │
│   ├── src/
│   │   ├── agent/                  # Núcleo del agente ReAct
│   │   │   ├── loop.py             #   compresión de 5 capas + agrupación de herramientas de lectura/escritura
│   │   │   ├── context.py          #   system prompt + auto-recuperación desde memoria persistente
│   │   │   ├── skills.py           #   cargador de skills (90 incluidas + creadas por el usuario vía CRUD)
│   │   │   ├── tools.py            #   clase base de herramientas + registro
│   │   │   ├── memory.py           #   estado ligero del workspace por ejecución
│   │   │   ├── frontmatter.py      #   parser de frontmatter YAML compartido
│   │   │   └── trace.py            #   escritor de traza de ejecución
│   │   │
│   │   ├── memory/                 # Memoria persistente entre sesiones
│   │   │   └── persistent.py       #   memoria basada en archivos (~/.vibe-trading/memory/)
│   │   │
│   │   ├── tools/                  # 107 herramientas de agente autodescubiertas
│   │   │   ├── backtest_tool.py    #   ejecuta backtests
│   │   │   ├── remember_tool.py    #   memoria entre sesiones (save/recall/forget)
│   │   │   ├── skill_writer_tool.py #  CRUD de skills (save/patch/delete/file)
│   │   │   ├── session_search_tool.py # búsqueda FTS5 entre sesiones
│   │   │   ├── swarm_tool.py       #   lanza equipos swarm
│   │   │   ├── web_search_tool.py  #   búsqueda web con DuckDuckGo
│   │   │   └── ...                 #   bash, E/S de archivos, análisis de factores, opciones, navegador de alpha + bench, etc.
│   │   │
│   │   ├── factors/                # Alpha Zoo — 462 alphas en 5 familias
│   │   │   ├── base.py             #   19 operadores (rank/scale/ts_*/delta/decay_linear/safe_div/vwap)
│   │   │   ├── registry.py         #   carga de metadatos solo por AST + cómputo diferido + puertas de sanidad
│   │   │   ├── bench_runner.py     #   IC + categorización alive/reversed/dead
│   │   │   └── zoo/                #   qlib158 (154) + alpha101 (101) + gtja191 (191) + academic (12) + fundamental (4)
│   │   │
│   │   ├── api/                    # Módulos de rutas FastAPI
│   │   │   └── alpha_routes.py     #   /alpha/list, /alpha/{id}, /alpha/bench, flujo SSE
│   │   │
│   │   ├── skills/                 # 90 skills financieras en 9 categorías (un SKILL.md cada una)
│   │   ├── swarm/                  # Motor de ejecución de DAG swarm
│   │   │   └── presets/            #   30 definiciones YAML de presets swarm
│   │   ├── session/                # Chat multi-turno + búsqueda de sesiones FTS5
│   │   └── providers/              # Abstracción de proveedores LLM
│   │
│   └── backtest/                   # Motores de backtest
│       ├── engines/                #   8 motores + motor compuesto multi-mercado + options_portfolio
│       ├── loaders/                #   24 fuentes: tushare, okx, binance, yfinance, akshare, baostock, tencent, mootdx, ccxt, futu, pykrx, local, eastmoney, sina, stooq, yahoo, finnhub, alphavantage, tiingo, fmp, longbridge, mt5, qveris, india_broker
│       │   ├── base.py             #   Protocolo DataLoader
│       │   └── registry.py         #   Registro + cadenas de fallback automáticas
│       └── optimizers/             #   MVO, equal vol, max div, risk parity
│
├── frontend/                       # Interfaz web (React 19 + Vite + TypeScript)
│   └── src/
│       ├── pages/                  #   Home, Agent, AlphaZoo, RunDetail, Compare, Correlation, Settings
│       ├── components/             #   chat, gráficos, layout
│       └── stores/                 #   gestión de estado con Zustand
│
├── Dockerfile                      # Build multi-etapa
├── docker-compose.yml              # Despliegue con un solo comando
├── pyproject.toml                  # Configuración del paquete + entrypoint de CLI
├── tools/                          # Utilidades de CI a nivel de repositorio
│   └── ci_grep_gates.sh            # rechaza yaml.load / marca registrada / filtraciones de datos por acción
└── LICENSE                         # MIT
```

</details>

---

## 🏛 Ecosystem

Vibe-Trading forma parte del ecosistema de agentes de **[HKUDS](https://github.com/HKUDS)**:

<table>
  <tr>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/nanobot"><b>NanoBot</b></a><br>
      <sub>Ultra-Lightweight Personal AI Assistant</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/AI-Trader"><b>AI-Trader</b></a><br>
      <sub>Agent-Native Signal &amp; Copy Trading Platform</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/CLI-Anything"><b>CLI-Anything</b></a><br>
      <sub>Making All Software Agent-Native</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/OpenSpace"><b>OpenSpace</b></a><br>
      <sub>Self-Evolving AI Agent Skills</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/ClawTeam"><b>ClawTeam</b></a><br>
      <sub>Agent Swarm Intelligence</sub>
    </td>
  </tr>
</table>

---

## 🗺 Roadmap

> Entregamos por fases. Los elementos se trasladan a [Issues](https://github.com/HKUDS/Vibe-Trading/issues) cuando comienza el trabajo.

| Fase | Función | Estado |
|-------|---------|--------|
| **Trust Layer** | Se emiten run cards reproducibles y se muestran en Run Detail; v1 añade tool traces y citations | v0 publicado |
| **Hypothesis Registry** | Hipótesis de investigación duraderas con lifecycle status, data sources, skills, enlaces a run-card y notas de invalidación | MVP de backend publicado |
| **Research Autopilot** | Bucle de investigación manual-primero: hipótesis → backtest determinista → evidence report | Fases 1–3 publicadas |
| **Data Bridge** | Trae tus propios datos: conectores locales CSV/Parquet/SQL con mapeo de esquema | Cargador local publicado |
| **Options Lab** | Superficie de volatilidad, panel de Greeks, explorador de payoff/escenarios | Herramienta analítica de payoff/escenarios **publicada**; superficie/panel planificados |
| **Portfolio Studio** | Risk x-ray, restricciones, optimizador con reducción de turnover, notas de rebalanceo | Optimizador con reducción de turnover **publicado en 0.1.11**; el resto planificado |
| **Alpha Zoo** | 462 alphas preconstruidas (Qlib 158 + Kakushadze 101 + GTJA 191 + academic + fundamental) con benchmark en una línea, integración con el agente y Web UI | **Publicado en 0.1.8**, ampliado hasta 0.1.12 |
| **Strategy Development Manager** | Registra papers / research de brokers como factores y estrategias con un almacén persistente + lifecycle automatizado de decaimiento de IC/Sharpe | **Publicado en 0.1.11** |
| **Correlation Regime** | Línea temporal de régimen por edge-density + histéresis, superpuesta en `/correlation` — detecta cuándo los mercados se fusionan en un solo bloque | **Publicado en 0.1.12** |
| **Research Delivery** | Briefs programados y sesiones de investigación en vivo a través de canales IM tipo Slack / Telegram / correo | Scheduler + runtime de IM publicados |
| **Community** | Skills, presets y strategy cards compartibles | En exploración |

---

## Contributing

¡Damos la bienvenida a las contribuciones! Consulta [CONTRIBUTING.md](CONTRIBUTING.md) para conocer las pautas.

Los **Good first issues** están etiquetados con [`good first issue`](https://github.com/HKUDS/Vibe-Trading/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) — elige uno y comienza.

¿Quieres contribuir con algo más grande? Revisa el [Roadmap](#-roadmap) anterior y abre un issue para discutirlo antes de empezar.

---

## Contributors

¡Gracias a todos los que han contribuido a Vibe-Trading!

Contribuidores y créditos recientes del ciclo v0.1.14:

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
<summary>Contribuidores del ciclo v0.1.12</summary>

- @santhreal — una limpieza de corrección de 30 PR: endurecimiento de strict-JSON / números finitos en metrics, factors, pattern y options (#764/#765/#766/#767/#739/#740/#744), corrección de loaders (#761 yahoo 1m bars), y robustez de session / journal (#762/#763/#768/#769/#770)
- @xkam7ar — mejoras de fiabilidad amplias en packaging, web, scheduler, swarm y CLI (#584), cancelación antes de la primera iteración de AgentLoop (#641, cierra #638), presupuesto de sesión de QVeris + contabilidad atómica de créditos (#685/#686), puertas de CI / OOS (#630/#632), y correcciones del filtro por mes / parseo de side en journal (#626/#628)
- @shadowinlife — la skill Strategy Development Manager (#457, cierra #455), extracción enchufable con OCR + LLM-vision (#548), credenciales de proveedor centralizadas (#563), la vectorización 80× de alineación de señales (#698), y el cacheo de MCP-discovery en swarm (#704)
- @ebujinovch — el endpoint + UI de la línea temporal de correlation regime (#756, cierra #719) y su skill `correlation-regime` (#557), además del factor `academic_corr_rewire` (#705)
- @honginp — enrutamiento USD-M de Binance con separación execution/mark (#470/#716) y el desacoplamiento del maintenance-bracket que mantiene los backtests `-PERP` sin necesidad de credenciales (#757)
- @StaniellG — el connector de broker MetaTrader 5 (Exness) + la fuente de datos `mt5` (#481)
- @tyj147454413-cmd — el loader de fallback de Binance (#643), historial acotado de OKX con manejo de rate-limit (#644), y clasificación de fallos de stream de codex (#663)
- @Marnie0415 — fallback de sub-motor composite para símbolos desconocidos (#734) y la corrección de la race condition de DOM en `insertBefore` durante el streaming en el frontend (#717)
- @YZY0108 — la corrección de look-ahead-bias en los cinco optimizadores de portfolio (#487)
- @UNHNQ — los proveedores SiliconFlow CN + Global (#565)
- @FenjuFu — el proveedor iFlytek Spark (#537)
- @jelech — el adaptador nativo de la API de Messages de Anthropic (#695)
- @octo-patch — endpoints regionales de la API de MiniMax (#731)
- @Thibaultjaigu — el proveedor de gateway Requesty compatible con OpenAI (#474)
- @Robin1987China — métricas de turnover realizado del portfolio para cada optimizador (#478)
- @YogeshModi24 — el factor académico betting-against-beta de Frazzini-Pedersen (#480)
- @0xZKnw — modo TAP opcional para Alpaca (#377)
- @sambazhu — la whitelist `_VALID_ZOOS` del zoo fundamental (#707)
- @nareshkps — conexión de `account_number` en el connector de Robinhood (#726)
- @darkknight4563 — descubrimiento del directorio de swarm-presets del usuario (#570)
- @MikeCer — pool de conexiones thread-local de IBKR + cotizaciones snapshot (#636)
- @Shizoqua — resampling de intervalos en el loader `local` (#467)
- @roberttidball — compatibilidad de importación del transporte de FastMCP (#469)
- @yxhuang — resolución de tickers sin prefijo en la matriz de correlación (#472, cierra #471)
- @Bortlesboat — corrección de `OPENAI_BASE_URL` desactualizado al cambiar de proveedor (#484, cierra #482)
- @ananaymital — corrección de caché desactualizada de `EnvConfig` en preflight (#479, cierra #477)
- @GabbaTauchi — reportó el bug de streaming / base-URL nativo de zai (#758)
- @warren618 / Haozhe Wu — la integración de backend de correlation regime, la corrección de streaming + resolución de base-URL del proveedor zai (#758), integración de releases, y triage de PRs/issues abiertos

</details>

<details>
<summary>Contribuidores del ciclo v0.1.11</summary>

- @shadowinlife — la culminación de la modularización de `api_server` (1103 → 371 líneas, #424 cerrando #331), configuración de entorno centralizada con la puerta de CI basada en AST (#440), conformidad del protocolo `fetch()` de los loaders (#437), y el RFC de Strategy Development Manager en revisión (#455/#457) — 12 PR fusionados en este ciclo
- @Robin1987China — cierre del bucle de la Fase 3 de Research Autopilot (#267), 4 alphas académicas canónicas (#277), condiciones de entrada PIT-safe de Shadow Account (#302/#314/#316), el optimizador de portfolio con reducción de turnover (#466), tests de la ruta de scheduled-research (#452), y lotes de cobertura de tests para las capas de trade-journal / pattern / loader (#268/#269/#276)
- @muku314115 — soporte de primera clase para renta variable india (NSE/BSE): `IndiaEquityEngine`, el stack de costes, el enrutamiento `.NS`/`.BO`, y el puente `india_broker` (#305)
- @mvanhorn — el ejecutor de extremo a extremo de scheduled-research (#278), el connector de solo lectura de Trading 212 (#321), la resolución del modelo por defecto de OpenAI (#319), y la validación de configuración de Robinhood (#320)
- @fei-moss — la herramienta de visión `analyze_image` (#464), el emparejamiento DM de NapCat (#463), y el informe de allowed-roots de medios en IM (#465)
- @sambazhu — el toolkit de value-investing: herramientas de financial-rigor + report-audit, 4 skills, y el preset `value_investing_committee` (#407/#408)
- @Elfsa-Miranda — la exploración del pipeline de investigación de alpha vinculado a evidencia (#405/#416, posteriormente reencauzado en #442)
- @Hinotoi-agent — rechazo de CSRF en loopback (#293) y solicitudes remotas autenticadas de la UI del mismo origen (#304)
- @dpersek — timeout configurable de respuesta en IM (#413) y la corrección de redirect en el preflight del proveedor (#404)
- @digger-yu — comandos `setup`/`dev` multiplataforma (#292) y comprobaciones previas de dependencias de desarrollo (#349)
- @skloxo — expansión de tilde + fallback de seguridad de file-roots (#299) y localización reactiva zh-CN (#301)
- @kadaliao — el tutorial para principiantes (#393) y las tarjetas sociales de Alpha Library (#396)
- @morluto — preservación del primer mensaje en el resume de CLI (#448) y el modelo por defecto de Codex OAuth (#446)
- @yxhuang — el proveedor Kimi for Coding (#435) y el diagnóstico preciso de #433 detrás de la reversión del governance-stack
- @isaveall — la corrección del directorio de artifacts de `validation.json` (#429) y errores más claros en `--swarm-run` (#428)
- @mustafakamal88 — timestamps UTC con conciencia de zona horaria (#397)
- @irfanallana-oss — la protección contra órdenes de tamaño cero en `trading_place_order` (#417)
- @Shizoqua — la protección central de invariante OHLC en el loader (#274)
- @hobostay — endurecimiento de la protección SSRF para rangos CGNAT/mesh + la corrección del redirect de medios de QQ (#389)
- @aeonframework — elevación de las versiones mínimas de Pillow / langchain por CVE (#390)
- @hannibal-lee — la corrección de la restricción de versión de pandas (#329)
- @MarkfuGod — conteos dinámicos de fuentes de datos + microcompaction controlada por tokens (#296)
- @gyx09212214-prog — salidas con validación estricta de JSON (#306)
- @LemonCANDY42 — la librería de informes de backtest (#224)
- @fanfpy — serialización Decimal→float de Longbridge (#459)
- @asahikiko — sincronización del conteo de capacidades en el SKILL.md empaquetado + el test de protección del manifest (#461)
- @wison1717-maker — el diálogo de segunda confirmación del mandato + toasts de error unificados (#453)
- @imsankz — mapeos de proveedor de opencode (#444)
- @flash1234pku — la corrección del code-fence de referencia de tushare (#449)
- @Penn-Live — el reporte del crash de iteración de rutas al iniciar Docker (#450)
- @warren618 / Haozhe Wu — la capa de factores fundamentales (paneles SEC PIT-safe), el track premium de QVeris, el runtime del canal IM, la revisión de la integración de renta variable india, los fallbacks de búsqueda en CN, e integración de releases

</details>

<details>
<summary>Contribuidores del ciclo v0.1.10</summary>

- @Hinotoi-agent — una ola de endurecimiento de seguridad: autenticación para el shutdown local (#241), rechazo de rebinding del host loopback (#242), opt-in de la herramienta de shell del agente (#243), autenticación en la escritura de settings (#245), contención del proposal-id del mandato (#256), validación de tipos en la memoria persistente (#257), y contención del run-id de swarm en MCP (#258)
- @mvanhorn — la caché local de datos opcional (#177), el round-trip del thoughtSignature de Gemini sobre tool calls compatibles con OpenAI (#176), la guía de loaders de datos personalizados (#194), y el alias de proveedor glm/zhipu + inferencia del nombre de modelo (#247)
- @gyx09212214-prog — robustez del loader ante variables de entorno de timeout malformadas de crypto/RSSHub (#227, #240), inclusión de la fecha final solicitada en yfinance (#226), JSON estricto de run-card para métricas no finitas (#238), y cobertura de retry-fallback en ddgs (#239)
- @BillDin — estado de los agentes swarm en la UI de chat (#188), manejo explícito del nombre del preset (#189), la herramienta de datos de mercado respaldada por loader para los workers de swarm (#199), y continuaciones de contexto de preset (#200)
- @Robin1987China — el puente goal-hypothesis de Research Autopilot (#260), el loader de datos local CSV/Parquet/DuckDB (#252), y una corrección de assistant-prefill + User-Agent configurable de Kimi (#248)
- @LemonCANDY42 — el panel de estado del runtime de solo lectura (#210), artefactos persistidos de uso de AgentLoop (#223), y payloads de gráficos de Run Detail opcionales (#225)
- @zwrong — la revisión de trace.jsonl con truncamiento cero + offload (#206) y el session-id al salir + `resume <session-id>` (#218)
- @forge-builder — la guía de contribución para IA (#173) y la documentación de smoke-tests solo de investigación de OpenClaw MCP (#165)
- @skloxo — localización del frontend al chino (zh-CN) (adoptada de #217)
- @LeeCQiang — docstrings en chino para los 452 factores de Alpha Zoo (#180)
- @KaiLuettmann — publicación de imágenes preconstruidas en GHCR con cada release (#187)
- @ngoanpv — preservación del thought_signature de Gemini a través de la ruta dict de AgentLoop (#184)
- @ShahNewazKhan — alcanzabilidad de Ollama en el host desde Docker vía host.docker.internal (#196)
- @sambazhu — sincronización en el frontend de los intentos de chat completados (#236)
- @bhlt — soporte del formato de código nativo de baostock (#230)
- @octo-patch — actualización del modelo por defecto a MiniMax M3 (#162)
- @warren618 / Haozhe Wu — la capa de datos global (8 fuentes + 18 herramientas de datos de solo lectura), los 10 connectors de SDK de broker, el stack completo de alpha-compare, la revisión de fiabilidad de proveedores, el fallback de web_search multi-motor, el Stop responsivo + reconexión SSE, e integración de releases

</details>

<a href="https://github.com/HKUDS/Vibe-Trading/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/Vibe-Trading" />
</a>

---

## Disclaimer

Vibe-Trading es software de investigación y trading. No constituye asesoría de inversión, no custodia fondos y no opera ningún centro de ejecución. El trading a través de un canal de broker que tú autorizas explícitamente (por ejemplo, Robinhood Agentic Trading) ocurre únicamente dentro de los límites que tú estableces y que puedes detener en cualquier momento. Esta capacidad de trading a través de broker es experimental y no ha sido verificada por nosotros frente a una cuenta de broker real — utilízala bajo tu propio riesgo. El rendimiento pasado no garantiza resultados futuros.

## License

MIT License — see [LICENSE](LICENSE)

---

<p align="center">
  ⭐ Si <b>Vibe-Trading</b> ayuda a tu investigación, una estrella ayuda a que más personas la encuentren.
</p>

---

<p align="center">
  Gracias por visitar <b>Vibe-Trading</b> ✨
</p>
<p align="center">
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.Vibe-Trading&style=flat" alt="visitors"/>
</p>
