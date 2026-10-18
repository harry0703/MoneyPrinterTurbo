# Playbook: baixar e "assistir" vídeos

## Ferramenta

`yt-dlp` não está instalado globalmente; use via Nix:

```sh
nix shell nixpkgs#yt-dlp nixpkgs#ffmpeg -c yt-dlp ...
```

## Buscar no YouTube sem navegador

```sh
yt-dlp --no-warnings --flat-playlist \
  --print "%(id)s | %(duration_string)s | %(channel)s | %(title)s" "ytsearch8:<consulta>"
```

Funciona igual para TikTok, X/Twitter e Instagram colando a URL.

## Assistir barato (low-res)

```sh
yt-dlp -q --no-warnings -f "bv*[height<=360]" -o "raw/low_%(id)s.%(ext)s" <URL>
```

Contact sheet geral (≈36 quadros):

```sh
ffmpeg -v error -y -i raw/low_ID.mp4 \
  -vf "fps=1/STEP,scale=192:-1,drawtext=text='%{pts\:hms}':x=4:y=4:fontsize=14:fontcolor=yellow:box=1:boxcolor=black,tile=6x6" \
  -frames:v 1 raw/sheet_ID.png
```

**Atenção:** os horários do `fps`+`tile` podem ficar deslocados alguns segundos. Antes de fechar
um trecho, confirme com seek exato, um quadro por horário:

```sh
ffmpeg -v error -y -ss <seg> -i raw/low_ID.mp4 -frames:v 1 -vf scale=320:180 raw/check_<seg>.png
```

Depois abra os PNGs para ver o conteúdo (requer uma IA que enxergue imagens).

## Baixar só o trecho em 1080p

```sh
yt-dlp -q --no-warnings -f "bv*[height<=1080][ext=mp4]/bv*[height<=1080]" --remux-video mp4 \
  --download-sections "*<ini>-<fim>" --force-keyframes-at-cuts -o "raw/hi_ID_<ini>.mp4" <URL>
```

Baixe 1 s a mais de margem nas pontas.

## Problemas conhecidos

- "Sign in to confirm you're not a bot": pule o vídeo e use outro candidato. Não peça cookies.
- Facecam do youtuber, marca d'água, legendas queimadas: anote no shotlist; o editor corta.

## Estudar um canal de referência

Vídeos recentes com visualizações (troque `/shorts` por `/videos` para vídeos longos; `--playlist-end`
limita a quantidade):

```sh
yt-dlp --no-warnings --flat-playlist --playlist-end 15 \
  --print "%(id)s | %(view_count)s | %(title)s" "https://www.youtube.com/@<handle>/shorts"
```

Legenda automática (só no idioma do canal, para não estourar o limite de requisições) e os
primeiros 15 s em texto — é ali que está o gancho:

```sh
yt-dlp -q --no-warnings --skip-download --write-auto-subs --sub-langs "<idioma>-orig,<idioma>" \
  --sub-format vtt -o "raw/ref_%(id)s" "https://www.youtube.com/shorts/<id>"
awk '/-->/{split($1,t,":"); s=t[1]*3600+t[2]*60+t[3]; keep=(s<15); next}
     keep && NF && !/^(WEBVTT|Kind|Language)/{gsub(/<[^>]*>/,""); print}' raw/ref_<id>.<idioma>-orig.vtt | uniq
```

Analise 3–5 dos mais vistos: como abrem, quantas palavras por segundo, como fecham, padrão de
título. Para ritmo de corte, baixe um em ≤360p e gere a contact sheet. Resuma em
`research.md` na seção "Referências de estilo" — padrões, não frases copiadas.
