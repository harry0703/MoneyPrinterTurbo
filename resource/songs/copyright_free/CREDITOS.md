# Música y ganchos libres de derechos

Paquete de audio para los videos de **Chamanismo y Holística** y **Silhouette Punto Total**.

## Licencia

Todos los archivos de esta carpeta son **originales**: se sintetizaron desde cero con
código (`generate_audio_pack.py`), sin samples, loops ni grabaciones de terceros.
No hay derechos de terceros, así que puedes usarlos en videos comerciales, anuncios,
TikTok, Reels y YouTube **sin atribución y sin reclamos de Content ID**.
Los publicamos bajo [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/deed.es).

## Fondos (3:00 cada uno, -18 LUFS, listos para ir debajo de una voz)

| Archivo | Para | Carácter |
| --- | --- | --- |
| `chamanismo_cuencos_profundos.mp3` | Chamanismo | Dron grave en Re con cuencos tibetanos cada 8-14 s |
| `chamanismo_tambor_ritual.mp3` | Chamanismo | Tambor de marco tipo latido (66 bpm) con sonaja |
| `chamanismo_binaural_calma_theta.mp3` | Chamanismo | Pulso binaural de 6 Hz (theta), pad cálido y viento; mejor con audífonos |
| `chamanismo_viento_y_campanas.mp3` | Chamanismo | Viento suave y campanitas al azar |
| `silhouette_spa_ambiente.mp3` | Silhouette | Pads de spa, notas sueltas de piano eléctrico y agua |
| `silhouette_lofi_suave_80bpm.mp3` | Silhouette | Lofi relajado con acordes de piano eléctrico y crujido de vinilo |
| `silhouette_pulso_ligero_104bpm.mp3` | Silhouette | Arpegios y beat ligero para antes/después y tips rápidos |

## Ganchos (primeros segundos del video)

| Archivo | Duración | Uso sugerido |
| --- | --- | --- |
| `gancho_cuenco_golpe.mp3` | 4.5 s | Abrir una lectura o un ritual |
| `gancho_cuenco_reverso.mp3` | 6 s | Subida que remata en golpe de cuenco: revelar una carta |
| `gancho_gong_swell.mp3` | 5 s | Inicio solemne, cambio de tema |
| `gancho_tambor_doble.mp3` | 2.2 s | «Pum-pum» para captar atención en el segundo 0 |
| `gancho_brillo_campanitas.mp3` | 2.8 s | Revelar un resultado o un producto |
| `gancho_riser_whoosh.mp3` | 2.5 s | Transición antes/después |
| `gancho_pop_suave.mp3` | 0.5 s | Texto que aparece en pantalla, botón, precio |

## Volumen recomendado

- Con voz: fondo al 15-20 % (`bgm_volume = 0.2` en MoneyPrinterTurbo, `background_audio_volume = 0.15` en videoAIgenerate).
- Sin voz: fondo al 60-80 %.
- Ganchos: al 100 %; ya vienen niveladas a -16 LUFS.

## Más música gratis (revisa la licencia de cada pista)

| Fuente | Licencia | ¿Se puede subir al repositorio? |
| --- | --- | --- |
| [FreePD](https://freepd.com) | CC0, sin atribución | Sí |
| [Freesound](https://freesound.org), filtro «Creative Commons 0» | CC0 (otras pistas piden atribución o prohíben uso comercial) | Solo las CC0 |
| [Free Music Archive](https://freemusicarchive.org) | Varía por pista: elige CC0 o CC BY | CC0 sí; CC BY con crédito |
| [Pixabay Music](https://pixabay.com/music/) | Licencia Pixabay: uso comercial sin atribución dentro de un video | **No**: prohíbe distribuir las pistas como archivo suelto; algunas tienen Content ID |

Para regenerar o crear variaciones: `python3 generate_audio_pack.py CARPETA_DE_SALIDA [nombre ...]`
(requiere numpy, scipy y ffmpeg).
